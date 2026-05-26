from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Do not create per-device diagnostic sensors.

    Older releases created seven sensors per MAC address. The tracker entity now
    carries those details as attributes to keep Home Assistant's registry small.
    This module remains so upgrades from older installs do not fail if HA still
    unloads the previous sensor platform during the transition.
    """
    return None
