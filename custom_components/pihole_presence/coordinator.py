from __future__ import annotations

import asyncio
import inspect
import ipaddress
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_MODE_AUTO,
    API_MODE_LEGACY,
    API_MODE_OPTIONS,
    API_MODE_V6,
    ATTR_DHCP_EXPIRES,
    ATTR_FIRST_SEEN,
    ATTR_INTERFACE,
    ATTR_IP_ADDRESSES,
    ATTR_IPS,
    ATTR_LAST_QUERY,
    ATTR_LAST_SEEN,
    ATTR_MAC_VENDOR,
    ATTR_NAME,
    ATTR_NUM_QUERIES,
    ATTR_PRIMARY_IP,
    AUTH_ENDPOINT,
    DEVICES_ENDPOINT,
    LEASES_ENDPOINT,
    LEGACY_NETWORK_ENDPOINT,
    QUERIES_ENDPOINT,
    SENSORS_ENDPOINT,
    SYSTEM_ENDPOINT,
)
from .util import normalize_host

_LOGGER = logging.getLogger(__name__)
_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
_SUPPLEMENTAL_REFRESH_SECONDS = 300
_MAX_RETRY_BACKOFF_SECONDS = 300
_QUERY_FETCH_OVERLAP_SECONDS = 5
_QUERY_FETCH_LIMIT = 1000
_QUERY_FETCH_MAX_PAGES = 5
_QUERY_FETCH_BUDGET_SECONDS = 8
_COORDINATOR_HAS_CONFIG_ENTRY = (
    "config_entry" in inspect.signature(DataUpdateCoordinator).parameters
)


def _clean_mac(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    mac = value.lower().strip()
    if mac == "00:00:00:00:00:00":
        return None
    if _MAC_RE.match(mac):
        return mac
    return None


def _clean_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or name == "*":
        return None
    return name


def _as_timestamp(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value <= 0 or value > 253402300799:
        return None
    return value


def _clean_ip(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        return None
    return str(ip)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


class PiholeApiError(Exception):
    """Base Pi-hole API error."""


class PiholeAuthError(PiholeApiError):
    """Pi-hole rejected the configured credentials."""


class PiholeNotFoundError(PiholeApiError):
    """The requested Pi-hole API endpoint does not exist."""


class PiholeRateLimitError(PiholeApiError):
    """Pi-hole asked the client to wait before retrying."""

    def __init__(self, message: str, retry_after: float = 60) -> None:
        super().__init__(message)
        self.retry_after = min(max(retry_after, 1), 3600)


def _retry_after(value: str | None) -> float:
    """Read both forms of the HTTP Retry-After header."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        try:
            result = (
                parsedate_to_datetime(value).timestamp()
                - datetime.now(timezone.utc).timestamp()
            )
        except (TypeError, ValueError, OverflowError):
            return 60
    return result if math.isfinite(result) else 60


class PiholeUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and normalize Pi-hole network device data."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        scan_interval: int,
        stale_device_days: int,
        presence_window: int = 900,
        password: str | None = None,
        api_token: str | None = None,
        api_mode: str = API_MODE_AUTO,
        config_entry: ConfigEntry | None = None,
    ):
        self._host = normalize_host(host)
        self._stale_after = timedelta(days=stale_device_days)
        self._presence_window = max(30, presence_window)
        self._password = password or ""
        self._api_token = (api_token or "").strip()
        self._api_mode = api_mode if api_mode in API_MODE_OPTIONS else API_MODE_AUTO
        self._sid: str | None = None
        self._session_authenticated = False
        self._resolved_api_mode: str | None = None
        self._cached_leases: list[Any] = []
        self._recent_query_by_ip: dict[str, float] = {}
        self._last_query_fetch_at: float | None = None
        self.query_activity_complete: bool | None = None
        self._supplemental_refresh_due = 0.0
        self._optional_retry_not_before = 0.0
        self._consecutive_failures = 0
        self._retry_not_before = 0.0
        self.host_metrics: dict[str, Any] = {}
        self._session = async_get_clientsession(hass)
        super().__init__(
            hass,
            _LOGGER,
            name="Pi-hole Presence",
            update_interval=timedelta(seconds=scan_interval),
            **({"config_entry": config_entry} if _COORDINATOR_HAS_CONFIG_ENTRY else {}),
        )

    async def _fetch_json(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
        timeout: float = 10,
    ) -> Any:
        url = f"{self._host}{endpoint}"
        async with self._session.request(
            method,
            url,
            # End each HTTP connection so embedded Pi-hole web servers do not
            # retain idle keep-alive worker slots. API sessions are independent
            # and remain reusable via X-FTL-SID.
            headers={"Connection": "close", **(headers or {})},
            params=params,
            json=json_payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            text = await resp.text()
            if resp.status in (401, 403):
                raise PiholeAuthError(
                    f"Pi-hole API rejected authentication for {endpoint}"
                )
            if resp.status == 404:
                raise PiholeNotFoundError(f"Pi-hole API endpoint not found: {endpoint}")
            if resp.status in (429, 503):
                raise PiholeRateLimitError(
                    f"Pi-hole API is busy (HTTP {resp.status})",
                    _retry_after(resp.headers.get("Retry-After")),
                )
            if resp.status >= 400:
                raise PiholeApiError(
                    f"Pi-hole API endpoint {endpoint} returned HTTP {resp.status}"
                )
            if text.strip() == "Not authorized!":
                raise PiholeAuthError(
                    "Pi-hole legacy API rejected the configured API token"
                )
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError as err:
                raise PiholeApiError(
                    f"Pi-hole API endpoint {endpoint} did not return JSON"
                ) from err
            if _is_unauthorized_response(data):
                raise PiholeAuthError(
                    f"Pi-hole API rejected authentication for {endpoint}"
                )
            if isinstance(data, dict) and data.get("error"):
                error = data["error"]
                key = error.get("key") if isinstance(error, dict) else None
                if key == "not_found":
                    raise PiholeNotFoundError(
                        f"Pi-hole API endpoint not found: {endpoint}"
                    )
                raise PiholeApiError(f"Pi-hole API returned an error for {endpoint}")
            return data

    async def _ensure_v6_session(self, *, force: bool = False) -> None:
        if not self._password:
            return

        # Pi-hole extends a session on every request. Reuse it until rejected,
        # rather than allocating another seat at its original expiry time.
        if not force and self._session_authenticated:
            return

        data = await self._fetch_json(
            AUTH_ENDPOINT,
            method="POST",
            json_payload={"password": self._password},
        )
        if not isinstance(data, dict):
            raise PiholeApiError("Unexpected Pi-hole v6 authentication response")
        session = data.get("session")
        if not isinstance(session, dict) or not session.get("valid"):
            message = None
            if isinstance(session, dict):
                message = _clean_name(session.get("message"))
            detail = f": {message}" if message else ""
            raise PiholeAuthError(f"Pi-hole v6 authentication failed{detail}")

        sid = session.get("sid")
        self._sid = sid if isinstance(sid, str) and sid else None
        self._session_authenticated = True

    async def async_close(self) -> None:
        """Release only this integration's Pi-hole session, never HA's client."""
        sid, self._sid = self._sid, None
        self._session_authenticated = False
        if sid:
            try:
                await self._fetch_json(
                    AUTH_ENDPOINT,
                    method="DELETE",
                    headers={"X-FTL-SID": sid},
                    timeout=3,
                )
            except (aiohttp.ClientError, asyncio.TimeoutError, PiholeApiError):
                _LOGGER.debug("Unable to end Pi-hole API session; it will expire")

    async def _fetch_v6_json(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        retry_auth: bool = True,
        timeout: float = 10,
    ) -> dict[str, Any]:
        await self._ensure_v6_session()
        headers = {"X-FTL-SID": self._sid} if self._sid else None

        try:
            return await self._fetch_json(
                endpoint,
                headers=headers,
                params=params,
                timeout=timeout,
            )
        except PiholeAuthError:
            if self._password and retry_auth:
                self._sid = None
                self._session_authenticated = False
                await self._ensure_v6_session(force=True)
                return await self._fetch_v6_json(
                    endpoint,
                    params=params,
                    retry_auth=False,
                    timeout=timeout,
                )
            if not self._password:
                raise PiholeAuthError(
                    "Pi-hole v6 requires authentication; configure the Pi-hole "
                    "password in this integration's options"
                )
            raise

    async def _fetch_v6_data(
        self, *, supplemental: bool = True
    ) -> tuple[list[Any], list[Any]]:
        devices_json = await self._fetch_v6_json(DEVICES_ENDPOINT)
        if not isinstance(devices_json, dict):
            raise PiholeApiError("Unexpected Pi-hole v6 API response")
        devices = devices_json.get("devices")
        if not isinstance(devices, list):
            raise PiholeApiError("Unexpected Pi-hole v6 API response")

        if not supplemental:
            return [], devices

        if monotonic() < self._optional_retry_not_before:
            return self._cached_leases, devices

        try:
            await asyncio.wait_for(
                self._refresh_recent_query_times(),
                timeout=_QUERY_FETCH_BUDGET_SECONDS,
            )
        except PiholeNotFoundError:
            self.query_activity_complete = False
            _LOGGER.debug("Pi-hole query API not found; using network-table timestamps")
        except (aiohttp.ClientError, asyncio.TimeoutError, PiholeApiError) as err:
            self.query_activity_complete = False
            _LOGGER.debug(
                "Unable to refresh recent Pi-hole queries; using cached data: %s",
                err,
            )
            if isinstance(err, PiholeRateLimitError):
                self._optional_retry_not_before = monotonic() + err.retry_after
                return self._cached_leases, devices

        now = monotonic()
        if now >= self._supplemental_refresh_due:
            # Presence only depends on the network devices response. DHCP leases
            # and host metrics are supplemental, so fetch them less frequently
            # and never let a supplemental endpoint take every tracker offline.
            self._supplemental_refresh_due = now + _SUPPLEMENTAL_REFRESH_SECONDS
            try:
                leases_json = await self._fetch_v6_json(LEASES_ENDPOINT, timeout=5)
                if not isinstance(leases_json, dict):
                    raise PiholeApiError("Unexpected Pi-hole v6 DHCP leases response")
                leases = leases_json.get("leases", [])
                if not isinstance(leases, list):
                    raise PiholeApiError("Unexpected Pi-hole v6 DHCP leases response")
                self._cached_leases = leases
            except PiholeNotFoundError:
                self._cached_leases = []
            except (aiohttp.ClientError, asyncio.TimeoutError, PiholeApiError) as err:
                _LOGGER.debug(
                    "Unable to refresh Pi-hole DHCP leases; using cached data: %s",
                    err,
                )
                if isinstance(err, PiholeRateLimitError):
                    self._optional_retry_not_before = monotonic() + err.retry_after
                    return self._cached_leases, devices

            self.host_metrics = await self._fetch_v6_host_metrics()

        return self._cached_leases, devices

    async def _refresh_recent_query_times(self) -> None:
        fetch_until = datetime.now(timezone.utc).timestamp()
        if self._last_query_fetch_at is None:
            fetch_from = fetch_until - self._presence_window
        else:
            fetch_from = max(
                fetch_until - self._presence_window,
                self._last_query_fetch_at - _QUERY_FETCH_OVERLAP_SECONDS,
            )

        cursor: int | None = None
        seen_cursors: set[int] = set()
        reached_page_limit = False
        self.query_activity_complete = False
        deadline = monotonic() + _QUERY_FETCH_BUDGET_SECONDS

        for page in range(_QUERY_FETCH_MAX_PAGES):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            params = {
                "from": str(fetch_from),
                "until": str(fetch_until),
                "length": str(_QUERY_FETCH_LIMIT),
            }
            if cursor is not None:
                params["cursor"] = str(cursor)

            response = await self._fetch_v6_json(
                QUERIES_ENDPOINT,
                params=params,
                timeout=min(5, remaining),
            )
            queries = response.get("queries") if isinstance(response, dict) else None
            if not isinstance(queries, list):
                raise PiholeApiError("Unexpected Pi-hole v6 queries response")

            for query in queries:
                if not isinstance(query, dict):
                    continue
                client = query.get("client")
                if not isinstance(client, dict):
                    continue
                ip = _clean_ip(client.get("ip"))
                query_time = _as_timestamp(query.get("time"))
                if ip and query_time:
                    self._recent_query_by_ip[ip] = max(
                        query_time,
                        self._recent_query_by_ip.get(ip, 0),
                    )

            next_cursor = response.get("cursor")
            if not queries or (isinstance(next_cursor, int) and next_cursor <= 0):
                self.query_activity_complete = True
                break
            if not isinstance(next_cursor, int):
                self.query_activity_complete = len(queries) < _QUERY_FETCH_LIMIT
                break
            if next_cursor in seen_cursors:
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if page == _QUERY_FETCH_MAX_PAGES - 1:
                reached_page_limit = True

        cutoff = fetch_until - self._presence_window
        self._recent_query_by_ip = {
            ip: query_time
            for ip, query_time in self._recent_query_by_ip.items()
            if query_time >= cutoff
        }
        self._last_query_fetch_at = fetch_until

        if reached_page_limit:
            _LOGGER.debug(
                "Pi-hole returned more than %s recent queries; "
                "older activity may be omitted from this update",
                _QUERY_FETCH_LIMIT * _QUERY_FETCH_MAX_PAGES,
            )

    async def _fetch_v6_host_metrics(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        endpoints = (
            (SYSTEM_ENDPOINT, "system"),
            (SENSORS_ENDPOINT, "sensors"),
        )

        for endpoint, key in endpoints:
            try:
                response = await self._fetch_v6_json(endpoint, timeout=5)
            except PiholeNotFoundError:
                continue
            except (aiohttp.ClientError, asyncio.TimeoutError, PiholeApiError) as err:
                _LOGGER.debug("Unable to fetch Pi-hole host metric %s: %s", key, err)
                if isinstance(err, PiholeRateLimitError):
                    self._optional_retry_not_before = monotonic() + err.retry_after
                    break
                continue

            value = response.get(key) if isinstance(response, dict) else None
            if isinstance(value, dict):
                metrics[key] = value

        return metrics

    async def _fetch_legacy_data(self) -> tuple[list[Any], list[Any]]:
        params = {"network": ""}
        if self._api_token:
            params["auth"] = self._api_token

        network_json = await self._fetch_json(LEGACY_NETWORK_ENDPOINT, params=params)
        network = (
            network_json.get("network")
            if isinstance(network_json, dict)
            else network_json
        )
        # Pi-hole v5's api_db.php returns an empty PHP array ([]) on auth
        # failure, but {"network": []} when authenticated with no devices.
        if network_json == [] or network_json == {}:
            raise PiholeAuthError("Pi-hole legacy API requires a valid API token")
        if not isinstance(network, list):
            raise PiholeApiError("Unexpected Pi-hole legacy network response")

        return [], _legacy_network_to_devices(network)

    async def _fetch_data(
        self, *, supplemental: bool = True
    ) -> tuple[list[Any], list[Any]]:
        """Remember API discovery, but detect upgrades when an endpoint disappears."""
        mode = self._resolved_api_mode or self._api_mode
        if mode in (API_MODE_AUTO, API_MODE_V6):
            try:
                result = await self._fetch_v6_data(supplemental=supplemental)
                self._resolved_api_mode = API_MODE_V6
                return result
            except PiholeNotFoundError:
                if self._api_mode != API_MODE_AUTO:
                    raise
        try:
            result = await self._fetch_legacy_data()
        except PiholeNotFoundError:
            if mode != API_MODE_LEGACY or self._api_mode != API_MODE_AUTO:
                raise
            self._resolved_api_mode = None
            result = await self._fetch_v6_data(supplemental=supplemental)
            self._resolved_api_mode = API_MODE_V6
            return result
        self._resolved_api_mode = API_MODE_LEGACY
        self.host_metrics = {}
        self.query_activity_complete = None
        return result

    async def async_validate_connection(self) -> None:
        """Validate only required network data, keeping form submission cheap."""
        await self._fetch_data(supplemental=False)

    async def _async_update_data(self) -> dict[str, Any]:
        now = monotonic()
        if now < self._retry_not_before:
            retry_in = max(1, round(self._retry_not_before - now))
            raise UpdateFailed(
                f"Pi-hole API retry is backed off for {retry_in} more seconds"
            )

        try:
            leases, devices = await self._fetch_data()
            data = self._normalize_data(leases, devices)
            self._record_update_success()
            return data
        except PiholeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (aiohttp.ClientError, asyncio.TimeoutError, PiholeApiError) as err:
            self._consecutive_failures += 1
            base_interval = max(1, self.update_interval.total_seconds())
            exponent = min(self._consecutive_failures - 1, 10)
            backoff = min(
                base_interval * (2**exponent),
                _MAX_RETRY_BACKOFF_SECONDS,
            )
            if isinstance(err, PiholeRateLimitError):
                backoff = max(backoff, err.retry_after)
            self._retry_not_before = monotonic() + backoff
            detail = str(err)
            if isinstance(err, asyncio.TimeoutError):
                detail = "Timed out connecting to the Pi-hole web/API server; DNS may still be working"
            elif isinstance(err, aiohttp.ClientError):
                detail = f"Cannot connect to the Pi-hole web/API server ({type(err).__name__})"
            raise UpdateFailed(
                f"{detail}; retrying in {round(backoff)} seconds"
            ) from err

    def _record_update_success(self) -> None:
        self._consecutive_failures = 0
        self._retry_not_before = 0.0

    def _normalize_data(
        self, leases: list[Any], devices: list[Any]
    ) -> dict[str, dict[str, Any]]:
        now = datetime.now(timezone.utc).timestamp()
        stale_cutoff = now - self._stale_after.total_seconds()
        merged: dict[str, dict[str, Any]] = {}

        for lease in leases:
            if not isinstance(lease, dict):
                continue
            mac = _clean_mac(lease.get("hwaddr"))
            if not mac:
                continue
            entry = merged.setdefault(mac, {ATTR_IP_ADDRESSES: set()})
            if ip := _clean_ip(lease.get("ip")):
                entry[ATTR_IP_ADDRESSES].add(ip)
            if name := _clean_name(lease.get("name")):
                entry[ATTR_NAME] = name
            if expires := _as_timestamp(lease.get("expires")):
                entry[ATTR_DHCP_EXPIRES] = expires

        for dev in devices:
            if not isinstance(dev, dict):
                continue
            if dev.get("interface") == "lo":
                continue
            mac = _clean_mac(dev.get("hwaddr"))
            if not mac:
                continue
            last_query = _as_timestamp(dev.get("lastQuery"))
            for ip_entry in _as_list(dev.get("ips")):
                if not isinstance(ip_entry, dict):
                    continue
                ip = _clean_ip(ip_entry.get("ip"))
                if ip and ip in self._recent_query_by_ip:
                    last_query = max(
                        last_query or 0,
                        self._recent_query_by_ip[ip],
                    )
            if last_query is None or last_query < stale_cutoff:
                continue

            entry = merged.setdefault(mac, {ATTR_IP_ADDRESSES: set()})
            entry.update(
                {
                    ATTR_INTERFACE: dev.get("interface"),
                    ATTR_FIRST_SEEN: _as_timestamp(dev.get("firstSeen")),
                    ATTR_LAST_QUERY: last_query,
                    ATTR_NUM_QUERIES: dev.get("numQueries"),
                    ATTR_MAC_VENDOR: _clean_name(dev.get("macVendor")),
                }
            )

            for ip_entry in _as_list(dev.get("ips")):
                if not isinstance(ip_entry, dict):
                    continue
                if ip := _clean_ip(ip_entry.get("ip")):
                    entry[ATTR_IP_ADDRESSES].add(str(ip))
                    entry.setdefault(ATTR_PRIMARY_IP, str(ip))
                if last_seen := _as_timestamp(ip_entry.get("lastSeen")):
                    entry[ATTR_LAST_SEEN] = max(last_seen, entry.get(ATTR_LAST_SEEN, 0))
                if not entry.get(ATTR_NAME) and (
                    name := _clean_name(ip_entry.get("name"))
                ):
                    entry[ATTR_NAME] = name

        merged = {
            mac: info
            for mac, info in merged.items()
            if isinstance(info.get(ATTR_LAST_QUERY), (int, float))
        }

        for info in merged.values():
            ips = sorted(info.get(ATTR_IP_ADDRESSES, []))
            info[ATTR_IP_ADDRESSES] = ips
            info[ATTR_IPS] = ", ".join(ips)
            if ips and not info.get(ATTR_PRIMARY_IP):
                info[ATTR_PRIMARY_IP] = ips[0]

        return merged


def _is_unauthorized_response(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    error = data.get("error")
    if not isinstance(error, dict):
        return False
    return error.get("key") == "unauthorized" or error.get("message") == "Unauthorized"


def _legacy_network_to_devices(network: list[Any]) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for row in network:
        if not isinstance(row, dict):
            continue

        last_query = _as_timestamp(row.get("lastQuery"))
        ips = []
        names = _as_list(row.get("name"))
        for index, ip in enumerate(_as_list(row.get("ip"))):
            ip_entry: dict[str, Any] = {"ip": ip}
            if index < len(names):
                ip_entry["name"] = names[index]
            if last_query is not None:
                ip_entry["lastSeen"] = last_query
            ips.append(ip_entry)

        devices.append(
            {
                "hwaddr": row.get("hwaddr"),
                "interface": row.get("interface"),
                "firstSeen": row.get("firstSeen"),
                "lastQuery": row.get("lastQuery"),
                "numQueries": row.get("numQueries"),
                "macVendor": row.get("macVendor"),
                "ips": ips,
            }
        )
    return devices
