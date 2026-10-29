"""Share useful failure details without exposing credentials or LAN devices."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_MODE,
    CONF_AWAY_TIME,
    CONF_SCAN_INTERVAL,
    CONF_STALE_DEVICE_DAYS,
    DOMAIN,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return an explicit allowlist; omit host, credentials, MACs, IPs, queries."""
    data = {**entry.data, **entry.options}
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
    diagnostics = {
        "settings": {
            key: data[key]
            for key in (
                CONF_API_MODE,
                CONF_AWAY_TIME,
                CONF_SCAN_INTERVAL,
                CONF_STALE_DEVICE_DAYS,
            )
            if key in data
        },
        "loaded": coordinator is not None,
    }
    if coordinator is not None:
        diagnostics["coordinator"] = {
            "api_mode": coordinator._resolved_api_mode,
            "last_update_success": coordinator.last_update_success,
            "last_error_type": type(coordinator.last_exception).__name__
            if coordinator.last_exception
            else None,
            "consecutive_failures": coordinator._consecutive_failures,
            "device_count": len(coordinator.data or {}),
            "query_activity_complete": coordinator.query_activity_complete,
        }
    return diagnostics
