"""Run against real HA classes, without starting an HA server or using a LAN."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant


@pytest.fixture
async def hass(tmp_path):
    # HA added a required config_dir constructor argument in 2024. Modern
    # coordinators also capture the running loop when they are constructed.
    if "config_dir" in inspect.signature(HomeAssistant).parameters:
        instance = HomeAssistant(str(tmp_path))
    else:
        instance = HomeAssistant()
        instance.config.config_dir = str(tmp_path)
    instance.config_entries = MagicMock()
    return instance


@pytest.fixture
async def coordinator(hass, monkeypatch):
    from custom_components.pihole_presence import coordinator as module

    monkeypatch.setattr(module, "async_get_clientsession", lambda _hass: MagicMock())
    return module.PiholeUpdateCoordinator(hass, "http://pi.hole", 30, 30)
