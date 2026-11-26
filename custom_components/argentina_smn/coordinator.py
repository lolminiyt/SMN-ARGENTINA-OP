"""DataUpdateCoordinator for the SMN integration."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any

import aiohttp

try:  # curl_cffi is used to obtain the anonymous web token from Cloudflare.
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - handled at runtime with a clear error
    curl_requests = None

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    API_ALERT_ENDPOINT,
    API_COORD_ENDPOINT,
    API_FORECAST_ENDPOINT,
    API_HEAT_WARNING_ENDPOINT,
    API_SHORTTERM_ALERT_ENDPOINT,
    API_TOKEN_ENDPOINT,
    API_WEATHER_ENDPOINT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SMN_TIMEZONE,
    TOKEN_PAGE,
    TOKEN_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

_TOKEN_PATTERNS = (
    r"localStorage\.setItem\(['\"]token['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    r'["\']token["\']\s*:\s*["\']([^"\']+)["\']',
    r'(?:var|let|const)\s+token\s*=\s*["\']([^"\']+)["\']',
    r"(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)",
)

_PERIODS = (
    ("early_morning", "00:00"),
    ("morning", "06:00"),
    ("afternoon", "12:00"),
    ("night", "18:00"),
)


def _smn_tz():
    """Return the SMN timezone."""
    return dt_util.get_time_zone(SMN_TIMEZONE) or dt_util.DEFAULT_TIME_ZONE


def _iso_datetime(day: str | None, clock: str) -> str | None:
    """Combine an SMN date and local clock time into an ISO datetime."""
    if not day:
        return None
    try:
        day_obj = date.fromisoformat(day)
        hour, minute = (int(part) for part in clock.split(":"))
    except (TypeError, ValueError):
        return None
    return datetime.combine(day_obj, time(hour, minute), tzinfo=_smn_tz()).isoformat()


def _average_range(value: Any) -> float | None:
    """Average an SMN [min, max] range, or return a scalar unchanged."""
    if isinstance(value, (list, tuple)):
        numbers = [item for item in value if isinstance(item, (int, float))]
        return sum(numbers) / len(numbers) if numbers else None
    if isinstance(value, (int, float)):
        return value
    return None


def _max_range(value: Any) -> float | None:
    """Return the upper bound of an SMN [min, max] range."""
    if isinstance(value, (list, tuple)):
        numbers = [item for item in value if isinstance(item, (int, float))]
        return max(numbers) if numbers else None
    if isinstance(value, (int, float)):
        return value
    return None


class SMNAuthError(UpdateFailed):
    """Raised when SMN rejects the configured credentials."""


class SMNTokenManager:
    """Manage JWT token for SMN API authentication."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize the token manager."""
        self._hass = hass
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_expiration: datetime | None = None
        self._token_lock = asyncio.Lock()

    def _decode_jwt_payload(self, token: str) -> dict[str, Any]:
        """Decode JWT payload without verification."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("Invalid JWT format")
            payload = parts[1]
            payload += "=" * (-len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception as err:  # noqa: BLE001 - malformed tokens must not crash
            _LOGGER.error("Error decoding JWT: %s", err)
            return {}

    async def _fetch_token_with_credentials(self) -> str:
        """Log in with SMN API credentials."""
        payload = {"username": self._username, "password": self._password}
        async with self._session.post(
            API_TOKEN_ENDPOINT,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
        ) as response:
            if response.status in (400, 401, 403):
                text = await response.text()
                raise SMNAuthError(
                    f"SMN rejected the configured credentials: {text[:200]}"
                )
            response.raise_for_status()
            data = await response.json(content_type=None)

        token = (
            data.get("token") or data.get("access_token") or data.get("jwt")
            if isinstance(data, dict)
            else None
        )
        if not token:
            raise UpdateFailed("SMN login response did not contain a token")
        return token

    async def _fetch_token_from_web(self) -> str:
        """Scrape the anonymous web token published by the SMN website."""
        if curl_requests is None:
            raise UpdateFailed(
                "curl_cffi is required to obtain the SMN web token. "
                "Install the integration requirements and restart Home Assistant."
            )

        def _scrape() -> str:
            last_error: str | None = None
            for impersonate in ("chrome131", "chrome", "chrome124", "chrome120"):
                try:
                    response = curl_requests.get(
                        TOKEN_PAGE,
                        impersonate=impersonate,
                        timeout=TOKEN_TIMEOUT,
                        headers={
                            "Accept": (
                                "text/html,application/xhtml+xml,"
                                "application/xml;q=0.9,image/avif,image/webp,"
                                "*/*;q=0.8"
                            ),
                            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
                            "Upgrade-Insecure-Requests": "1",
                        },
                    )
                except Exception as err:  # noqa: BLE001 - try the next profile
                    last_error = str(err)
                    continue

                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}"
                    continue

                for pattern in _TOKEN_PATTERNS:
                    match = re.search(pattern, response.text)
                    if match:
                        return match.group(1)

                last_error = "token not found in page"
                break

            raise UpdateFailed(
                f"Could not obtain the SMN web token ({last_error or 'unknown error'})"
            )

        return await self._hass.async_add_executor_job(_scrape)

    async def _fetch_token(self) -> str:
        """Fetch a JWT token from the SMN API or public website."""
        try:
            if self._username and self._password:
                _LOGGER.debug("Requesting token from %s", API_TOKEN_ENDPOINT)
                token = await self._fetch_token_with_credentials()
            else:
                _LOGGER.debug("Scraping anonymous token from %s", TOKEN_PAGE)
                token = await self._fetch_token_from_web()

            if not token.startswith("eyJ"):
                _LOGGER.warning("Token doesn't look like a JWT (length %d)", len(token))

            payload = self._decode_jwt_payload(token)
            if "exp" in payload:
                self._token_expiration = datetime.fromtimestamp(
                    payload["exp"], tz=dt_util.UTC
                )
                _LOGGER.debug(
                    "Token expires at: %s", self._token_expiration.isoformat()
                )
            else:
                # Do not fetch a token for every request if SMN omits ``exp``.
                self._token_expiration = dt_util.utcnow() + timedelta(minutes=55)
                _LOGGER.warning(
                    "Token does not contain expiration field; assuming 55 minutes"
                )

            self._token = token
            return token

        except UpdateFailed:
            raise
        except aiohttp.ClientError as err:
            _LOGGER.error("HTTP error fetching token: %s", err)
            raise UpdateFailed(f"Error fetching token: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching token")
            raise UpdateFailed(f"Unexpected error fetching token: {err}") from err

    async def fetch_token(self) -> str:
        """Fetch a new token, serializing concurrent callers."""
        async with self._token_lock:
            return await self._fetch_token()

    async def get_token(self) -> str:
        """Get valid token, refreshing if necessary."""
        async with self._token_lock:
            if (
                self._token
                and self._token_expiration
                and dt_util.utcnow() < (self._token_expiration - timedelta(minutes=5))
            ):
                return self._token
            return await self._fetch_token()

    @property
    def token_expiration(self) -> datetime | None:
        """Return token expiration time."""
        return self._token_expiration


class ArgentinaSMNData:
    """Class to handle SMN data."""

    def __init__(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        token_manager: SMNTokenManager,
        location_id: str | None = None,
    ) -> None:
        """Initialize the data object."""
        self._hass = hass
        self._latitude = latitude
        self._longitude = longitude
        self._location_id = location_id
        self._session = async_get_clientsession(hass)
        self._token_manager = token_manager

        self.location_name: str | None = None
        self.station_name: str | None = None
        self.station_distance_km: float | None = None
        self.current_weather_data: dict[str, Any] = {}
        self.daily_forecast: list[dict[str, Any]] = []
        self.hourly_forecast: list[dict[str, Any]] = []
        self.alerts: dict[str, Any] = {}
        self.shortterm_alerts: list[dict[str, Any]] = []
        self.heat_warnings: dict[str, Any] = {}
        # Track whether the optional alert endpoints were read successfully.
        # When they fail, the alert entities become unavailable instead of
        # silently reporting "no alerts".
        self.alerts_available = False
        self.shortterm_alerts_available = False

    async def _get_headers(self) -> dict[str, str]:
        """Get headers with authentication token."""
        token = await self._token_manager.get_token()
        return {
            "Authorization": f"JWT {token}",
            "Accept": "application/json",
        }

    async def _request_json(self, url: str, *, allow_404: bool = False) -> Any:
        """GET a JSON endpoint, retrying once with a fresh token on 401."""
        last_status: int | None = None
        last_text = ""

        for attempt in range(2):
            headers = await self._get_headers()
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as response:
                if response.status == 401 and attempt == 0:
                    _LOGGER.debug("Token rejected by %s, refreshing", url)
                    await self._token_manager.fetch_token()
                    continue

                if response.status == 404 and allow_404:
                    return None

                if response.status >= 400:
                    last_status = response.status
                    last_text = (await response.text())[:200]
                    break

                try:
                    return await response.json(content_type=None)
                except ValueError as err:
                    raise UpdateFailed(f"SMN returned invalid JSON for {url}") from err

        raise UpdateFailed(
            f"SMN request failed for {url} (HTTP {last_status}): {last_text}"
        )

    async def _get_location_id(self) -> str:
        """Get the location ID from coordinates."""
        if self._location_id:
            return self._location_id

        url = f"{API_COORD_ENDPOINT}?lat={self._latitude}&lon={self._longitude}"
        data = await self._request_json(url)

        location_id: Any = None
        if isinstance(data, dict):
            location_id = data.get("id") or data.get("location_id")
            self.location_name = data.get("name") or self.location_name
            self._update_station_info(data)
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            location_id = data[0].get("id") or data[0].get("location_id")
            self.location_name = data[0].get("name") or self.location_name
            self._update_station_info(data[0])

        if location_id is None:
            raise UpdateFailed(
                f"Could not resolve an SMN location for "
                f"{self._latitude},{self._longitude}"
            )

        self._location_id = str(location_id)
        _LOGGER.debug(
            "Location ID for %s,%s: %s (%s)",
            self._latitude,
            self._longitude,
            self._location_id,
            self.location_name,
        )
        return self._location_id

    def _update_station_info(self, data: dict[str, Any]) -> None:
        """Store the reference station details from a georef response."""
        station = (data.get("ref") or {}).get("station") or {}
        if not isinstance(station, dict):
            return
        self.station_name = station.get("name") or self.station_name
        distance = station.get("distance")
        if isinstance(distance, (int, float)):
            self.station_distance_km = float(distance)

    async def async_get_location(self) -> tuple[str, str | None]:
        """Resolve and return the SMN location ID and name."""
        location_id = await self._get_location_id()
        return location_id, self.location_name

    async def fetch_data(self) -> None:
        """Fetch data from SMN API."""
        try:
            location_id = await self._get_location_id()
            # All endpoints share one token; the token manager serializes the
            # initial token fetch, so these requests can safely run in parallel.
            results = await asyncio.gather(
                self._fetch_current_weather(location_id),
                self._fetch_forecast(location_id),
                self._fetch_alerts(location_id),
                self._fetch_shortterm_alerts(location_id),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, SMNAuthError):
                    raise result
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error fetching SMN data: {err}") from err

    async def _fetch_current_weather(self, location_id: str) -> None:
        """Fetch current weather data."""
        url = f"{API_WEATHER_ENDPOINT}/{location_id}"
        data = await self._request_json(url)

        if not isinstance(data, dict):
            raise UpdateFailed(f"Unexpected current weather payload: {data!r}")

        wind_data = data.get("wind") or {}
        location_data = data.get("location") or {}
        distance = location_data.get("distance")
        if isinstance(distance, (int, float)):
            self.station_distance_km = float(distance)

        self.current_weather_data = {
            "date": data.get("date"),
            "temperature": data.get("temperature"),
            "feels_like": data.get("feels_like"),
            "humidity": data.get("humidity"),
            "pressure": data.get("pressure"),
            "visibility": data.get("visibility"),
            "wind_speed": wind_data.get("speed"),
            "wind_deg": wind_data.get("deg"),
            "wind_direction": wind_data.get("direction"),
            "weather": data.get("weather"),
            "station_id": data.get("station_id"),
            "name": location_data.get("name"),
        }

        if self.current_weather_data.get("name"):
            self.location_name = self.current_weather_data["name"]

        _LOGGER.debug(
            "Updated current weather for location %s: temp=%s, weather=%s",
            location_id,
            self.current_weather_data.get("temperature"),
            self.current_weather_data.get("weather"),
        )

    async def _fetch_forecast(self, location_id: str) -> None:
        """Fetch forecast data."""
        url = f"{API_FORECAST_ENDPOINT}/{location_id}"
        data = await self._request_json(url)

        forecast_data = data.get("forecast", []) if isinstance(data, dict) else data
        if not isinstance(forecast_data, list):
            raise UpdateFailed(f"Unexpected forecast response format: {type(data)}")

        daily_forecast: list[dict[str, Any]] = []
        hourly_forecast: list[dict[str, Any]] = []

        for day in forecast_data:
            if not isinstance(day, dict):
                continue

            day_date = day.get("date")
            temperatures: list[float] = []
            precipitation_probabilities: list[float] = []
            precipitation_amounts: list[float] = []

            for period_name, period_time in _PERIODS:
                period_data = day.get(period_name)
                if not isinstance(period_data, dict):
                    continue

                wind_data = period_data.get("wind")
                if not isinstance(wind_data, dict):
                    wind_data = {}

                weather_obj = period_data.get("weather")
                temperature = period_data.get("temperature")
                if isinstance(temperature, (int, float)):
                    temperatures.append(temperature)

                probability = _max_range(period_data.get("rain_prob_range"))
                if probability is not None:
                    precipitation_probabilities.append(probability)

                precipitation = period_data.get("rain06h")
                if isinstance(precipitation, (int, float)):
                    precipitation_amounts.append(precipitation)

                wind_speed = _average_range(wind_data.get("speed_range"))
                if wind_speed is None:
                    wind_speed = wind_data.get("speed")

                hourly_forecast.append(
                    {
                        "date": day_date,
                        "time": period_time,
                        "datetime": _iso_datetime(day_date, period_time),
                        "temperature": temperature,
                        "feels_like": period_data.get("feels_like"),
                        "weather": weather_obj,
                        "humidity": period_data.get("humidity"),
                        "visibility": period_data.get("visibility"),
                        "precipitation_probability": (
                            int(probability) if probability is not None else None
                        ),
                        "precipitation": precipitation,
                        "wind_speed": wind_speed,
                        "wind_gust": _average_range(period_data.get("gust_range")),
                        "wind_direction": wind_data.get("deg"),
                    }
                )

            day_weather = None
            for period_name in ("afternoon", "morning", "night", "early_morning"):
                period_data = day.get(period_name)
                if isinstance(period_data, dict) and period_data.get("weather"):
                    day_weather = period_data["weather"]
                    break

            temp_max = day.get("temp_max")
            if not isinstance(temp_max, (int, float)):
                temp_max = max(temperatures) if temperatures else None

            temp_min = day.get("temp_min")
            if not isinstance(temp_min, (int, float)):
                temp_min = min(temperatures) if temperatures else None

            daily_forecast.append(
                {
                    "date": day_date,
                    "temp_max": temp_max,
                    "temp_min": temp_min,
                    "weather": day_weather,
                    "precipitation_probability": (
                        int(max(precipitation_probabilities))
                        if precipitation_probabilities
                        else None
                    ),
                    "precipitation": (
                        sum(precipitation_amounts) if precipitation_amounts else None
                    ),
                }
            )

        self.daily_forecast = daily_forecast
        self.hourly_forecast = hourly_forecast

        _LOGGER.debug(
            "Parsed %d daily forecasts and %d hourly forecasts",
            len(self.daily_forecast),
            len(self.hourly_forecast),
        )

    async def _fetch_alerts(self, location_id: str) -> None:
        """Fetch weather alerts."""
        url = f"{API_ALERT_ENDPOINT}/{location_id}"
        try:
            data = await self._request_json(url, allow_404=True)
        except SMNAuthError:
            raise
        except UpdateFailed as err:
            self.alerts_available = False
            _LOGGER.warning(
                "Could not update SMN alerts; keeping previous data: %s", err
            )
            return

        self.alerts_available = True
        if isinstance(data, dict):
            self.alerts = data
            area_id = data.get("area_id")
            if area_id:
                await self._fetch_heat_warnings(area_id)
        else:
            self.alerts = {}

    async def _fetch_shortterm_alerts(self, location_id: str) -> None:
        """Fetch short-term severe weather alerts."""
        url = f"{API_SHORTTERM_ALERT_ENDPOINT}/{location_id}"
        try:
            data = await self._request_json(url, allow_404=True)
        except SMNAuthError:
            raise
        except UpdateFailed as err:
            self.shortterm_alerts_available = False
            _LOGGER.warning(
                "Could not update short-term SMN alerts; keeping previous data: %s",
                err,
            )
            return

        self.shortterm_alerts_available = True
        if isinstance(data, list):
            self.shortterm_alerts = data
        elif isinstance(data, dict) and isinstance(data.get("alerts"), list):
            self.shortterm_alerts = data["alerts"]
        else:
            self.shortterm_alerts = []

    async def _fetch_heat_warnings(self, area_id: str) -> None:
        """Fetch heat warnings for the area (optional endpoint)."""
        url = f"{API_HEAT_WARNING_ENDPOINT}/{area_id}"
        try:
            data = await self._request_json(url, allow_404=True)
        except SMNAuthError:
            raise
        except UpdateFailed as err:
            _LOGGER.warning(
                "Could not update SMN heat warnings; keeping previous data: %s", err
            )
            return

        self.heat_warnings = data if isinstance(data, dict) else {}

    async def async_get_alerts(self, location_id: str) -> dict[str, Any] | None:
        """Fetch alerts for an arbitrary location ID."""
        data = await self._request_json(
            f"{API_ALERT_ENDPOINT}/{location_id}", allow_404=True
        )
        return data if isinstance(data, dict) else None


class ArgentinaSMNDataUpdateCoordinator(DataUpdateCoordinator[ArgentinaSMNData]):
    """Class to manage fetching SMN data."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self._token_refresh_unsub = None
        latitude = config_entry.data[CONF_LATITUDE]
        longitude = config_entry.data[CONF_LONGITUDE]
        username = config_entry.data.get(CONF_USERNAME)
        password = config_entry.data.get(CONF_PASSWORD)

        session = async_get_clientsession(hass)
        self._token_manager = SMNTokenManager(hass, session, username, password)
        self._smn_data = ArgentinaSMNData(
            hass, latitude, longitude, self._token_manager
        )

        scan_interval_minutes = config_entry.options.get(CONF_SCAN_INTERVAL)
        try:
            update_interval = timedelta(minutes=int(scan_interval_minutes))
        except (TypeError, ValueError):
            update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> ArgentinaSMNData:
        """Fetch data from API."""
        try:
            await self._smn_data.fetch_data()
        except SMNAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        self._schedule_token_refresh()
        return self._smn_data

    @property
    def token_expiration(self) -> datetime | None:
        """Return the current token expiration time."""
        return self._token_manager.token_expiration

    async def async_get_alerts_for_location(
        self, location_id: str
    ) -> dict[str, Any] | None:
        """Fetch alerts for an arbitrary location ID."""
        return await self._smn_data.async_get_alerts(location_id)

    def _schedule_token_refresh(self) -> None:
        """Schedule token refresh before expiration."""
        if self._token_refresh_unsub:
            self._token_refresh_unsub()
            self._token_refresh_unsub = None

        expiration = self._token_manager.token_expiration
        if not expiration:
            return

        now = dt_util.utcnow()
        refresh_time = expiration - timedelta(minutes=5)
        if refresh_time <= now:
            return

        seconds_until_refresh = (refresh_time - now).total_seconds()
        _LOGGER.debug(
            "Scheduling token refresh in %.0f seconds (at %s)",
            seconds_until_refresh,
            refresh_time.isoformat(),
        )

        async def _refresh_token(now):
            try:
                await self._token_manager.fetch_token()
                _LOGGER.debug("Token refreshed successfully")
                self._schedule_token_refresh()
            except Exception as err:  # noqa: BLE001 - retried on next update
                _LOGGER.warning(
                    "Failed to refresh token; will retry on next update: %s", err
                )

        self._token_refresh_unsub = async_call_later(
            self.hass, seconds_until_refresh, _refresh_token
        )

    async def async_shutdown(self) -> None:
        """Cancel the token refresh timer."""
        if self._token_refresh_unsub:
            self._token_refresh_unsub()
            self._token_refresh_unsub = None
        await super().async_shutdown()
