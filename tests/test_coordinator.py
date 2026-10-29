"""Regression tests for both Pi-hole API families and failure recovery."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.pihole_presence import coordinator as module
from custom_components.pihole_presence.const import (
    API_MODE_LEGACY,
    API_MODE_V6,
    ATTR_LAST_QUERY,
    AUTH_ENDPOINT,
    DEVICES_ENDPOINT,
    LEGACY_NETWORK_ENDPOINT,
)
from custom_components.pihole_presence.coordinator import (
    PiholeApiError,
    PiholeAuthError,
    PiholeNotFoundError,
    PiholeRateLimitError,
    _as_timestamp,
    _legacy_network_to_devices,
)

MAC = "aa:bb:cc:dd:ee:02"


def device(**updates):
    return {
        "hwaddr": MAC,
        "interface": "eth0",
        "firstSeen": 1600000000,
        "lastQuery": datetime.now(timezone.utc).timestamp() - 5,
        "numQueries": 42,
        "macVendor": "Example",
        "ips": [{"ip": "192.168.1.20", "name": "phone"}],
        **updates,
    }


def response(coordinator, body, status=200, headers=None):
    result = MagicMock(status=status, headers=headers or {})
    result.text = AsyncMock(
        return_value=json.dumps(body) if not isinstance(body, str) else body
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=result)
    context.__aexit__ = AsyncMock(return_value=False)
    coordinator._session.request.return_value = context
    return result


@pytest.mark.asyncio
async def test_timeout_is_actionable_and_recovers(coordinator):
    coordinator._fetch_data = AsyncMock(side_effect=asyncio.TimeoutError())
    with pytest.raises(UpdateFailed, match="Timed out connecting.*30 seconds"):
        await coordinator._async_update_data()
    with pytest.raises(UpdateFailed, match="backed off"):
        await coordinator._async_update_data()
    coordinator._fetch_data.assert_awaited_once()
    coordinator._retry_not_before = 0
    coordinator._fetch_data = AsyncMock(return_value=([], [device()]))
    assert MAC in await coordinator._async_update_data()
    assert coordinator._consecutive_failures == 0
    assert coordinator._retry_not_before == 0


@pytest.mark.asyncio
async def test_auth_requests_reauthentication_without_network_backoff(coordinator):
    coordinator._fetch_data = AsyncMock(
        side_effect=PiholeAuthError("Invalid credentials")
    )
    with pytest.raises(ConfigEntryAuthFailed, match="Invalid credentials"):
        await coordinator._async_update_data()
    assert coordinator._consecutive_failures == 0


@pytest.mark.asyncio
async def test_backoff_and_retry_after(coordinator):
    coordinator._fetch_data = AsyncMock(side_effect=PiholeApiError("Unavailable"))
    for delay in (30, 60, 120, 240, 300, 300):
        coordinator._retry_not_before = 0
        with pytest.raises(UpdateFailed, match=f"retrying in {delay} seconds"):
            await coordinator._async_update_data()
    coordinator._retry_not_before = 0
    coordinator._fetch_data.side_effect = PiholeRateLimitError("Busy", 600)
    with pytest.raises(UpdateFailed, match="600 seconds"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,error",
    [
        (401, {}, PiholeAuthError),
        (403, {}, PiholeAuthError),
        (404, {}, PiholeNotFoundError),
        (429, {}, PiholeRateLimitError),
        (503, {}, PiholeRateLimitError),
        (500, "private response and secret", PiholeApiError),
        (200, "Not authorized!", PiholeAuthError),
        (200, {"error": {"key": "unauthorized"}}, PiholeAuthError),
        (200, {"error": {"key": "not_found"}}, PiholeNotFoundError),
        (200, {"error": {"key": "database_error"}}, PiholeApiError),
        (200, "<html>Login page</html>", PiholeApiError),
    ],
)
async def test_http_failures_do_not_expose_response_or_token(
    coordinator, status, body, error
):
    response(coordinator, body, status, {"Retry-After": "120"})
    with pytest.raises(error) as caught:
        await coordinator._fetch_json("/test", params={"auth": "private-token"})
    assert "private" not in str(caught.value)
    if isinstance(caught.value, PiholeRateLimitError):
        assert caught.value.retry_after == 120


@pytest.mark.asyncio
async def test_http_requests_close_connections_but_keep_session_auth(coordinator):
    response(coordinator, {"devices": []})
    await coordinator._fetch_json(
        DEVICES_ENDPOINT, headers={"X-FTL-SID": "test-session"}
    )
    assert coordinator._session.request.call_args.kwargs["headers"] == {
        "Connection": "close",
        "X-FTL-SID": "test-session",
    }


@pytest.mark.asyncio
async def test_reuses_sessions_and_preserves_password_whitespace(coordinator):
    coordinator._password = " password with spaces "
    coordinator._fetch_json = AsyncMock(
        side_effect=[
            {"session": {"valid": True, "sid": "our-session", "validity": 1}},
            {"devices": []},
            {"devices": []},
            {},
        ]
    )
    await coordinator._fetch_v6_json(DEVICES_ENDPOINT)
    await coordinator._fetch_v6_json(DEVICES_ENDPOINT)
    assert coordinator._fetch_json.await_count == 3
    assert coordinator._fetch_json.await_args_list[0].kwargs["json_payload"] == {
        "password": " password with spaces "
    }
    await coordinator.async_close()
    coordinator._fetch_json.assert_awaited_with(
        AUTH_ENDPOINT, method="DELETE", headers={"X-FTL-SID": "our-session"}, timeout=3
    )
    await coordinator.async_close()
    assert coordinator._fetch_json.await_count == 4
    coordinator._session.close.assert_not_called()


@pytest.mark.asyncio
async def test_expired_session_reauthenticates_once(coordinator):
    coordinator._password = "password"
    coordinator._sid = "expired"
    coordinator._session_authenticated = True
    coordinator._fetch_json = AsyncMock(
        side_effect=[
            PiholeAuthError("Expired"),
            {"session": {"valid": True, "sid": "fresh", "validity": 300}},
            {"devices": []},
        ]
    )
    assert await coordinator._fetch_v6_json(DEVICES_ENDPOINT) == {"devices": []}
    assert coordinator._sid == "fresh"
    assert coordinator._fetch_json.await_count == 3


@pytest.mark.asyncio
async def test_invalid_password_does_not_retry_forever(coordinator):
    coordinator._password = "bad"
    coordinator._fetch_json = AsyncMock(side_effect=PiholeAuthError("Bad password"))
    with pytest.raises(PiholeAuthError):
        await coordinator._fetch_v6_json(DEVICES_ENDPOINT)
    coordinator._fetch_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_detection_is_cached_and_handles_v5_upgrade(coordinator):
    coordinator._fetch_v6_data = AsyncMock(side_effect=PiholeNotFoundError())
    coordinator._fetch_legacy_data = AsyncMock(return_value=([], []))
    await coordinator._fetch_data()
    await coordinator._fetch_data()
    assert coordinator._resolved_api_mode == API_MODE_LEGACY
    coordinator._fetch_v6_data.assert_awaited_once()
    coordinator._fetch_legacy_data.side_effect = PiholeNotFoundError()
    coordinator._fetch_v6_data.side_effect = None
    coordinator._fetch_v6_data.return_value = ([], [])
    await coordinator._fetch_data()
    assert coordinator._resolved_api_mode == API_MODE_V6


@pytest.mark.asyncio
async def test_v6_auth_failure_never_falls_back_to_legacy(coordinator):
    coordinator._fetch_v6_data = AsyncMock(side_effect=PiholeAuthError())
    coordinator._fetch_legacy_data = AsyncMock()
    with pytest.raises(PiholeAuthError):
        await coordinator._fetch_data()
    coordinator._fetch_legacy_data.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [API_MODE_LEGACY, API_MODE_V6])
async def test_explicit_api_mode_does_not_fallback(coordinator, mode):
    coordinator._api_mode = mode
    coordinator._fetch_v6_data = AsyncMock(side_effect=PiholeNotFoundError())
    coordinator._fetch_legacy_data = AsyncMock(side_effect=PiholeNotFoundError())
    with pytest.raises(PiholeNotFoundError):
        await coordinator._fetch_data()
    assert coordinator._fetch_v6_data.await_count == (mode == API_MODE_V6)
    assert coordinator._fetch_legacy_data.await_count == (mode == API_MODE_LEGACY)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,error",
    [
        ([], PiholeAuthError),
        ({}, PiholeAuthError),
        ({"network": []}, None),
        ({"something": []}, PiholeApiError),
    ],
)
async def test_legacy_auth_and_empty_network(coordinator, body, error):
    coordinator._api_token = "test-token"
    coordinator._fetch_json = AsyncMock(return_value=body)
    if error:
        with pytest.raises(error):
            await coordinator._fetch_legacy_data()
    else:
        assert await coordinator._fetch_legacy_data() == ([], [])
    coordinator._fetch_json.assert_awaited_with(
        LEGACY_NETWORK_ENDPOINT, params={"network": "", "auth": "test-token"}
    )


@pytest.mark.asyncio
async def test_legacy_numeric_strings_and_missing_values(coordinator):
    now = str(datetime.now(timezone.utc).timestamp())
    rows = _legacy_network_to_devices(
        [
            None,
            {
                "hwaddr": MAC.upper(),
                "lastQuery": now,
                "firstSeen": "1600000000",
                "ip": ["192.168.1.20", "fd00::20"],
                "name": ["phone", None],
            },
        ]
    )
    data = coordinator._normalize_data([], rows)
    assert data[MAC][ATTR_LAST_QUERY] == float(now)
    assert data[MAC]["name"] == "phone"
    assert data[MAC]["ip_addresses"] == ["192.168.1.20", "fd00::20"]


@pytest.mark.asyncio
async def test_optional_failures_never_take_trackers_offline(coordinator):
    coordinator._fetch_v6_json = AsyncMock(
        side_effect=[{"devices": [device()]}, PiholeApiError("DHCP unavailable")]
    )
    coordinator._refresh_recent_query_times = AsyncMock(
        side_effect=asyncio.TimeoutError()
    )
    coordinator._fetch_v6_host_metrics = AsyncMock(return_value={})
    data = await coordinator._async_update_data()
    assert MAC in data
    assert coordinator._consecutive_failures == 0


@pytest.mark.asyncio
async def test_optional_rate_limit_does_not_block_required_data(coordinator):
    coordinator._fetch_v6_json = AsyncMock(return_value={"devices": [device()]})
    coordinator._refresh_recent_query_times = AsyncMock(
        side_effect=PiholeRateLimitError("Busy", 600)
    )
    for _ in range(2):
        assert MAC in await coordinator._async_update_data()
    coordinator._refresh_recent_query_times.assert_awaited_once()
    assert coordinator._fetch_v6_json.await_count == 2


@pytest.mark.asyncio
async def test_optional_query_budget_includes_authentication_and_all_pages(
    coordinator, monkeypatch
):
    monkeypatch.setattr(module, "_QUERY_FETCH_BUDGET_SECONDS", 0.01)
    coordinator._fetch_v6_json = AsyncMock(return_value={"devices": [device()]})
    coordinator._supplemental_refresh_due = module.monotonic() + 300
    coordinator._refresh_recent_query_times = asyncio.Event().wait
    assert MAC in await asyncio.wait_for(coordinator._async_update_data(), timeout=1)
    assert not coordinator.query_activity_complete


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"devices": {}}, [], {"error": "bad"}])
async def test_bad_network_response_is_not_an_empty_success(coordinator, body):
    coordinator._fetch_v6_json = AsyncMock(return_value=body)
    with pytest.raises(PiholeApiError):
        await coordinator._fetch_v6_data()


@pytest.mark.asyncio
async def test_validation_does_not_fetch_optional_data(coordinator):
    coordinator._fetch_v6_json = AsyncMock(return_value={"devices": []})
    await coordinator.async_validate_connection()
    coordinator._fetch_v6_json.assert_awaited_once_with(DEVICES_ENDPOINT)


@pytest.mark.asyncio
async def test_queries_follow_cursor_even_when_server_caps_page_length(coordinator):
    now = datetime.now(timezone.utc).timestamp()
    coordinator._fetch_v6_json = AsyncMock(
        side_effect=[
            {
                "queries": [{"time": now, "client": {"ip": "192.168.1.20"}}],
                "cursor": 100,
            },
            {
                "queries": [{"time": now - 1, "client": {"ip": "fd00::20"}}],
                "cursor": 99,
            },
            {"queries": [], "cursor": 0},
        ]
    )
    await coordinator._refresh_recent_query_times()
    assert coordinator._recent_query_by_ip == {"192.168.1.20": now, "fd00::20": now - 1}
    assert coordinator.query_activity_complete
    assert (
        coordinator._fetch_v6_json.await_args_list[1].kwargs["params"]["cursor"]
        == "100"
    )


@pytest.mark.asyncio
async def test_query_pagination_is_bounded(coordinator):
    now = datetime.now(timezone.utc).timestamp()
    coordinator._fetch_v6_json = AsyncMock(
        side_effect=[
            {"queries": [{"time": now, "client": {"ip": "192.168.1.20"}}], "cursor": i}
            for i in range(100, 80, -1)
        ]
    )
    await coordinator._refresh_recent_query_times()
    assert coordinator._fetch_v6_json.await_count == module._QUERY_FETCH_MAX_PAGES
    assert not coordinator.query_activity_complete


@pytest.mark.asyncio
async def test_normalization_skips_bad_and_stale_devices(coordinator):
    data = coordinator._normalize_data(
        [],
        [
            None,
            device(hwaddr="invalid"),
            device(hwaddr="00:00:00:00:00:00"),
            device(interface="lo"),
            device(lastQuery=1),
            device(lastQuery="nan"),
            device(),
        ],
    )
    assert list(data) == [MAC]


@pytest.mark.parametrize(
    "value", [None, True, False, "nan", "inf", float("inf"), 10**100, -1, 0, {}, []]
)
def test_invalid_timestamps(value):
    assert _as_timestamp(value) is None
