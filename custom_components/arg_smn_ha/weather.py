"""Weather platform for SMN Argentina (OpenSMN)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.weather import Forecast, WeatherEntity, WeatherEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfLength, UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.sun import is_up
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTR_CONDITION_CLEAR_NIGHT, ATTR_CONDITION_SUNNY, CONDITION_ID_MAP, DOMAIN
from .coordinator import SmnDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def format_condition(condition: Any, sun_is_up: bool = True) -> str:
    """Map an SMN weather object (dict with ``id``) to an HA condition.

    Falls back to sunny/clear-night so the entity never reports ``unknown``
    just because SMN added a new icon id.
    """
    default = ATTR_CONDITION_SUNNY if sun_is_up else ATTR_CONDITION_CLEAR_NIGHT
    if not isinstance(condition, dict):
        return default
    weather_id = condition.get("id")
    mapped = CONDITION_ID_MAP.get(weather_id) if weather_id is not None else None
    if not mapped:
        if weather_id is not None:
            _LOGGER.debug("Unknown SMN weather id %r, using default", weather_id)
        return default
    if mapped == ATTR_CONDITION_SUNNY and not sun_is_up:
        return ATTR_CONDITION_CLEAR_NIGHT
    return mapped


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the SMN weather entity."""
    coordinator: SmnDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmnWeatherEntity(coordinator, entry)])


class SmnWeatherEntity(CoordinatorEntity[SmnDataUpdateCoordinator], WeatherEntity):
    """SMN weather entity with daily + hourly forecasts."""

    _attr_attribution = "Data provided by Servicio Meteorológico Nacional Argentina"
    _attr_has_entity_name = True
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_supported_features = WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    _attr_translation_key = "smn_weather"

    def __init__(self, coordinator: SmnDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = entry.data.get(CONF_NAME) or coordinator.data.location_name or "SMN"
        self._attr_unique_id = f"{entry.entry_id}_weather"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info shared with the alert sensors."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.data.get(CONF_NAME) or "SMN Argentina",
            manufacturer="Servicio Meteorológico Nacional",
            model=self.coordinator.location_id,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def condition(self) -> str | None:
        """Return the current condition."""
        current = self.coordinator.data.current
        if not current:
            return None
        condition = current.get("description") or current.get("weather")
        try:
            sun_up = is_up(self.hass)
        except Exception:  # noqa: BLE001 - sun integration may be unavailable
            sun_up = True
        return format_condition(condition, sun_up)

    @property
    def native_temperature(self) -> float | None:
        """Return the current temperature."""
        return _as_float(self.coordinator.data.current.get("temperature"))

    @property
    def native_apparent_temperature(self) -> float | None:
        """Return the feels-like temperature."""
        return _as_float(self.coordinator.data.current.get("feels_like"))

    @property
    def humidity(self) -> float | None:
        """Return humidity."""
        return _as_float(self.coordinator.data.current.get("humidity"))

    @property
    def native_pressure(self) -> float | None:
        """Return pressure."""
        return _as_float(self.coordinator.data.current.get("pressure"))

    @property
    def native_wind_speed(self) -> float | None:
        """Return wind speed."""
        return _as_float(self.coordinator.data.current.get("wind_speed"))

    @property
    def wind_bearing(self) -> float | str | None:
        """Return wind bearing."""
        return self.coordinator.data.current.get("wind_deg")

    @property
    def native_visibility(self) -> float | None:
        """Return visibility in meters (SMN reports meters)."""
        vis = _as_float(self.coordinator.data.current.get("visibility"))
        if vis is None:
            return None
        # HA expects km for visibility when unit is not set; SMN gives meters.
        # Keep meters and let HA convert: native_visibility_unit defaults to km,
        # so convert here.
        return vis / 1000.0

    async def async_get_forecasts(
        self, kind: str, hours: int | None = None, days: int | None = None
    ) -> list[Forecast] | None:
        """Return daily or hourly forecasts (modern HA forecast API)."""
        kind = (kind or "").lower()
        if kind == "daily":
            items = self.coordinator.data.daily_forecast
            if days is not None:
                items = items[: max(days, 0)]
            return self._build_daily(items)
        if kind == "hourly":
            items = self.coordinator.data.hourly_forecast
            if hours is not None:
                items = items[: max(hours, 0)]
            return self._build_hourly(items)
        return None

    def _build_daily(self, items: list[dict[str, Any]]) -> list[Forecast]:
        forecasts: list[Forecast] = []
        for item in items:
            dt = _parse_dt(item.get("date"))
            if dt is None:
                continue
            forecasts.append(
                Forecast(
                    datetime=dt,
                    native_temperature=_as_float(item.get("temp_max")),
                    native_templow=_as_float(item.get("temp_min")),
                    condition=format_condition(item.get("weather")),
                )
            )
        return forecasts

    def _build_hourly(self, items: list[dict[str, Any]]) -> list[Forecast]:
        forecasts: list[Forecast] = []
        for item in items:
            dt = _parse_dt(item.get("datetime"))
            if dt is None:
                continue
            forecasts.append(
                Forecast(
                    datetime=dt,
                    native_temperature=_as_float(item.get("temperature")),
                    condition=format_condition(item.get("weather")),
                    humidity=_as_float(item.get("humidity")),
                    native_wind_speed=_as_float(item.get("wind_speed")),
                    wind_bearing=item.get("wind_direction"),
                )
            )
        return forecasts

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose location metadata without duplicating alert sensors."""
        return {
            "location_id": self.coordinator.location_id,
            "location_name": self.coordinator.data.location_name,
            "observed_at": self.coordinator.data.current.get("observed_at"),
        }


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    parsed = dt_util.parse_datetime(text)
    if parsed is not None:
        return parsed.isoformat()
    date_only = dt_util.parse_date(text)
    if date_only is not None:
        return datetime.combine(date_only, datetime.min.time()).isoformat()
    return None
