"""Binary sensor platform for SMN weather alerts."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alerts import active_alerts, alert_level_info, event_level
from .const import ALERT_EVENT_ICONS, ALERT_EVENT_MAP, DOMAIN
from .coordinator import ArgentinaSMNDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Event types for Home Assistant events
EVENT_ALERT_CREATED = f"{DOMAIN}_alert_created"
EVENT_ALERT_UPDATED = f"{DOMAIN}_alert_updated"
EVENT_ALERT_CLEARED = f"{DOMAIN}_alert_cleared"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SMN binary sensors."""
    coordinator: ArgentinaSMNDataUpdateCoordinator = config_entry.runtime_data

    entities: list[BinarySensorEntity] = [SMNAlertSensor(coordinator, config_entry)]

    for event_id, event_name in ALERT_EVENT_MAP.items():
        entities.append(
            SMNEventAlertSensor(coordinator, config_entry, event_id, event_name)
        )

    entities.append(SMNShortTermAlertSensor(coordinator, config_entry))

    async_add_entities(entities)


def _device_info(config_entry: ConfigEntry) -> DeviceInfo:
    """Return shared device information."""
    return DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=config_entry.data.get(CONF_NAME, "SMN Weather"),
        manufacturer="Servicio Meteorológico Nacional",
        entry_type=DeviceEntryType.SERVICE,
    )


class SMNAlertSensor(
    CoordinatorEntity[ArgentinaSMNDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor for SMN weather alerts (all types)."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_translation_key = "weather_alert"
    _attr_icon = "mdi:alert"

    def __init__(
        self,
        coordinator: ArgentinaSMNDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_alert"
        # Seed with current alerts so a restart does not emit "created" events
        # for alerts that were already active.
        data = getattr(coordinator, "data", None)
        self._previous_alerts: set[tuple[str | None, int, int]] = (
            {
                (alert["date"], alert["event_id"], alert["level"])
                for alert in active_alerts(data.alerts if data else None)
            }
            if data
            else set()
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _device_info(self._config_entry)

    @property
    def available(self) -> bool:
        """Return False when the alert endpoint could not be read."""
        data = self.coordinator.data
        return super().available and bool(data and data.alerts_available)

    @property
    def is_on(self) -> bool:
        """Return True if there are active alerts."""
        return bool(active_alerts(self.coordinator.data.alerts))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        alerts = active_alerts(self.coordinator.data.alerts)
        if not alerts:
            return {
                "active_alert_count": 0,
                "max_severity": "info",
                "max_level": 1,
            }

        max_level = max(alert["level"] for alert in alerts)
        max_severity_info = alert_level_info(max_level)
        alert_summary = ", ".join(
            f"{alert['event_name']} ({alert['level_name']})" for alert in alerts
        )

        return {
            "active_alert_count": len(alerts),
            "max_severity": max_severity_info["severity"],
            "max_level": max_level,
            "alert_summary": alert_summary,
            "alerts": alerts,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._fire_alert_events()
        super()._handle_coordinator_update()

    def _fire_alert_events(self) -> None:
        """Fire Home Assistant events for alert changes."""
        alerts = active_alerts(self.coordinator.data.alerts)
        current = {
            (alert["date"], alert["event_id"], alert["level"]) for alert in alerts
        }

        new_alerts = current - self._previous_alerts
        for day, event_id, level in new_alerts:
            level_info = alert_level_info(level)
            self.hass.bus.fire(
                EVENT_ALERT_CREATED,
                {
                    "date": day,
                    "event_id": event_id,
                    "event_name": ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                    "level": level,
                    "level_name": level_info["name"],
                    "severity": level_info["severity"],
                },
            )
            _LOGGER.info(
                "Alert created: %s on %s (level %d - %s)",
                ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                day,
                level,
                level_info["name"],
            )

        previous_levels = {
            (day, event_id): level for day, event_id, level in self._previous_alerts
        }
        current_levels = {(day, event_id): level for day, event_id, level in current}
        for (day, event_id), level in current_levels.items():
            old_level = previous_levels.get((day, event_id))
            if old_level is None or old_level == level:
                continue
            level_info = alert_level_info(level)
            self.hass.bus.fire(
                EVENT_ALERT_UPDATED,
                {
                    "date": day,
                    "event_id": event_id,
                    "event_name": ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                    "old_level": old_level,
                    "new_level": level,
                    "level_name": level_info["name"],
                    "severity": level_info["severity"],
                },
            )
            _LOGGER.info(
                "Alert updated: %s on %s (level %d -> %d)",
                ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                day,
                old_level,
                level,
            )

        for day, event_id, level in self._previous_alerts - current:
            # A changed level is reported as "updated", not as cleared+created.
            if (day, event_id) in current_levels:
                continue
            self.hass.bus.fire(
                EVENT_ALERT_CLEARED,
                {
                    "date": day,
                    "event_id": event_id,
                    "event_name": ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                    "level": level,
                },
            )
            _LOGGER.info(
                "Alert cleared: %s on %s (level %d)",
                ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                day,
                level,
            )

        self._previous_alerts = current


class SMNEventAlertSensor(
    CoordinatorEntity[ArgentinaSMNDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor for a specific SMN weather alert type."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    # There are eleven event sensors; keep the entity registry uncluttered and
    # let users enable only the alert types they care about.
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: ArgentinaSMNDataUpdateCoordinator,
        config_entry: ConfigEntry,
        event_id: int,
        event_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._event_id = event_id
        self._event_name = event_name
        self._attr_unique_id = f"{config_entry.entry_id}_alert_{event_name}"
        self._attr_translation_key = f"alert_{event_name}"
        self._attr_icon = ALERT_EVENT_ICONS.get(event_name, "mdi:alert")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _device_info(self._config_entry)

    @property
    def available(self) -> bool:
        """Return False when the alert endpoint could not be read."""
        data = self.coordinator.data
        return super().available and bool(data and data.alerts_available)

    @property
    def _matching_alerts(self) -> list[dict[str, Any]]:
        """Return active alerts for this event type."""
        return [
            alert
            for alert in active_alerts(self.coordinator.data.alerts)
            if alert["event_id"] == self._event_id
        ]

    @property
    def is_on(self) -> bool:
        """Return True if the specific event type is active."""
        return bool(self._matching_alerts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        alerts = self._matching_alerts
        if not alerts:
            return {}

        max_level = max(alert["level"] for alert in alerts)
        level_info = alert_level_info(max_level)
        description = next(
            (alert["description"] for alert in alerts if alert["description"]), None
        )
        instruction = next(
            (alert["instruction"] for alert in alerts if alert["instruction"]), None
        )

        return {
            "event_id": self._event_id,
            "event_name": self._event_name,
            "level": max_level,
            "level_name": level_info["name"],
            "severity": level_info["severity"],
            "description": description,
            "instruction": instruction,
            "dates": [alert["date"] for alert in alerts if alert["date"]],
        }


class SMNShortTermAlertSensor(
    CoordinatorEntity[ArgentinaSMNDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor for short-term alerts."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_translation_key = "short_term_alert"
    _attr_icon = "mdi:alert-circle"

    def __init__(
        self,
        coordinator: ArgentinaSMNDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_short_term_alert"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return _device_info(self._config_entry)

    @property
    def available(self) -> bool:
        """Return False when the short-term alert endpoint could not be read."""
        data = self.coordinator.data
        return super().available and bool(data and data.shortterm_alerts_available)

    @property
    def is_on(self) -> bool:
        """Return True if there are short-term alerts."""
        return bool(self.coordinator.data.shortterm_alerts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        alerts = self.coordinator.data.shortterm_alerts
        if not alerts:
            return {}

        max_level = max(
            (event_level(alert) for alert in alerts if isinstance(alert, dict)),
            default=1,
        )

        level_info = alert_level_info(max_level)

        return {
            "shortterm_alert_count": len(alerts),
            "max_level": max_level,
            "max_severity": level_info["severity"],
        }
