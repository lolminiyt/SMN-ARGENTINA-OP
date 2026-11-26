"""Weather platform for SMN."""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_SUNNY,
    Forecast,
    SingleCoordinatorWeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.sun import is_up
from homeassistant.util import dt as dt_util

from .const import (
    CONDITION_ID_MAP,
    CONDITIONS_MAP,
    DOMAIN,
    SMN_TIMEZONE,
)
from .coordinator import ArgentinaSMNDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _smn_tz():
    """Return the SMN timezone."""
    return dt_util.get_time_zone(SMN_TIMEZONE) or dt_util.DEFAULT_TIME_ZONE


def parse_smn_datetime(value: str | None) -> str | None:
    """Parse an SMN date/datetime into a timezone-aware ISO string."""
    if not value:
        return None

    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        day = dt_util.parse_date(value)
        if day is None:
            return None
        parsed = datetime.combine(day, time.min)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_smn_tz())

    return parsed.isoformat()


def format_condition(condition: dict | str | None, sun_is_up: bool = True) -> str:
    """Map SMN weather condition ID or description to a Home Assistant condition."""
    if not condition:
        return ATTR_CONDITION_SUNNY if sun_is_up else ATTR_CONDITION_CLEAR_NIGHT

    if isinstance(condition, dict):
        weather_id = condition.get("id")
        if weather_id is not None:
            ha_condition = CONDITION_ID_MAP.get(weather_id)
            if ha_condition:
                if ha_condition == ATTR_CONDITION_SUNNY and not sun_is_up:
                    return ATTR_CONDITION_CLEAR_NIGHT
                return ha_condition
        description = (condition.get("description") or "").lower()
        for ha_condition, terms in CONDITIONS_MAP.items():
            if any(term in description for term in terms):
                return ha_condition
        return ATTR_CONDITION_SUNNY if sun_is_up else ATTR_CONDITION_CLEAR_NIGHT

    # String fallback
    description = condition.lower()
    for ha_condition, terms in CONDITIONS_MAP.items():
        if any(term in description for term in terms):
            return ha_condition
    return ATTR_CONDITION_SUNNY if sun_is_up else ATTR_CONDITION_CLEAR_NIGHT


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SMN weather entity."""
    coordinator: ArgentinaSMNDataUpdateCoordinator = config_entry.runtime_data
    async_add_entities([ArgentinaSMNWeather(coordinator, config_entry)], False)


class ArgentinaSMNWeather(
    SingleCoordinatorWeatherEntity[ArgentinaSMNDataUpdateCoordinator]
):
    """Implementation of an SMN weather entity."""

    _attr_attribution = "Data provided by Servicio Meteorológico Nacional Argentina"
    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(
        self,
        coordinator: ArgentinaSMNDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the weather entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_weather"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._config_entry.entry_id)},
            name=self._config_entry.data.get(CONF_NAME, "SMN Weather"),
            manufacturer="Servicio Meteorológico Nacional",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def condition(self) -> str | None:
        """Return the current condition."""
        if not self.coordinator.data.current_weather_data:
            return None
        condition = self.coordinator.data.current_weather_data.get(
            "weather"
        ) or self.coordinator.data.current_weather_data.get("description")
        return format_condition(condition, is_up(self.hass))

    @property
    def native_temperature(self) -> float | None:
        """Return the temperature."""
        return self.coordinator.data.current_weather_data.get("temperature")

    @property
    def native_apparent_temperature(self) -> float | None:
        """Return the apparent temperature (feels like)."""
        return self.coordinator.data.current_weather_data.get("feels_like")

    @property
    def humidity(self) -> float | None:
        """Return the humidity."""
        return self.coordinator.data.current_weather_data.get("humidity")

    @property
    def native_pressure(self) -> float | None:
        """Return the pressure."""
        return self.coordinator.data.current_weather_data.get("pressure")

    @property
    def native_wind_speed(self) -> float | None:
        """Return the wind speed."""
        return self.coordinator.data.current_weather_data.get("wind_speed")

    @property
    def wind_bearing(self) -> float | str | None:
        """Return the wind bearing."""
        return self.coordinator.data.current_weather_data.get("wind_deg")

    @property
    def native_visibility(self) -> float | None:
        """Return the visibility."""
        return self.coordinator.data.current_weather_data.get("visibility")

    def _format_forecast(
        self, forecast_data: list[dict[str, Any]], is_daily: bool = False
    ) -> list[Forecast]:
        """Format forecast data for Home Assistant."""
        if not forecast_data:
            return []

        forecasts: list[Forecast] = []

        for item in forecast_data:
            forecast_datetime = parse_smn_datetime(
                item.get("date") if is_daily else item.get("datetime")
            )
            if forecast_datetime is None:
                continue

            if is_daily:
                forecast = Forecast(
                    datetime=forecast_datetime,
                    native_temperature=item.get("temp_max"),
                    native_templow=item.get("temp_min"),
                    condition=format_condition(item.get("weather")),
                    native_precipitation=item.get("precipitation"),
                    precipitation_probability=item.get("precipitation_probability"),
                )
            else:
                forecast = Forecast(
                    datetime=forecast_datetime,
                    native_temperature=item.get("temperature"),
                    native_apparent_temperature=item.get("feels_like"),
                    condition=format_condition(item.get("weather")),
                    humidity=item.get("humidity"),
                    native_wind_speed=item.get("wind_speed"),
                    native_wind_gust_speed=item.get("wind_gust"),
                    wind_bearing=item.get("wind_direction"),
                    native_precipitation=item.get("precipitation"),
                    precipitation_probability=item.get("precipitation_probability"),
                )

            forecasts.append(forecast)

        return forecasts

    @callback
    def _async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast."""
        return self._format_forecast(
            self.coordinator.data.daily_forecast, is_daily=True
        )

    @callback
    def _async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the 6-hourly forecast (SMN publishes four periods per day)."""
        return self._format_forecast(
            self.coordinator.data.hourly_forecast, is_daily=False
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        data = self.coordinator.data
        attrs: dict[str, Any] = {}
        if data.location_name:
            attrs["location_name"] = data.location_name
        if data.station_name:
            attrs["station_name"] = data.station_name
        if data.station_distance_km is not None:
            attrs["station_distance_km"] = data.station_distance_km
        if data.current_weather_data.get("date"):
            attrs["observation_time"] = data.current_weather_data["date"]
        if data.current_weather_data.get("station_id") is not None:
            attrs["station_id"] = data.current_weather_data["station_id"]
        return attrs
