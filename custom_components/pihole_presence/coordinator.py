from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
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
    LEGACY_NETWORK_ENDPOINT,
    LEASES_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)
_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


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
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


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


class PiholeUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and normalize Pi-hole network device data."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        scan_interval: int,
        stale_device_days: int,
        password: str | None = None,
        api_token: str | None = None,
        api_mode: str = API_MODE_AUTO,
    ):
        self._host = host.rstrip("/")
        self._stale_after = timedelta(days=stale_device_days)
        self._password = (password or "").strip()
        self._api_token = (api_token or "").strip()
        self._api_mode = api_mode if api_mode in API_MODE_OPTIONS else API_MODE_AUTO
        self._sid: str | None = None
        self._sid_valid_until: float | None = None
        self._session = async_get_clientsession(hass)
        super().__init__(
            hass,
            _LOGGER,
            name="Pi-hole Presence",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _fetch_json(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._host}{endpoint}"
        async with self._session.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_payload,
            timeout=10,
        ) as resp:
            text = await resp.text()
            if resp.status in (401, 403):
                raise PiholeAuthError(
                    f"Pi-hole API rejected authentication for {endpoint}"
                )
            if resp.status == 404:
                raise PiholeNotFoundError(f"Pi-hole API endpoint not found: {endpoint}")
            if resp.status >= 400:
                raise PiholeApiError(
                    f"Pi-hole API endpoint {endpoint} returned HTTP {resp.status}: "
                    f"{text[:120]}"
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
            return data

    async def _ensure_v6_session(self, *, force: bool = False) -> None:
        if not self._password:
            return

        now = datetime.now(timezone.utc).timestamp()
        if (
            not force
            and self._sid
            and (
                self._sid_valid_until is None
                or self._sid_valid_until > now + 30
            )
        ):
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
        validity = session.get("validity")
        if isinstance(validity, (int, float)) and validity > 0:
            self._sid_valid_until = now + float(validity)
        else:
            self._sid_valid_until = None

    async def _fetch_v6_json(
        self, endpoint: str, *, retry_auth: bool = True
    ) -> dict[str, Any]:
        await self._ensure_v6_session()
        headers = {"X-FTL-SID": self._sid} if self._sid else None

        try:
            return await self._fetch_json(endpoint, headers=headers)
        except PiholeAuthError:
            if self._password and retry_auth:
                self._sid = None
                self._sid_valid_until = None
                await self._ensure_v6_session(force=True)
                return await self._fetch_v6_json(endpoint, retry_auth=False)
            if not self._password:
                raise PiholeAuthError(
                    "Pi-hole v6 requires authentication; configure the Pi-hole "
                    "password in this integration's options"
                )
            raise

    async def _fetch_v6_data(self) -> tuple[list[Any], list[Any]]:
        devices_json = await self._fetch_v6_json(DEVICES_ENDPOINT)
        try:
            leases_json = await self._fetch_v6_json(LEASES_ENDPOINT)
        except PiholeNotFoundError:
            leases_json = {"leases": []}

        if not isinstance(leases_json, dict) or not isinstance(devices_json, dict):
            raise PiholeApiError("Unexpected Pi-hole v6 API response")
        leases = leases_json.get("leases", [])
        devices = devices_json.get("devices", [])
        if not isinstance(leases, list) or not isinstance(devices, list):
            raise PiholeApiError("Unexpected Pi-hole v6 API response")
        return leases, devices

    async def _fetch_legacy_data(self) -> tuple[list[Any], list[Any]]:
        params = {"network": ""}
        if self._api_token:
            params["auth"] = self._api_token

        network_json = await self._fetch_json(LEGACY_NETWORK_ENDPOINT, params=params)
        network = (
            network_json.get("network") if isinstance(network_json, dict) else None
        )
        if not isinstance(network, list):
            raise PiholeAuthError(
                "Pi-hole legacy API did not return network data; configure the API "
                "token if the Pi-hole web UI has a password"
            )

        return [], _legacy_network_to_devices(network)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self._api_mode in (API_MODE_AUTO, API_MODE_V6):
                try:
                    leases, devices = await self._fetch_v6_data()
                    return self._normalize_data(leases, devices)
                except PiholeNotFoundError:
                    if self._api_mode == API_MODE_V6:
                        raise
                    _LOGGER.debug("Pi-hole v6 API not found; trying legacy PHP API")

            if self._api_mode in (API_MODE_AUTO, API_MODE_LEGACY):
                leases, devices = await self._fetch_legacy_data()
                return self._normalize_data(leases, devices)

            raise PiholeApiError(f"Unsupported Pi-hole API mode: {self._api_mode}")
        except (aiohttp.ClientError, asyncio.TimeoutError, PiholeApiError) as err:
            raise UpdateFailed(err) from err

    def _normalize_data(
        self, leases: list[Any], devices: list[Any]
    ) -> dict[str, dict[str, Any]]:
        now = datetime.now(timezone.utc).timestamp()
        stale_cutoff = now - self._stale_after.total_seconds()
        merged: dict[str, dict[str, Any]] = {}

        for lease in leases:
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
            if dev.get("interface") == "lo":
                continue
            mac = _clean_mac(dev.get("hwaddr"))
            if not mac:
                continue
            last_query = _as_timestamp(dev.get("lastQuery"))
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

            for ip_entry in dev.get("ips", []):
                if ip := _clean_ip(ip_entry.get("ip")):
                    entry[ATTR_IP_ADDRESSES].add(str(ip))
                    entry.setdefault(ATTR_PRIMARY_IP, str(ip))
                if last_seen := _as_timestamp(ip_entry.get("lastSeen")):
                    entry[ATTR_LAST_SEEN] = max(
                        last_seen, entry.get(ATTR_LAST_SEEN, 0)
                    )
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
    return (
        error.get("key") == "unauthorized"
        or error.get("message") == "Unauthorized"
    )


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
