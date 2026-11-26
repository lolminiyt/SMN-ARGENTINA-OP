"""The SMN Weather integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import UpdateFailed

from .alerts import parse_alerts
from .const import DOMAIN
from .coordinator import ArgentinaSMNDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.WEATHER, Platform.BINARY_SENSOR]

SERVICE_GET_ALERTS = "get_alerts"
SERVICE_GET_ALERTS_FOR_LOCATION = "get_alerts_for_location"

SERVICE_GET_ALERTS_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
    }
)

SERVICE_GET_ALERTS_FOR_LOCATION_SCHEMA = vol.Schema(
    {
        vol.Required("location_id"): vol.Coerce(str),
    }
)


def _get_coordinator(
    hass: HomeAssistant, config_entry_id: str | None = None
) -> ArgentinaSMNDataUpdateCoordinator | None:
    """Return a loaded coordinator."""
    if config_entry_id:
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or entry.domain != DOMAIN:
            return None
        return getattr(entry, "runtime_data", None)

    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            return coordinator
    return None


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SMN from a config entry."""
    coordinator = ArgentinaSMNDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    if not hass.services.has_service(DOMAIN, SERVICE_GET_ALERTS):

        async def handle_get_alerts(call: ServiceCall) -> dict[str, Any]:
            """Handle get_alerts service call."""
            config_entry_id = call.data.get("config_entry_id")
            coordinator = _get_coordinator(hass, config_entry_id)
            if coordinator is None or coordinator.data is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="no_entry",
                )
            if not coordinator.data.alerts_available:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="alerts_unavailable",
                )

            result = parse_alerts(coordinator.data.alerts)
            _LOGGER.debug(
                "Alerts service called: %d active alerts, max severity '%s'",
                len(result["active_alerts"]),
                result["max_severity"],
            )
            return result

        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_ALERTS,
            handle_get_alerts,
            schema=SERVICE_GET_ALERTS_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_GET_ALERTS_FOR_LOCATION):

        async def handle_get_alerts_for_location(call: ServiceCall) -> dict[str, Any]:
            """Handle get_alerts_for_location service call."""
            location_id = call.data["location_id"]
            coordinator = _get_coordinator(hass)
            if coordinator is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="no_entry",
                )

            try:
                data = await coordinator.async_get_alerts_for_location(location_id)
            except UpdateFailed as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="alerts_fetch_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            return parse_alerts(data)

        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_ALERTS_FOR_LOCATION,
            handle_get_alerts_for_location,
            schema=SERVICE_GET_ALERTS_FOR_LOCATION_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator: ArgentinaSMNDataUpdateCoordinator | None = getattr(
        entry, "runtime_data", None
    )
    if coordinator is not None:
        await coordinator.async_shutdown()
    entry.runtime_data = None

    remaining_entries = [
        other
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
        and getattr(other, "runtime_data", None) is not None
    ]
    if not remaining_entries:
        for service in (SERVICE_GET_ALERTS, SERVICE_GET_ALERTS_FOR_LOCATION):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return True
