"""Diagnostics support for the SMN integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import ArgentinaSMNDataUpdateCoordinator

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for an SMN config entry."""
    coordinator: ArgentinaSMNDataUpdateCoordinator | None = getattr(
        entry, "runtime_data", None
    )
    if coordinator is None or coordinator.data is None:
        return {
            "entry": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "data": None,
        }

    data = coordinator.data

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "location": {
            "name": data.location_name,
            "station_name": data.station_name,
            "station_distance_km": data.station_distance_km,
        },
        "current_weather": data.current_weather_data,
        "daily_forecast": data.daily_forecast,
        "hourly_forecast": data.hourly_forecast,
        "alerts": data.alerts,
        "alerts_available": data.alerts_available,
        "shortterm_alerts": data.shortterm_alerts,
        "shortterm_alerts_available": data.shortterm_alerts_available,
        "heat_warnings": data.heat_warnings,
        "token_expiration": (
            coordinator.token_expiration.isoformat()
            if coordinator.token_expiration
            else None
        ),
    }
