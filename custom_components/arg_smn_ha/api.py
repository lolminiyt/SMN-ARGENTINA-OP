"""API clients for OpenSMN proxy and direct SMN access.

Both backends expose the same SMN v1 paths; only the base URL and the
authentication mechanism differ:

* OpenSMN proxy: ``{opensmn_base}/v1/...`` with an optional ``Authorization``
  header (the proxy itself owns/refreshes the SMN JWT).
* Direct SMN: ``https://ws1.smn.gob.ar/v1/...`` with a ``JWT <token>`` header
  where the token is scraped from the SMN website.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import aiohttp
import async_timeout

from homeassistant.util import dt as dt_util

from .const import (
    CONNECTION_TYPE_DIRECT,
    CONNECTION_TYPE_OPENSMN,
    PATH_ALERT,
    PATH_FORECAST,
    PATH_GEOREF_COORD,
    PATH_HEAT_WARNING,
    PATH_SHORTTERM_ALERT,
    PATH_WEATHER,
    REQUEST_TIMEOUT_SECONDS,
    SMN_DIRECT_BASE_URL,
    SMN_TOKEN_PAGES,
)

_LOGGER = logging.getLogger(__name__)

_TOKEN_PATTERNS: tuple[str, ...] = (
    r"localStorage\.setItem\(\s*['\"]token['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    r'setItem\(\s*["\']token["\']\s*,\s*["\']([^"\']+)["\']',
    r'["\']token["\']\s*:\s*["\']([^"\']+)["\']',
    r"(?:var|let|const)\s+token\s*=\s*[\"']([^\"']+)[\"']",
    r"token\s*=\s*[\"']([^\"']+)[\"']",
)


class SmnApiError(Exception):
    """Base error for SMN communication failures."""


class SmnAuthError(SmnApiError):
    """Authentication failed (bad proxy password or rejected JWT)."""


class SmnNotFoundError(SmnApiError):
    """Location or resource not found (usually coordinates outside Argentina)."""


class SmnTokenError(SmnApiError):
    """SMN token could not be obtained (scraping blocked or page unreachable)."""


def normalize_base_url(url: str) -> str:
    """Normalize a user-supplied base URL (strip whitespace/trailing slash)."""
    return url.strip().rstrip("/")


def build_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    """Join base + path and optionally append a query string."""
    base = normalize_base_url(base_url)
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base}{path}"
    if params:
        url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
    return url


def extract_token_from_html(html: str) -> str | None:
    """Extract a JWT token from SMN website HTML using known patterns."""
    for pattern in _TOKEN_PATTERNS:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


def is_plausible_jwt(token: str) -> bool:
    """Cheap client-side check: 3 dot-separated parts starting with ``eyJ``."""
    parts = (token or "").strip().split(".")
    return len(parts) == 3 and parts[0].startswith("eyJ") and all(parts)


def decode_jwt_expiry(token: str) -> datetime | None:
    """Decode the ``exp`` claim of a JWT without verification."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        if exp is None:
            return None
        return datetime.fromtimestamp(int(exp), tz=dt_util.UTC)
    except Exception:  # noqa: BLE001 - malformed tokens must not crash setup
        return None


@dataclass
class ResolvedLocation:
    """Location resolved from coordinates."""

    location_id: str
    name: str | None = None


def parse_georef_response(data: Any) -> ResolvedLocation:
    """Parse the georef coord endpoint response (dict or single-item list)."""
    if isinstance(data, list):
        if not data:
            raise SmnNotFoundError("No SMN location found for these coordinates")
        data = data[0]
    if not isinstance(data, dict):
        raise SmnApiError(f"Unexpected georef response: {type(data).__name__}")
    location_id = data.get("id", data.get("location_id", data.get("locationId")))
    if location_id is None:
        raise SmnApiError(f"Georef response has no id: {data!r:.200}")
    name = data.get("name", data.get("nombre", data.get("location")))
    if isinstance(name, dict):
        name = name.get("name")
    return ResolvedLocation(location_id=str(location_id), name=str(name) if name else None)


class BaseSmnClient:
    """Shared GET + error-mapping logic for both backends."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    async def _get_json(self, url: str, headers: dict[str, str]) -> Any:
        try:
            async with async_timeout.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.get(url, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status == 401:
                        raise SmnAuthError("Unauthorized (401). Check password/token.")
                    if resp.status == 404:
                        raise SmnNotFoundError("Not found (404).")
                    if resp.status == 429:
                        raise SmnApiError("Rate limited (429). Try again later.")
                    if resp.status >= 500:
                        raise SmnApiError(f"Upstream error (HTTP {resp.status}).")
                    if resp.status != 200:
                        raise SmnApiError(f"Unexpected HTTP {resp.status}: {text[:200]}")
                    try:
                        return json.loads(text)
                    except ValueError as err:
                        raise SmnApiError("Upstream returned invalid JSON.") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SmnApiError(f"Connection failed: {err}") from err

    async def get_path(
        self, base_url: str, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """GET a relative path against a base URL."""
        url = build_url(base_url, path, params)
        _LOGGER.debug("SMN GET %s", url.split("?")[0])
        return await self._get_json(url, await self._headers())


class OpenSmnClient(BaseSmnClient):
    """Client for a self-hosted OpenSMN proxy instance."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        password: str = "",
    ) -> None:
        super().__init__(session)
        self._base_url = normalize_base_url(base_url)
        self._password = (password or "").strip()

    @property
    def base_url(self) -> str:
        """Return the configured proxy base URL."""
        return self._base_url

    async def _headers(self) -> dict[str, str]:
        headers = await super()._headers()
        if self._password:
            headers["Authorization"] = self._password
        return headers

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a path through the OpenSMN proxy."""
        return await self.get_path(self._base_url, path, params)


class DirectSmnTokenManager:
    """Fetch and cache the SMN JWT by scraping the SMN website.

    A user-supplied static token (pasted from the browser) always wins:
    Cloudflare intermittently blocks scraping, so manual paste is the
    reliable fallback.
    """

    def __init__(self, session: aiohttp.ClientSession, static_token: str = "") -> None:
        self._session = session
        self._static_token = (static_token or "").strip() or None
        self._token: str | None = None
        self._expires: datetime | None = None
        if self._static_token:
            self._token = self._static_token
            self._expires = decode_jwt_expiry(self._static_token)

    async def _fetch_from_page(self, page_url: str) -> str | None:
        async with async_timeout.timeout(REQUEST_TIMEOUT_SECONDS):
            async with self._session.get(page_url) as resp:
                resp.raise_for_status()
                html = await resp.text()
        token = extract_token_from_html(html)
        if token:
            _LOGGER.debug("Found SMN token via %s (%d chars)", page_url, len(token))
        return token

    async def fetch_token(self) -> str:
        """Fetch a fresh token, trying each known SMN page in order."""
        if self._static_token:
            self._token = self._static_token
            return self._static_token
        last_error: Exception | None = None
        for page_url in SMN_TOKEN_PAGES:
            try:
                token = await self._fetch_from_page(page_url)
                if token:
                    self._token = token
                    self._expires = decode_jwt_expiry(token)
                    if self._expires:
                        _LOGGER.info("SMN token expires at %s", self._expires.isoformat())
                    return token
                last_error = SmnTokenError(f"No token found in {page_url}")
            except (aiohttp.ClientError, TimeoutError) as err:
                last_error = err
                _LOGGER.debug("Token fetch failed for %s: %s", page_url, err)
        raise SmnTokenError(f"Could not obtain SMN token (paste it manually): {last_error}")

    async def get_token(self) -> str:
        """Return a cached token, refreshing when close to expiry."""
        if self._static_token:
            return self._static_token
        if self._token and self._expires:
            if dt_util.utcnow() < (self._expires - timedelta(minutes=5)):
                return self._token
        elif self._token and self._expires is None:
            return self._token
        return await self.fetch_token()


class DirectSmnClient(BaseSmnClient):
    """Client that talks to SMN directly (same behavior as reference integration)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token_manager: DirectSmnTokenManager | None = None,
        static_token: str = "",
    ) -> None:
        super().__init__(session)
        self._tokens = token_manager or DirectSmnTokenManager(session, static_token)

    async def _headers(self) -> dict[str, str]:
        headers = await super()._headers()
        headers["Authorization"] = f"JWT {await self._tokens.get_token()}"
        return headers

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a path directly from SMN, retrying once on 401 (expired JWT)."""
        try:
            return await self.get_path(SMN_DIRECT_BASE_URL, path, params)
        except SmnAuthError:
            _LOGGER.info("SMN token rejected, refreshing once and retrying")
            await self._tokens.fetch_token()
            return await self.get_path(SMN_DIRECT_BASE_URL, path, params)


SmnClient = OpenSmnClient | DirectSmnClient


def create_client(
    connection_type: str,
    session: aiohttp.ClientSession,
    opensmn_url: str = "",
    opensmn_password: str = "",
    smn_token: str = "",
) -> SmnClient:
    """Factory used by config flow, coordinator and services."""
    if connection_type == CONNECTION_TYPE_DIRECT:
        return DirectSmnClient(session, static_token=smn_token)
    if connection_type == CONNECTION_TYPE_OPENSMN:
        if not (opensmn_url or "").strip():
            raise SmnApiError("OpenSMN URL is required in proxy mode.")
        return OpenSmnClient(session, opensmn_url, opensmn_password)
    raise SmnApiError(f"Unknown connection type: {connection_type}")


async def async_resolve_location(
    client: SmnClient, latitude: float, longitude: float
) -> ResolvedLocation:
    """Resolve SMN location id + display name from coordinates."""
    data = await client.get(PATH_GEOREF_COORD, {"lat": latitude, "lon": longitude})
    return parse_georef_response(data)


async def async_fetch_all(
    client: SmnClient, location_id: str
) -> dict[str, Any]:
    """Fetch weather, forecast and alerts for a location id.

    Individual non-critical fetches degrade gracefully: weather/forecast
    failures raise, while alert endpoints return empty defaults (alerts are
    legitimately absent most of the time).
    """

    async def _safe(coro: Any, default: Any) -> Any:
        try:
            return await coro
        except (SmnNotFoundError, SmnApiError) as err:
            _LOGGER.debug("Optional SMN fetch degraded: %s", err)
            return default

    weather = await client.get(f"{PATH_WEATHER}/{location_id}")
    forecast = await client.get(f"{PATH_FORECAST}/{location_id}")
    alerts = await _safe(client.get(f"{PATH_ALERT}/{location_id}"), {})
    shortterm = await _safe(client.get(f"{PATH_SHORTTERM_ALERT}/{location_id}"), [])
    heat: Any = {}
    area_id = alerts.get("area_id") if isinstance(alerts, dict) else None
    if area_id:
        heat = await _safe(client.get(f"{PATH_HEAT_WARNING}/{area_id}"), {})
    return {
        "weather": weather,
        "forecast": forecast,
        "alerts": alerts if isinstance(alerts, dict) else {},
        "shortterm": shortterm if isinstance(shortterm, list) else [],
        "heat": heat if isinstance(heat, dict) else {},
    }
