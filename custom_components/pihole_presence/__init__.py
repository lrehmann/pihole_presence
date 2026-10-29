from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_MODE,
    CONF_API_TOKEN,
    CONF_AWAY_TIME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_STALE_DEVICE_DAYS,
    DEFAULT_API_MODE,
    DEFAULT_AWAY_TIME,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_DEVICE_DAYS,
    DOMAIN,
)
from .coordinator import PiholeUpdateCoordinator
from .util import normalize_host

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["device_tracker", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pi-hole Presence from a UI config entry."""
    data = {**entry.data, **entry.options}
    host = normalize_host(data.get(CONF_HOST, DEFAULT_HOST))
    scan_interval = data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    away_time = data.get(CONF_AWAY_TIME, DEFAULT_AWAY_TIME)
    stale_device_days = data.get(CONF_STALE_DEVICE_DAYS, DEFAULT_STALE_DEVICE_DAYS)
    password = data.get(CONF_PASSWORD, "")
    api_token = data.get(CONF_API_TOKEN, "")
    api_mode = data.get(CONF_API_MODE, DEFAULT_API_MODE)

    coordinator = PiholeUpdateCoordinator(
        hass,
        host,
        scan_interval,
        stale_device_days,
        presence_window=away_time,
        password=password,
        api_token=api_token,
        api_mode=api_mode,
        config_entry=entry,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_close()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "away_time": away_time,
        "host": host,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    async def _async_stop(_event):
        await coordinator.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply saved options immediately, including credentials and poll interval."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["coordinator"].async_close()
    return unload_ok
