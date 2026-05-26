from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
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
    DEVICES_ENDPOINT,
    LEASES_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)
_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def _clean_mac(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    mac = value.lower().strip()
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


class PiholeUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and normalize Pi-hole network device data."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        scan_interval: int,
        stale_device_days: int,
    ):
        self._host = host.rstrip("/")
        self._stale_after = timedelta(days=stale_device_days)
        self._session = async_get_clientsession(hass)
        super().__init__(
            hass,
            _LOGGER,
            name="Pi-hole Presence",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _fetch_json(self, endpoint: str) -> dict[str, Any]:
        url = f"{self._host}{endpoint}"
        async with self._session.get(url, timeout=10) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise UpdateFailed(f"{url} returned HTTP {resp.status}: {text[:120]}")
            return await resp.json(content_type=None)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            leases_json, devices_json = await asyncio.gather(
                self._fetch_json(LEASES_ENDPOINT),
                self._fetch_json(DEVICES_ENDPOINT),
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(err) from err

        leases = leases_json.get("leases", [])
        devices = devices_json.get("devices", [])
        if not isinstance(leases, list) or not isinstance(devices, list):
            raise UpdateFailed("Unexpected Pi-hole API response")

        now = datetime.now(timezone.utc).timestamp()
        stale_cutoff = now - self._stale_after.total_seconds()
        merged: dict[str, dict[str, Any]] = {}

        for lease in leases:
            mac = _clean_mac(lease.get("hwaddr"))
            if not mac:
                continue
            entry = merged.setdefault(mac, {ATTR_IP_ADDRESSES: set()})
            if lease.get("ip"):
                entry[ATTR_IP_ADDRESSES].add(str(lease["ip"]))
            if name := _clean_name(lease.get("name")):
                entry[ATTR_NAME] = name
            if expires := _as_timestamp(lease.get("expires")):
                entry[ATTR_DHCP_EXPIRES] = expires

        for dev in devices:
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
                if ip := ip_entry.get("ip"):
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
