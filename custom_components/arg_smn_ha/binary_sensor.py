"""Binary sensors for SMN weather alerts."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ALERT_EVENT_ICONS,
    ALERT_EVENT_MAP,
    ALERT_LEVEL_MAP,
    DOMAIN,
    EVENT_ALERT_CLEARED,
    EVENT_ALERT_CREATED,
    EVENT_ALERT_UPDATED,
)
from .coordinator import SmnDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up alert sensors: aggregate + per-event + short-term."""
    coordinator: SmnDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [SmnAlertSensor(coordinator, entry)]
    for event_id, slug in ALERT_EVENT_MAP.items():
        entities.append(SmnEventAlertSensor(coordinator, entry, event_id, slug))
    entities.append(SmnShortTermAlertSensor(coordinator, entry))
    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data.get(CONF_NAME) or "SMN Argentina",
        manufacturer="Servicio Meteorológico Nacional",
        entry_type=DeviceEntryType.SERVICE,
    )


def _active_events(alerts: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Return (warning, event, report-level) triples for active (level > 1) events."""
    warnings = alerts.get("warnings") or []
    reports = alerts.get("reports") or []
    if not warnings or not isinstance(warnings[0], dict):
        return []
    warning = warnings[0]
    triples = []
    for event in warning.get("events") or []:
        if not isinstance(event, dict):
            continue
        if int(event.get("max_level", 1) or 1) <= 1:
            continue
        level_data: dict[str, Any] = {}
        for report in reports:
            if isinstance(report, dict) and report.get("event_id") == event.get("id"):
                for lvl in report.get("levels") or []:
                    if isinstance(lvl, dict) and lvl.get("level") == event.get("max_level"):
                        level_data = lvl
                        break
        triples.append((warning, event, level_data))
    return triples


class SmnAlertSensor(CoordinatorEntity[SmnDataUpdateCoordinator], BinarySensorEntity):
    """Aggregate sensor: on when any SMN alert is active."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_translation_key = "weather_alert"

    def __init__(self, coordinator: SmnDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_alert"
        self._previous: dict[Any, int] = {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return _device_info(self._entry)

    @property
    def is_on(self) -> bool:
        """Return True when at least one alert is active."""
        return bool(_active_events(self.coordinator.data.alerts))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return alert summary attributes for automations."""
        triples = _active_events(self.coordinator.data.alerts)
        if not triples:
            return {"active_alert_count": 0, "max_severity": "info", "max_level": 1}
        max_level = max(int(event.get("max_level", 1)) for _, event, _ in triples)
        items = []
        for _, event, level_data in triples:
            event_id = event.get("id")
            info = ALERT_LEVEL_MAP.get(int(event.get("max_level", 1)), ALERT_LEVEL_MAP[1])
            items.append(
                {
                    "event_name": ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                    "level_name": info["name"],
                    "severity": info["severity"],
                    "description": level_data.get("description"),
                }
            )
        top = ALERT_LEVEL_MAP.get(max_level, ALERT_LEVEL_MAP[1])
        return {
            "active_alert_count": len(items),
            "max_severity": top["severity"],
            "max_level": max_level,
            "alert_summary": ", ".join(f"{a['event_name']} ({a['level_name']})" for a in items),
            "active_alerts": items,
            "area_id": self.coordinator.data.alerts.get("area_id"),
            "updated": self.coordinator.data.alerts.get("updated"),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire events on alert transitions, then update state."""
        self._fire_transition_events()
        super()._handle_coordinator_update()

    def _fire_transition_events(self) -> None:
        triples = _active_events(self.coordinator.data.alerts)
        current = {event.get("id"): int(event.get("max_level", 1)) for _, event, _ in triples}
        for event_id, level in current.items():
            info = ALERT_LEVEL_MAP.get(level, ALERT_LEVEL_MAP[1])
            base = {
                "event_id": event_id,
                "event_name": ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                "level": level,
                "level_name": info["name"],
                "severity": info["severity"],
            }
            if event_id not in self._previous:
                self.hass.bus.fire(EVENT_ALERT_CREATED, base)
            elif self._previous[event_id] != level:
                self.hass.bus.fire(
                    EVENT_ALERT_UPDATED,
                    {**base, "old_level": self._previous[event_id], "new_level": level},
                )
        for event_id, level in self._previous.items():
            if event_id not in current:
                self.hass.bus.fire(
                    EVENT_ALERT_CLEARED,
                    {"event_id": event_id, "event_name": ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"), "level": level},
                )
        self._previous = current


class SmnEventAlertSensor(CoordinatorEntity[SmnDataUpdateCoordinator], BinarySensorEntity):
    """Per-event sensor (tormenta, lluvia, ...)."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True

    def __init__(self, coordinator: SmnDataUpdateCoordinator, entry: ConfigEntry, event_id: int, slug: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._event_id = event_id
        self._slug = slug
        self._attr_unique_id = f"{entry.entry_id}_alert_{slug}"
        self._attr_translation_key = f"alert_{slug}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return _device_info(self._entry)

    @property
    def icon(self) -> str:
        """Return event-specific icon."""
        return ALERT_EVENT_ICONS.get(self._slug, "mdi:alert")

    def _match(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        for warning, event, level_data in _active_events(self.coordinator.data.alerts):
            if event.get("id") == self._event_id:
                return warning, event, level_data
        return None

    @property
    def is_on(self) -> bool:
        """Return True when this specific event is active."""
        return self._match() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return level details for the event."""
        matched = self._match()
        if matched is None:
            return {"level": 1, "severity": "info"}
        warning, event, level_data = matched
        level = int(event.get("max_level", 1))
        info = ALERT_LEVEL_MAP.get(level, ALERT_LEVEL_MAP[1])
        return {
            "event_id": self._event_id,
            "event_name": self._slug,
            "level": level,
            "level_name": info["name"],
            "color": info["color"],
            "severity": info["severity"],
            "date": warning.get("date"),
            "description": level_data.get("description"),
            "instruction": level_data.get("instruction"),
        }


class SmnShortTermAlertSensor(CoordinatorEntity[SmnDataUpdateCoordinator], BinarySensorEntity):
    """Short-term severe weather alerts (nowcasting)."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_translation_key = "short_term_alert"

    def __init__(self, coordinator: SmnDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_shortterm_alert"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return _device_info(self._entry)

    @property
    def is_on(self) -> bool:
        """Return True when short-term alerts exist."""
        return bool(self.coordinator.data.shortterm_alerts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return short-term alert list."""
        alerts = self.coordinator.data.shortterm_alerts or []
        if not alerts:
            return {"alert_count": 0}
        return {
            "alert_count": len(alerts),
            "alerts": [
                {
                    "title": a.get("title"),
                    "date": a.get("date"),
                    "end_date": a.get("end_date"),
                    "severity": a.get("severity"),
                    "zones": a.get("zones"),
                    "instructions": a.get("instructions"),
                    "region": a.get("region"),
                }
                for a in alerts
                if isinstance(a, dict)
            ],
        }
