"""Config flow for SMN Weather integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import ArgentinaSMNData, SMNAuthError, SMNTokenManager

_LOGGER = logging.getLogger(__name__)

# SMN only covers Argentina (including the southern islands).
ARGENTINA_LAT_MIN = -55.5
ARGENTINA_LAT_MAX = -21.0
ARGENTINA_LON_MIN = -74.0
ARGENTINA_LON_MAX = -53.0

# Token scraping plus the georef request should finish well within this.
VALIDATION_TIMEOUT = 45


def validate_coordinates(latitude: float, longitude: float) -> str | None:
    """Return a translation key when the coordinates are invalid."""
    if not -90 <= latitude <= 90:
        return "invalid_latitude"
    if not -180 <= longitude <= 180:
        return "invalid_longitude"
    if not (
        ARGENTINA_LAT_MIN <= latitude <= ARGENTINA_LAT_MAX
        and ARGENTINA_LON_MIN <= longitude <= ARGENTINA_LON_MAX
    ):
        return "outside_argentina"
    return None


async def async_validate_input(
    hass: HomeAssistant,
    latitude: float,
    longitude: float,
    username: str | None,
    password: str | None,
) -> str | None:
    """Validate credentials/connectivity and return the SMN location name."""
    session = async_get_clientsession(hass)
    data = ArgentinaSMNData(
        hass,
        latitude,
        longitude,
        SMNTokenManager(hass, session, username, password),
    )
    async with asyncio.timeout(VALIDATION_TIMEOUT):
        _location_id, location_name = await data.async_get_location()
    return location_name


class ArgentinaSMNConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SMN Weather."""

    VERSION = 1

    _reauth_entry: Any = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ArgentinaSMNOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose between the HA home location and custom coordinates."""
        return self.async_show_menu(
            menu_options=["home", "manual"],
            description_placeholders={
                "latitude": f"{self.hass.config.latitude:.4f}",
                "longitude": f"{self.hass.config.longitude:.4f}",
            },
        )

    async def async_step_home(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the integration for the Home Assistant home location."""
        return await self._async_configure(step_id="home", user_input=user_input)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the integration for custom coordinates."""
        return await self._async_configure(step_id="manual", user_input=user_input)

    async def _async_configure(
        self,
        *,
        step_id: str,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Validate the location and create the config entry."""
        errors: dict[str, str] = {}
        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude

        # The HA home location is not covered by SMN: send the user to the
        # manual step with the home coordinates pre-filled instead of showing
        # a form that can never be submitted.
        home_unsupported = step_id == "home" and bool(
            validate_coordinates(latitude, longitude)
        )

        if user_input is not None and not home_unsupported:
            if step_id == "manual":
                latitude = user_input[CONF_LATITUDE]
                longitude = user_input[CONF_LONGITUDE]
            name = (user_input.get(CONF_NAME) or "").strip()
            username = (user_input.get(CONF_USERNAME) or "").strip() or None
            password = user_input.get(CONF_PASSWORD) or None

            if error := validate_coordinates(latitude, longitude):
                errors["base"] = error
            elif bool(username) != bool(password):
                errors["base"] = "credentials_required"
            else:
                await self.async_set_unique_id(f"{latitude:.4f}_{longitude:.4f}")
                self._abort_if_unique_id_configured()

                try:
                    location_name = await async_validate_input(
                        self.hass, latitude, longitude, username, password
                    )
                except SMNAuthError:
                    errors["base"] = "invalid_auth"
                except (UpdateFailed, aiohttp.ClientError, TimeoutError):
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error validating SMN location")
                    errors["base"] = "unknown"
                else:
                    data: dict[str, Any] = {
                        CONF_LATITUDE: latitude,
                        CONF_LONGITUDE: longitude,
                        CONF_NAME: name or location_name or "SMN Weather",
                    }
                    if username and password:
                        data[CONF_USERNAME] = username
                        data[CONF_PASSWORD] = password
                    return self.async_create_entry(title=data[CONF_NAME], data=data)

        if home_unsupported:
            errors["base"] = "outside_argentina"
            step_id = "manual"

        schema_fields: dict[Any, Any] = {}
        if step_id == "manual":
            schema_fields[vol.Required(CONF_LATITUDE, default=latitude)] = cv.latitude
            schema_fields[vol.Required(CONF_LONGITUDE, default=longitude)] = (
                cv.longitude
            )
        schema_fields[vol.Optional(CONF_NAME)] = cv.string
        schema_fields[vol.Optional(CONF_USERNAME)] = cv.string
        schema_fields[vol.Optional(CONF_PASSWORD)] = cv.string

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(schema_fields),
            errors=errors,
            description_placeholders={
                "latitude": f"{latitude:.4f}",
                "longitude": f"{longitude:.4f}",
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a reauthentication request."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new SMN credentials."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if entry is None:
            return self.async_abort(reason="reauth_failed")

        if user_input is not None:
            username = (user_input.get(CONF_USERNAME) or "").strip()
            password = user_input.get(CONF_PASSWORD) or ""
            if not username or not password:
                errors["base"] = "credentials_required"
            else:
                try:
                    await async_validate_input(
                        self.hass,
                        entry.data[CONF_LATITUDE],
                        entry.data[CONF_LONGITUDE],
                        username,
                        password,
                    )
                except SMNAuthError:
                    errors["base"] = "invalid_auth"
                except (UpdateFailed, aiohttp.ClientError, TimeoutError):
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error during SMN reauthentication")
                    errors["base"] = "unknown"
                else:
                    new_data = dict(entry.data)
                    new_data[CONF_USERNAME] = username
                    new_data[CONF_PASSWORD] = password
                    # Updating the entry schedules the registered update
                    # listener, which reloads the entry exactly once.
                    self.hass.config_entries.async_update_entry(entry, data=new_data)
                    return self.async_abort(reason="reauth_successful")

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")
                ): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=data_schema,
            errors=errors,
        )


class ArgentinaSMNOptionsFlow(OptionsFlow):
    """Handle options for an existing SMN entry."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the polling interval."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_minutes = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL // 60
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_minutes): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=1440)
                    ),
                }
            ),
        )
