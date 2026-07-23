from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries

from .const import (
    API_MODE_OPTIONS,
    CONF_AWAY_TIME,
    CONF_API_MODE,
    CONF_API_TOKEN,
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


def _data_schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(
                CONF_API_MODE, default=defaults.get(CONF_API_MODE, DEFAULT_API_MODE)
            ): vol.In(API_MODE_OPTIONS),
            vol.Optional(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            vol.Optional(CONF_API_TOKEN, default=defaults.get(CONF_API_TOKEN, "")): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(int, vol.Range(min=5)),
            vol.Required(
                CONF_AWAY_TIME, default=defaults.get(CONF_AWAY_TIME, DEFAULT_AWAY_TIME)
            ): vol.All(int, vol.Range(min=30)),
            vol.Required(
                CONF_STALE_DEVICE_DAYS,
                default=defaults.get(CONF_STALE_DEVICE_DAYS, DEFAULT_STALE_DEVICE_DAYS),
            ): vol.All(int, vol.Range(min=1)),
        }
    )


STEP_USER_DATA_SCHEMA = _data_schema()


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
            data_schema=_data_schema(data),
        )
