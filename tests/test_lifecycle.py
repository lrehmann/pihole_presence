"""Verify reloads, failed setup cleanup, and stable entity identities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.pihole_presence import (
    _async_update_options,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.pihole_presence.const import DOMAIN
from custom_components.pihole_presence.device_tracker import PiholeTracker
from custom_components.pihole_presence.sensor import (
    SENSOR_DESCRIPTIONS,
    PiholeHostSensor,
)


@pytest.mark.asyncio
async def test_setup_failure_releases_its_session(hass, monkeypatch):
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=UpdateFailed("Offline")
    )
    coordinator.async_close = AsyncMock()
    monkeypatch.setattr(
        "custom_components.pihole_presence.PiholeUpdateCoordinator",
        lambda *a, **kw: coordinator,
    )
    entry = SimpleNamespace(data={}, options={})
    with pytest.raises(UpdateFailed):
        await async_setup_entry(hass, entry)
    coordinator.async_close.assert_awaited_once()
    assert DOMAIN not in hass.data


@pytest.mark.asyncio
async def test_options_reload(hass):
    hass.config_entries.async_reload = AsyncMock()
    await _async_update_options(hass, SimpleNamespace(entry_id="existing"))
    hass.config_entries.async_reload.assert_awaited_once_with("existing")


@pytest.mark.asyncio
async def test_unload_closes_session_only_after_platforms_unload(hass):
    coordinator = SimpleNamespace(async_close=AsyncMock())
    hass.data[DOMAIN] = {"existing": {"coordinator": coordinator}}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    entry = SimpleNamespace(entry_id="existing")
    assert not await async_unload_entry(hass, entry)
    coordinator.async_close.assert_not_awaited()
    hass.config_entries.async_unload_platforms.return_value = True
    assert await async_unload_entry(hass, entry)
    coordinator.async_close.assert_awaited_once()
    assert "existing" not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_tracker_and_sensor_ids_survive_upgrade(coordinator):
    coordinator.data = {"aa:bb:cc:dd:ee:02": {}}
    tracker = PiholeTracker(coordinator, "aa:bb:cc:dd:ee:02", 900)
    assert tracker.unique_id == "pihole_presence_aabbccddee02_pihole"
    assert tracker.mac_address == "aa:bb:cc:dd:ee:02"
    assert tracker.state == "not_home"
    sensor = PiholeHostSensor(
        coordinator, "existing", "http://pi.hole", SENSOR_DESCRIPTIONS[0]
    )
    assert sensor.unique_id == "existing_host_temperature"
    assert not sensor.available
