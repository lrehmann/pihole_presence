from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DHCP_EXPIRES,
    ATTR_FIRST_SEEN,
    ATTR_IP_ADDRESSES,
    ATTR_IPS,
    ATTR_LAST_QUERY,
    ATTR_LAST_SEEN,
    ATTR_MAC_VENDOR,
    ATTR_NAME,
    ATTR_NUM_QUERIES,
    ATTR_PRIMARY_IP,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    away_time = data["away_time"]
    known_macs: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new_macs = sorted(set(coordinator.data) - known_macs)
        if not new_macs:
            return
        known_macs.update(new_macs)
        async_add_entities(
            PiholeTracker(coordinator, mac, away_time) for mac in new_macs
        )

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


def _iso_timestamp(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return None


class PiholeTracker(CoordinatorEntity, TrackerEntity):
    """Presence via Pi-hole device tracker."""

    def __init__(self, coordinator, mac: str, away_time: int) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._away = away_time
        self._attr_unique_id = f"{DOMAIN}_{mac.replace(':','')}_pihole"
        self._attr_name = "Pi-hole Presence"

    @property
    def is_connected(self) -> bool:
        last = self.coordinator.data.get(self._mac, {}).get(ATTR_LAST_QUERY)
        if not isinstance(last, (int, float)):
            return False
        return (datetime.now(timezone.utc).timestamp() - last) <= self._away

    @property
    def state(self) -> str:
        """Return home or not_home instead of unknown."""
        return STATE_HOME if self.is_connected else STATE_NOT_HOME

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data.get(self._mac, {})
        last = data.get(ATTR_LAST_QUERY)
        now = datetime.now(timezone.utc).timestamp()
        return {
            "last_query": _iso_timestamp(last),
            "last_query_seconds_ago": int(now - last)
            if isinstance(last, (int, float))
            else None,
            "first_seen": _iso_timestamp(data.get(ATTR_FIRST_SEEN)),
            "last_seen": _iso_timestamp(data.get(ATTR_LAST_SEEN)),
            "query_count": data.get(ATTR_NUM_QUERIES),
            "ip_addresses": data.get(ATTR_IP_ADDRESSES, []),
            "ip_addresses_text": data.get(ATTR_IPS),
            "dhcp_expires": _iso_timestamp(data.get(ATTR_DHCP_EXPIRES)),
            "mac_vendor": data.get(ATTR_MAC_VENDOR),
            "device_name": data.get(ATTR_NAME),
            "away_timeout": self._away,
        }

    @property
    def source_type(self) -> SourceType:
        return SourceType.ROUTER

    @property
    def ip_address(self) -> str | None:
        return self.coordinator.data.get(self._mac, {}).get(ATTR_PRIMARY_IP)

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def device_info(self) -> DeviceInfo:
        info = self.coordinator.data.get(self._mac, {})
        name = info.get(ATTR_NAME)
        if not name or name == "*" or not name.strip():
            name = self._mac
        return DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, self._mac)},
            name=name,
            manufacturer=info.get(ATTR_MAC_VENDOR),
            model=None,
        )
