"""Config flow for SMN Argentina (OpenSMN)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SmnApiError,
    SmnAuthError,
    SmnNotFoundError,
    async_resolve_location,
    create_client,
)
from .const import (
    CONF_CONNECTION_TYPE,
    CONF_OPENSMN_PASSWORD,
    CONF_OPENSMN_URL,
    CONF_SCAN_INTERVAL,
    CONNECTION_TYPE_DIRECT,
    CONNECTION_TYPE_OPENSMN,
    DEFAULT_CONNECTION_TYPE,
    DEFAULT_OPENSMN_URL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

COORD_TOLERANCE_DEG: float = 0.0001
DEFAULT_HOME_LATITUDE: float = -34.6037
DEFAULT_HOME_LONGITUDE: float = -58.3816


class SmnConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for SMN Argentina."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._pending: dict[str, Any] = {}

    def _duplicate_title(self, latitude: float, longitude: float) -> str | None:
        for entry in self._async_current_entries():
            lat = entry.data.get(CONF_LATITUDE)
            lon = entry.data.get(CONF_LONGITUDE)
            if lat is None or lon is None:
                continue
            try:
                if abs(float(lat) - latitude) < COORD_TOLERANCE_DEG and abs(float(lon) - longitude) < COORD_TOLERANCE_DEG:
                    return entry.title
            except (TypeError, ValueError):
                continue
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: mode + coordinates. Direct validates here, proxy goes to step 2."""
        errors: dict[str, str] = {}
        hass_lat = self.hass.config.latitude or DEFAULT_HOME_LATITUDE
        hass_lon = self.hass.config.longitude or DEFAULT_HOME_LONGITUDE
        if user_input is not None:
            connection_type = user_input.get(CONF_CONNECTION_TYPE, DEFAULT_CONNECTION_TYPE)
            try:
                latitude = float(user_input[CONF_LATITUDE])
                longitude = float(user_input[CONF_LONGITUDE])
            except (TypeError, ValueError):
                errors["base"] = "invalid_coordinates"
            else:
                name = (user_input.get(CONF_NAME) or "").strip()
                if not name:
                    errors[CONF_NAME] = "invalid_name"
                elif self._duplicate_title(latitude, longitude):
                    errors["base"] = "already_configured"
                elif connection_type == CONNECTION_TYPE_OPENSMN:
                    # Defer network validation until we have the proxy URL.
                    self._pending = {
                        CONF_CONNECTION_TYPE: connection_type,
                        CONF_LATITUDE: latitude,
                        CONF_LONGITUDE: longitude,
                        CONF_NAME: name,
                    }
                    return await self.async_step_proxy()
                else:
                    result = await self._create_direct_entry(latitude, longitude, name)
                    if isinstance(result, str):
                        errors["base"] = result
                    else:
                        return result
            user_input = {**user_input}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONNECTION_TYPE, default=user_input.get(CONF_CONNECTION_TYPE, DEFAULT_CONNECTION_TYPE) if user_input else DEFAULT_CONNECTION_TYPE): vol.In(
                        {CONNECTION_TYPE_DIRECT: "SMN directo (sin servidor)", CONNECTION_TYPE_OPENSMN: "Proxy OpenSMN (avanzado)"}
                    ),
                    vol.Required(CONF_LATITUDE, default=(user_input.get(CONF_LATITUDE, hass_lat) if user_input else hass_lat)): cv.latitude,
                    vol.Required(CONF_LONGITUDE, default=(user_input.get(CONF_LONGITUDE, hass_lon) if user_input else hass_lon)): cv.longitude,
                    vol.Required(CONF_NAME, default=(user_input.get(CONF_NAME, "") if user_input else "")): cv.string,
                }
            ),
            errors=errors,
        )

    async def async_step_proxy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 2 (proxy only): OpenSMN URL + optional password, then validate."""
        errors: dict[str, str] = {}
        if not self._pending:
            return await self.async_step_user()
        if user_input is not None:
            opensmn_url = (user_input.get(CONF_OPENSMN_URL) or "").strip()
            opensmn_password = (user_input.get(CONF_OPENSMN_PASSWORD) or "").strip()
            if not opensmn_url:
                errors[CONF_OPENSMN_URL] = "required_in_proxy_mode"
            else:
                latitude = self._pending[CONF_LATITUDE]
                longitude = self._pending[CONF_LONGITUDE]
                name = self._pending[CONF_NAME]
                session = async_get_clientsession(self.hass)
                try:
                    client = create_client(CONNECTION_TYPE_OPENSMN, session, opensmn_url, opensmn_password)
                    resolved = await async_resolve_location(client, latitude, longitude)
                except SmnAuthError:
                    errors["base"] = "invalid_auth"
                except SmnNotFoundError:
                    errors["base"] = "location_not_found"
                except SmnApiError as err:
                    _LOGGER.warning("OpenSMN validation failed: %s", err)
                    errors["base"] = "cannot_connect_proxy"
                else:
                    await self.async_set_unique_id(f"{CONNECTION_TYPE_OPENSMN}_{resolved.location_id}")
                    self._abort_if_unique_id_configured()
                    title = name or resolved.name or f"SMN {resolved.location_id}"
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_CONNECTION_TYPE: CONNECTION_TYPE_OPENSMN,
                            CONF_OPENSMN_URL: opensmn_url,
                            CONF_OPENSMN_PASSWORD: opensmn_password,
                            CONF_LATITUDE: latitude,
                            CONF_LONGITUDE: longitude,
                            CONF_NAME: name or resolved.name or title,
                            "location_id": resolved.location_id,
                            "location_name": resolved.name,
                        },
                    )
        return self.async_show_form(
            step_id="proxy",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OPENSMN_URL, default=(user_input.get(CONF_OPENSMN_URL, DEFAULT_OPENSMN_URL) if user_input else DEFAULT_OPENSMN_URL)): cv.string,
                    vol.Optional(CONF_OPENSMN_PASSWORD, default=""): cv.string,
                }
            ),
            errors=errors,
        )

    async def _create_direct_entry(self, latitude: float, longitude: float, name: str) -> ConfigFlowResult | str:
        """Validate direct SMN and build the entry. Returns error key on failure."""
        session = async_get_clientsession(self.hass)
        try:
            client = create_client(CONNECTION_TYPE_DIRECT, session)
            resolved = await async_resolve_location(client, latitude, longitude)
        except SmnAuthError:
            return "invalid_auth"
        except SmnNotFoundError:
            return "location_not_found"
        except SmnApiError as err:
            _LOGGER.warning("Direct SMN validation failed: %s", err)
            return "cannot_connect_direct"
        await self.async_set_unique_id(f"{CONNECTION_TYPE_DIRECT}_{resolved.location_id}")
        self._abort_if_unique_id_configured()
        title = name or resolved.name or f"SMN {resolved.location_id}"
        return self.async_create_entry(
            title=title,
            data={
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_DIRECT,
                CONF_OPENSMN_URL: "",
                CONF_OPENSMN_PASSWORD: "",
                CONF_LATITUDE: latitude,
                CONF_LONGITUDE: longitude,
                CONF_NAME: name or resolved.name or title,
                "location_id": resolved.location_id,
                "location_name": resolved.name,
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Trigger reauth when the stored password/token stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm new credentials for an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            password = (user_input.get(CONF_OPENSMN_PASSWORD) or "").strip()
            url = (user_input.get(CONF_OPENSMN_URL) or entry.data.get(CONF_OPENSMN_URL, "")).strip()
            session = async_get_clientsession(self.hass)
            try:
                client = create_client(entry.data.get(CONF_CONNECTION_TYPE, DEFAULT_CONNECTION_TYPE), session, url, password)
                await async_resolve_location(
                    client, float(entry.data[CONF_LATITUDE]), float(entry.data[CONF_LONGITUDE])
                )
            except SmnAuthError:
                errors["base"] = "invalid_auth"
            except SmnApiError as err:
                _LOGGER.warning("Reauth validation failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_OPENSMN_URL: url, CONF_OPENSMN_PASSWORD: password},
                )
        is_proxy = entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_OPENSMN
        if is_proxy:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_OPENSMN_URL, default=entry.data.get(CONF_OPENSMN_URL, DEFAULT_OPENSMN_URL)
                    ): cv.string,
                    vol.Optional(CONF_OPENSMN_PASSWORD, default=""): cv.string,
                }
            )
        else:
            # Direct mode has no stored secret; reauth just retries the token fetch.
            schema = vol.Schema({})
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return SmnOptionsFlowHandler()


class SmnOptionsFlowHandler(OptionsFlow):
    """Options flow: polling interval and proxy credentials."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}
        data = self.config_entry.data
        current_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
        if user_input is not None:
            try:
                interval = int(user_input[CONF_SCAN_INTERVAL])
            except (TypeError, ValueError):
                errors[CONF_SCAN_INTERVAL] = "invalid_interval"
                interval = 0
            else:
                if not MIN_SCAN_INTERVAL_SECONDS <= interval <= MAX_SCAN_INTERVAL_SECONDS:
                    errors[CONF_SCAN_INTERVAL] = "invalid_interval"
                else:
                    options: dict[str, Any] = {CONF_SCAN_INTERVAL: interval}
                    # Allow credential rotation without re-adding the entry.
                    if data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_OPENSMN:
                        options[CONF_OPENSMN_URL] = (user_input.get(CONF_OPENSMN_URL) or "").strip()
                        options[CONF_OPENSMN_PASSWORD] = (user_input.get(CONF_OPENSMN_PASSWORD) or "").strip()
                    return self.async_create_entry(title="", data=options)
        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL_SECONDS, max=MAX_SCAN_INTERVAL_SECONDS)
            ),
        }
        if data.get(CONF_CONNECTION_TYPE) == CONNECTION_TYPE_OPENSMN:
            schema_dict[vol.Optional(CONF_OPENSMN_URL, default=data.get(CONF_OPENSMN_URL, DEFAULT_OPENSMN_URL))] = cv.string
            schema_dict[vol.Optional(CONF_OPENSMN_PASSWORD, default="")] = cv.string
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict), errors=errors)
