"""Exercise flows with HA's own classes, including read-only config_entry."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.pihole_presence import config_flow as module
from custom_components.pihole_presence.coordinator import PiholeAuthError
from custom_components.pihole_presence.util import normalize_host


@pytest.mark.parametrize(
    "value,expected",
    [
        ("pi.hole", "http://pi.hole"),
        (" 192.168.1.2 ", "http://192.168.1.2"),
        ("http://pi.hole/admin/", "http://pi.hole"),
        ("https://pi.hole:8443/admin/index.php", "https://pi.hole:8443"),
        (
            "https://example.com/pihole/api/?test=1#ignored",
            "https://example.com/pihole",
        ),
        ("https://example.com/pihole/", "https://example.com/pihole"),
        ("[fd00::2]:8080", "http://[fd00::2]:8080"),
        ("fd00::2", "http://[fd00::2]"),
    ],
)
def test_host_normalization(value, expected):
    assert normalize_host(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "ftp://pi.hole",
        "http://",
        "http://user:pass@pi.hole",
        "http://bad host",
        "http://pi.hole:99999",
    ],
)
def test_invalid_host(value):
    with pytest.raises(ValueError):
        normalize_host(value)


@pytest.mark.asyncio
async def test_options_open_and_use_existing_overrides(hass):
    entry = SimpleNamespace(
        data={"host": "http://pi.hole", "scan_interval": 30},
        options={"scan_interval": 120},
    )
    flow = module.PiholePresenceConfigFlow.async_get_options_flow(entry)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] == "form"
    defaults = result["data_schema"](
        {
            "host": "http://pi.hole",
            "api_mode": "auto",
            "away_time": 900,
            "stale_device_days": 30,
        }
    )
    assert defaults["scan_interval"] == 120


@pytest.mark.asyncio
async def test_options_validate_and_retain_existing_values(hass, monkeypatch):
    entry = SimpleNamespace(
        data={"host": "http://pi.hole", "away_time": 900},
        options={"scan_interval": 120, "password": "secret"},
    )
    flow = module.OptionsFlowHandler(entry)
    flow.hass = hass
    validate = AsyncMock(return_value={})
    monkeypatch.setattr(module, "_validate_input", validate)
    result = await flow.async_step_init({"scan_interval": 60})
    assert result["type"] == "create_entry"
    assert result["data"] == {
        "host": "http://pi.hole",
        "away_time": 900,
        "scan_interval": 60,
        "password": "secret",
    }


@pytest.mark.asyncio
async def test_bad_auth_stays_in_form_and_releases_session(hass, monkeypatch):
    client = MagicMock()
    client.async_validate_connection = AsyncMock(side_effect=PiholeAuthError())
    client.async_close = AsyncMock()
    monkeypatch.setattr(
        module, "PiholeUpdateCoordinator", MagicMock(return_value=client)
    )
    entry = SimpleNamespace(data={"host": "pi.hole"}, options={})
    flow = module.OptionsFlowHandler(entry)
    flow.hass = hass
    result = await flow.async_step_init({"password": "bad"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}
    client.async_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_host_is_reported_without_http(hass, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(module, "PiholeUpdateCoordinator", client)
    assert await module._validate_input(hass, {"host": "ftp://pi.hole"}) == {
        "host": "invalid_host"
    }
    client.assert_not_called()


@pytest.mark.asyncio
async def test_new_config_entry_is_validated(hass, monkeypatch):
    flow = module.PiholePresenceConfigFlow()
    flow.hass = hass
    monkeypatch.setattr(module, "_validate_input", AsyncMock(return_value={}))
    monkeypatch.setattr(flow, "_async_current_entries", lambda: [])
    result = await flow.async_step_user({"host": "http://pi.hole"})
    assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_duplicate_check_uses_effective_host_from_options(hass, monkeypatch):
    flow = module.PiholePresenceConfigFlow()
    flow.hass = hass
    monkeypatch.setattr(module, "_validate_input", AsyncMock(return_value={}))
    monkeypatch.setattr(
        flow,
        "_async_current_entries",
        lambda: [
            SimpleNamespace(
                data={"host": "http://old.host"},
                options={"host": "http://pi.hole/admin"},
            )
        ],
    )
    result = await flow.async_step_user({"host": "http://pi.hole"})
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_reauth_preserves_entry_and_options(hass, monkeypatch):
    entry = SimpleNamespace(
        entry_id="existing",
        data={"host": "http://pi.hole", "away_time": 900},
        options={"scan_interval": 120},
    )
    flow = module.PiholePresenceConfigFlow()
    flow.hass = hass
    flow.context = {"entry_id": "existing", "source": "reauth"}
    hass.config_entries.async_get_entry.return_value = entry
    hass.config_entries.async_reload = AsyncMock()
    monkeypatch.setattr(module, "_validate_input", AsyncMock(return_value={}))
    assert (await flow.async_step_reauth({}))["step_id"] == "reauth_confirm"
    result = await flow.async_step_reauth_confirm({"password": "new password"})
    assert result["reason"] == "reauth_successful"
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            "host": "http://pi.hole",
            "away_time": 900,
            "scan_interval": 120,
            "password": "new password",
        },
        options={},
    )
    hass.config_entries.async_reload.assert_awaited_once_with("existing")
