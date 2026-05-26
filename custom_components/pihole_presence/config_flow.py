from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST

from .const import (
    CONF_AWAY_TIME,
    CONF_SCAN_INTERVAL,
    CONF_STALE_DEVICE_DAYS,
    DEFAULT_AWAY_TIME,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_DEVICE_DAYS,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=5)
        ),
        vol.Required(CONF_AWAY_TIME, default=DEFAULT_AWAY_TIME): vol.All(
            int, vol.Range(min=30)
        ),
        vol.Required(
            CONF_STALE_DEVICE_DAYS, default=DEFAULT_STALE_DEVICE_DAYS
        ): vol.All(int, vol.Range(min=1)),
    }
)


class PiholePresenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Pi-hole Presence config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(
                title="Pi-hole Presence",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Allow tuning polling and presence thresholds."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=data.get(CONF_HOST, DEFAULT_HOST)
                    ): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(int, vol.Range(min=5)),
                    vol.Required(
                        CONF_AWAY_TIME,
                        default=data.get(CONF_AWAY_TIME, DEFAULT_AWAY_TIME),
                    ): vol.All(int, vol.Range(min=30)),
                    vol.Required(
                        CONF_STALE_DEVICE_DAYS,
                        default=data.get(
                            CONF_STALE_DEVICE_DAYS, DEFAULT_STALE_DEVICE_DAYS
                        ),
                    ): vol.All(int, vol.Range(min=1)),
                }
            ),
        )
