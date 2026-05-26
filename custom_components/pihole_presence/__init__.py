from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AWAY_TIME,
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    CONF_STALE_DEVICE_DAYS,
    DEFAULT_AWAY_TIME,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_DEVICE_DAYS,
    DOMAIN,
)
from .coordinator import PiholeUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["device_tracker"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pi-hole Presence from a UI config entry."""
    data = {**entry.data, **entry.options}
    host = data.get(CONF_HOST, DEFAULT_HOST)
    scan_interval = data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    away_time = data.get(CONF_AWAY_TIME, DEFAULT_AWAY_TIME)
    stale_device_days = data.get(CONF_STALE_DEVICE_DAYS, DEFAULT_STALE_DEVICE_DAYS)

    coordinator = PiholeUpdateCoordinator(hass, host, scan_interval, stale_device_days)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "away_time": away_time,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
