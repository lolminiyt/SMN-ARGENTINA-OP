"""DataUpdateCoordinator for SMN Argentina (OpenSMN)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SmnApiError, SmnAuthError, async_fetch_all, create_client
from .const import (
    CONF_CONNECTION_TYPE,
    CONF_OPENSMN_PASSWORD,
    CONF_OPENSMN_URL,
    CONF_SCAN_INTERVAL,
    CONF_SMN_TOKEN,
    DEFAULT_CONNECTION_TYPE,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class SmnData:
    """Normalized data exposed to platforms."""

    location_id: str = ""
    location_name: str | None = None
    current: dict[str, Any] = field(default_factory=dict)
    daily_forecast: list[dict[str, Any]] = field(default_factory=list)
    hourly_forecast: list[dict[str, Any]] = field(default_factory=list)
    alerts: dict[str, Any] = field(default_factory=dict)
    shortterm_alerts: list[dict[str, Any]] = field(default_factory=list)
    heat_warnings: dict[str, Any] = field(default_factory=dict)


def _mean(values: list[Any]) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return sum(nums) / len(nums)


def parse_current_weather(raw: Any) -> dict[str, Any]:
    """Normalize the /weather/location response."""
    if not isinstance(raw, dict):
        return {}
    wind = raw.get("wind") if isinstance(raw.get("wind"), dict) else {}
    location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    return {
        "temperature": raw.get("temperature", raw.get("temp")),
        "feels_like": raw.get("feels_like", raw.get("st")),
        "humidity": raw.get("humidity"),
        "pressure": raw.get("pressure"),
        "visibility": raw.get("visibility"),
        "wind_speed": (wind or {}).get("speed"),
        "wind_deg": (wind or {}).get("deg"),
        "weather": raw.get("weather"),
        "description": raw.get("description"),
        "name": (location or {}).get("name"),
        "observed_at": raw.get("date", raw.get("updated", raw.get("time"))),
    }


def parse_forecast(raw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize the /forecast/location response into daily + hourly lists."""
    daily: list[dict[str, Any]] = []
    hourly: list[dict[str, Any]] = []
    days: Any = raw.get("forecast", []) if isinstance(raw, dict) else raw
    if not isinstance(days, list):
        return daily, hourly
    periods = (
        ("early_morning", "00:00"),
        ("morning", "06:00"),
        ("afternoon", "12:00"),
        ("night", "18:00"),
    )
    for day in days:
        if not isinstance(day, dict):
            continue
        date = day.get("date")
        if not date:
            continue
        daily.append(
            {
                "date": date,
                "temp_max": day.get("temp_max"),
                "temp_min": day.get("temp_min"),
                "weather": (day.get("afternoon") or {}).get("weather")
                if isinstance(day.get("afternoon"), dict)
                else None,
            }
        )
        for period_name, period_time in periods:
            period = day.get(period_name)
            if not isinstance(period, dict):
                continue
            wind = period.get("wind") if isinstance(period.get("wind"), dict) else {}
            speed_range = (wind or {}).get("speed_range") or []
            wind_speed = _mean(speed_range) if speed_range else (wind or {}).get("speed")
            hourly.append(
                {
                    "date": date,
                    "time": period_time,
                    "datetime": f"{date}T{period_time}:00",
                    "temperature": period.get("temperature"),
                    "weather": period.get("weather"),
                    "humidity": period.get("humidity"),
                    "wind_speed": wind_speed,
                    "wind_direction": (wind or {}).get("deg"),
                }
            )
    return daily, hourly


class SmnDataUpdateCoordinator(DataUpdateCoordinator[SmnData]):
    """Fetch SMN data through the configured backend."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        data = entry.data
        options = entry.options
        interval = int(
            options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        session = async_get_clientsession(hass)
        # Options may override stored proxy credentials (rotation without re-add).
        self._client = create_client(
            data.get(CONF_CONNECTION_TYPE, DEFAULT_CONNECTION_TYPE),
            session,
            options.get(CONF_OPENSMN_URL, data.get(CONF_OPENSMN_URL, "")),
            options.get(CONF_OPENSMN_PASSWORD, data.get(CONF_OPENSMN_PASSWORD, "")),
            options.get(CONF_SMN_TOKEN, data.get(CONF_SMN_TOKEN, "")),
        )
        location_id = str(data.get("location_id", ""))
        self.data = SmnData(location_id=location_id)

    @property
    def entry(self) -> ConfigEntry:
        """Return the config entry (used by services)."""
        return self._entry

    @property
    def location_id(self) -> str:
        """Return the SMN location id for this entry."""
        loc = self._entry.data.get("location_id", "")
        return str(loc)

    async def _async_update_data(self) -> SmnData:
        """Fetch all data; map auth problems to reauth flow."""
        try:
            raw = await async_fetch_all(self._client, self.location_id)
        except SmnAuthError as err:
            raise ConfigEntryAuthFailed(f"SMN auth failed: {err}") from err
        except SmnApiError as err:
            raise UpdateFailed(f"SMN request failed: {err}") from err

        daily, hourly = parse_forecast(raw.get("forecast"))
        current = parse_current_weather(raw.get("weather"))
        alerts = raw.get("alerts") or {}
        shortterm = raw.get("shortterm") or []
        heat = raw.get("heat") or {}
        name = current.get("name") or self.data.location_name
        self.data = SmnData(
            location_id=self.location_id,
            location_name=name,
            current=current,
            daily_forecast=daily,
            hourly_forecast=hourly,
            alerts=alerts if isinstance(alerts, dict) else {},
            shortterm_alerts=shortterm if isinstance(shortterm, list) else [],
            heat_warnings=heat if isinstance(heat, dict) else {},
        )
        return self.data

    async def async_set_scan_interval(self, seconds: int) -> None:
        """Update the polling interval (used by the options flow)."""
        self.update_interval = timedelta(seconds=int(seconds))
        await self.async_request_refresh()
