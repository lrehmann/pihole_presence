"""Diagnostics must remain useful without disclosing local network details."""

import json
from types import SimpleNamespace

import pytest

from custom_components.pihole_presence.const import DOMAIN
from custom_components.pihole_presence.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.mark.asyncio
async def test_diagnostics_omit_private_data_even_when_unloaded(hass):
    entry = SimpleNamespace(
        entry_id="existing",
        data={
            "host": "http://private.host",
            "password": "secret-password",
            "api_token": "secret-token",
            "scan_interval": 30,
        },
        options={"password": "secret-override"},
    )
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert not data["loaded"]
    assert data["settings"] == {"scan_interval": 30}
    hass.data[DOMAIN] = {
        entry.entry_id: {
            "coordinator": SimpleNamespace(
                _resolved_api_mode="v6",
                last_update_success=False,
                last_exception=Exception("secret-error-url"),
                _consecutive_failures=2,
                data={"aa:bb:cc:dd:ee:ff": {"ip": "192.168.1.20"}},
                query_activity_complete=False,
            )
        }
    }
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["coordinator"]["device_count"] == 1
    text = json.dumps(data)
    for value in ["secret", "private.host", "aa:bb:cc", "192.168"]:
        assert value not in text
