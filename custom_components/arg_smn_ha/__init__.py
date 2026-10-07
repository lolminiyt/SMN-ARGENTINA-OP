"""The SMN Argentina (OpenSMN) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SmnApiError, create_client
from .const import (
    ALERT_EVENT_MAP,
    ALERT_LEVEL_MAP,
    CONF_CONNECTION_TYPE,
    CONF_OPENSMN_PASSWORD,
    CONF_OPENSMN_URL,
    DEFAULT_CONNECTION_TYPE,
    DOMAIN,
    SERVICE_GET_ALERTS,
    SERVICE_GET_ALERTS_FOR_LOCATION,
)
from .coordinator import SmnDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.WEATHER, Platform.BINARY_SENSOR]

SERVICE_GET_ALERTS_SCHEMA = vol.Schema({vol.Optional("config_entry_id"): cv.string})
SERVICE_GET_ALERTS_FOR_LOCATION_SCHEMA = vol.Schema({vol.Required("location_id"): cv.string})


def parse_alerts_payload(alerts_data: Any) -> dict[str, Any]:
    """Normalize the raw alert payload for services and diagnostics."""
    empty: dict[str, Any] = {"active_alerts": [], "max_severity": "info", "max_level": 1, "area_id": None, "updated": None}
    if not isinstance(alerts_data, dict):
        return empty
    warnings = alerts_data.get("warnings") or []
    reports = alerts_data.get("reports") or []
    area_id = alerts_data.get("area_id")
    active: list[dict[str, Any]] = []
    max_level = 1
    if warnings:
        current = warnings[0] if isinstance(warnings[0], dict) else {}
        for event in current.get("events") or []:
            if not isinstance(event, dict):
                continue
            level = int(event.get("max_level", 1) or 1)
            if level <= 1:
                continue
            max_level = max(max_level, level)
            event_id = event.get("id")
            description = instruction = None
            for report in reports:
                if isinstance(report, dict) and report.get("event_id") == event_id:
                    for lvl in report.get("levels") or []:
                        if isinstance(lvl, dict) and lvl.get("level") == level:
                            description = lvl.get("description")
                            instruction = lvl.get("instruction")
                            break
            info = ALERT_LEVEL_MAP.get(level, ALERT_LEVEL_MAP[1])
            active.append(
                {
                    "event_id": event_id,
                    "event_name": ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                    "max_level": level,
                    "level_name": info["name"],
                    "color": info["color"],
                    "severity": info["severity"],
                    "date": current.get("date"),
                    "description": description,
                    "instruction": instruction,
                }
            )
    top = ALERT_LEVEL_MAP.get(max_level, ALERT_LEVEL_MAP[1])
    return {
        "active_alerts": active,
        "max_severity": top["severity"],
        "max_level": max_level,
        "area_id": area_id,
        "updated": alerts_data.get("updated"),
    }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SMN Argentina from a config entry."""
    coordinator = SmnDataUpdateCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except Exception as err:  # noqa: BLE001 - first refresh maps to retry
        raise ConfigEntryNotReady(f"SMN initial fetch failed: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    if not hass.services.has_service(DOMAIN, SERVICE_GET_ALERTS):

        async def handle_get_alerts(call: ServiceCall) -> dict[str, Any]:
            entry_id = call.data.get("config_entry_id") or next(iter(hass.data.get(DOMAIN, {})), None)
            coordinator_: SmnDataUpdateCoordinator | None = hass.data.get(DOMAIN, {}).get(entry_id) if entry_id else None
            if coordinator_ is None:
                _LOGGER.warning("get_alerts called with unknown entry %s", entry_id)
                return parse_alerts_payload(None)
            result = parse_alerts_payload(coordinator_.data.alerts)
            _LOGGER.info("get_alerts: %d active alerts", len(result["active_alerts"]))
            return result

        hass.services.async_register(
            DOMAIN, SERVICE_GET_ALERTS, handle_get_alerts,
            schema=SERVICE_GET_ALERTS_SCHEMA, supports_response="only",
        )

    if not hass.services.has_service(DOMAIN, SERVICE_GET_ALERTS_FOR_LOCATION):

        async def handle_get_alerts_for_location(call: ServiceCall) -> dict[str, Any]:
            location_id = str(call.data["location_id"])
            entries: dict[str, SmnDataUpdateCoordinator] = hass.data.get(DOMAIN, {})
            if not entries:
                return {**parse_alerts_payload(None), "error": "integration not configured"}
            first = next(iter(entries.values()))
            entry_data = first.entry.data  # reuse backend of first entry
            entry_options = first.entry.options
            session = async_get_clientsession(hass)
            try:
                client = create_client(
                    entry_data.get(CONF_CONNECTION_TYPE, DEFAULT_CONNECTION_TYPE),
                    session,
                    entry_options.get(CONF_OPENSMN_URL, entry_data.get(CONF_OPENSMN_URL, "")),
                    entry_options.get(CONF_OPENSMN_PASSWORD, entry_data.get(CONF_OPENSMN_PASSWORD, "")),
                )
                from .const import PATH_ALERT

                raw = await client.get(f"{PATH_ALERT}/{location_id}")
            except SmnApiError as err:
                _LOGGER.error("get_alerts_for_location(%s) failed: %s", location_id, err)
                return {**parse_alerts_payload(None), "error": str(err)}
            return parse_alerts_payload(raw)

        hass.services.async_register(
            DOMAIN, SERVICE_GET_ALERTS_FOR_LOCATION, handle_get_alerts_for_location,
            schema=SERVICE_GET_ALERTS_FOR_LOCATION_SCHEMA, supports_response="only",
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change so credentials/interval take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entries forward (currently a no-op for v1)."""
    if entry.version > 1:
        return False
    return True
