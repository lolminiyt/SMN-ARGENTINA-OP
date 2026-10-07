"""Diagnostics for SMN Argentina (OpenSMN)."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_OPENSMN_PASSWORD, DOMAIN
from .coordinator import SmnDataUpdateCoordinator


def _redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: ("[REDACTED]" if "password" in k.lower() or "token" in k.lower() else _redact(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact(v) for v in data]
    if isinstance(data, str) and len(data) > 64:
        return data[:8] + "…[TRUNCATED]"
    return data


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics without secrets."""
    coordinator: SmnDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    config = dict(entry.data)
    if CONF_OPENSMN_PASSWORD in config and config[CONF_OPENSMN_PASSWORD]:
        config[CONF_OPENSMN_PASSWORD] = "[REDACTED]"
    data = coordinator.data
    return {
        "entry": {"data": _redact(config), "options": dict(entry.options), "version": entry.version},
        "coordinator": {
            "location_id": data.location_id,
            "location_name": data.location_name,
            "current": data.current,
            "daily_count": len(data.daily_forecast),
            "hourly_count": len(data.hourly_forecast),
            "daily_sample": data.daily_forecast[:1],
            "hourly_sample": data.hourly_forecast[:2],
            "alerts": data.alerts,
            "shortterm_count": len(data.shortterm_alerts),
            "heat": data.heat_warnings,
            "last_update_success": coordinator.last_update_success,
        },
    }
