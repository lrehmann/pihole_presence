from __future__ import annotations

import asyncio

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    API_MODE_OPTIONS,
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
from .coordinator import PiholeApiError, PiholeAuthError, PiholeUpdateCoordinator
from .util import normalize_host


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


async def _validate_input(hass, user_input: dict) -> dict[str, str]:
    """Validate connectivity without saving invalid credentials or settings."""
    try:
        user_input[CONF_HOST] = normalize_host(user_input[CONF_HOST])
    except (ValueError, TypeError):
        return {CONF_HOST: "invalid_host"}
    coordinator = PiholeUpdateCoordinator(
        hass,
        user_input[CONF_HOST],
        user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        user_input.get(CONF_STALE_DEVICE_DAYS, DEFAULT_STALE_DEVICE_DAYS),
        password=user_input.get(CONF_PASSWORD),
        api_token=user_input.get(CONF_API_TOKEN),
        api_mode=user_input.get(CONF_API_MODE, DEFAULT_API_MODE),
    )
    try:
        await coordinator.async_validate_connection()
    except PiholeAuthError:
        return {"base": "invalid_auth"}
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return {"base": "cannot_connect"}
    except PiholeApiError:
        return {"base": "invalid_response"}
    finally:
        await coordinator.async_close()
    return {}


class PiholePresenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Pi-hole Presence config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            errors = await _validate_input(self.hass, user_input)
            if not errors:
                # Match the effective host for both old and new entries. A host
                # can change in options, so it is not a stable unique ID.
                for entry in self._async_current_entries():
                    existing = {**entry.data, **entry.options}
                    try:
                        same_host = (
                            normalize_host(existing.get(CONF_HOST, DEFAULT_HOST))
                            == user_input[CONF_HOST]
                        )
                    except (TypeError, ValueError):
                        continue
                    if same_host:
                        return self.async_abort(reason="already_configured")
                return self.async_create_entry(
                    title="Pi-hole Presence",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema(user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)

    async def async_step_reauth(self, entry_data):
        """Repair expired or changed credentials without recreating trackers."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._reauth_entry
        data = {**entry.data, **entry.options}
        if user_input is not None:
            data.update(user_input)
            errors = await _validate_input(self.hass, data)
            if not errors:
                # Preserve overrides from existing installations.
                self.hass.config_entries.async_update_entry(
                    entry, data=data, options={}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_data_schema(data),
            errors=errors,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Allow tuning polling and presence thresholds."""

    def __init__(self, config_entry):
        # config_entry is read-only on recent HA. Keep a private reference so
        # this also works before HA began providing OptionsFlow.config_entry.
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        data = {**self._entry.data, **self._entry.options}
        errors = {}
        if user_input is not None:
            data.update(user_input)
            errors = await _validate_input(self.hass, data)
            if not errors:
                return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="init",
            data_schema=_data_schema(data),
            errors=errors,
        )
