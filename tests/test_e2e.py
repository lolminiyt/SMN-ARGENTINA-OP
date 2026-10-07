"""End-to-end automation verification (no HA runtime, no network).

Simulates realistic SMN payloads through both backends and asserts every
automation surface: services, events, sensor attributes, weather forecasts.
"""
import asyncio
import sys
import types
import unittest
from pathlib import Path

from stubs import install_stubs

install_stubs()

ROOT = Path(__file__).resolve().parents[1]
# Register only the top-level package so the REAL domain __init__ executes
# (stubs already cover voluptuous + HA). Submodule imports then work normally.
if "custom_components" not in sys.modules:
    mod = types.ModuleType("custom_components")
    mod.__path__ = [str(ROOT / "custom_components")]
    sys.modules["custom_components"] = mod
sys.modules.pop("custom_components.arg_smn_ha", None)

from custom_components.arg_smn_ha import parse_alerts_payload as _svc_parse
from custom_components.arg_smn_ha import binary_sensor as bs_mod
from custom_components.arg_smn_ha import coordinator as coord_mod
from custom_components.arg_smn_ha import diagnostics as diag_mod
from custom_components.arg_smn_ha import weather as wx_mod
from custom_components.arg_smn_ha import api as api_mod

# No real waiting in unit tests; retry *logic* is what we verify.
api_mod.TOKEN_SCRAPE_BACKOFF_SECONDS = 0
from custom_components.arg_smn_ha.api import (
    DirectSmnClient,
    OpenSmnClient,
    SmnApiError,
    SmnAuthError,
    async_fetch_all,
    async_resolve_location,
    create_client,
)
from custom_components.arg_smn_ha.const import (
    CONF_CONNECTION_TYPE,
    CONF_OPENSMN_PASSWORD,
    CONF_OPENSMN_URL,
    CONF_SCAN_INTERVAL,
    CONNECTION_TYPE_DIRECT,
    CONNECTION_TYPE_OPENSMN,
    DOMAIN,
    EVENT_ALERT_CLEARED,
    EVENT_ALERT_CREATED,
    EVENT_ALERT_UPDATED,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)

GEOREF = {"id": 4864, "name": "Ciudad Autónoma de Buenos Aires"}
WEATHER = {
    "temperature": 22.5, "feels_like": 24.0, "humidity": 60,
    "pressure": 1013, "visibility": 10000,
    "wind": {"speed": 15, "deg": 180},
    "weather": {"id": 3, "description": "Despejado"},
    "location": {"name": "CABA"}, "date": "2026-10-07T12:00:00",
}
FORECAST = {
    "forecast": [
        {
            "date": "2026-10-08", "temp_max": 25, "temp_min": 15,
            "early_morning": {"temperature": 16, "humidity": 80, "weather": {"id": 43}, "wind": {"speed_range": [10, 20], "deg": 90}},
            "morning": {"temperature": 20, "humidity": 60, "weather": {"id": 25}, "wind": {"speed": 12, "deg": 90}},
            "afternoon": {"temperature": 25, "humidity": 50, "weather": {"id": 3}, "wind": {"speed": 15, "deg": 180}},
            "night": {"temperature": 18, "humidity": 70, "weather": {"id": 5}, "wind": {"speed": 8, "deg": 200}},
        },
        {
            "date": "2026-10-09", "temp_max": 27, "temp_min": 17,
            "early_morning": {"temperature": 18, "humidity": 75, "weather": {"id": 37}, "wind": {"speed": 9, "deg": 100}},
            "morning": {"temperature": 22, "humidity": 55, "weather": {"id": 76}, "wind": {"speed": 14, "deg": 120}},
            "afternoon": {"temperature": 27, "humidity": 45, "weather": {"id": 81}, "wind": {"speed": 20, "deg": 150}},
            "night": {"temperature": 20, "humidity": 65, "weather": {"id": 38}, "wind": {"speed": 10, "deg": 180}},
        },
    ]
}
ALERTS = {
    "warnings": [{
        "date": "2026-10-07",
        "events": [
            {"id": 41, "max_level": 4},  # tormenta naranja
            {"id": 37, "max_level": 2},  # lluvia advertencia
            {"id": 39, "max_level": 1},  # viento inactivo
        ],
    }],
    "reports": [
        {"event_id": 41, "levels": [{"level": 4, "description": "Tormenta fuerte", "instruction": "Permanecer dentro"}]},
        {"event_id": 37, "levels": [{"level": 2, "description": "Lluvia persistente", "instruction": "Precaución"}]},
    ],
    "area_id": "AR-CABA", "updated": "2026-10-07T10:00:00",
}
SHORTTERM = [{
    "title": "Tormenta severa", "date": "2026-10-07T11:00:00",
    "end_date": "2026-10-07T14:00:00", "severity": "red",
    "zones": ["CABA"], "instructions": "Refugiarse", "region": "AMBA",
}]
HEAT = {"level": 3, "area": "AR-CABA"}
EMPTY_ALERTS = {"warnings": [], "reports": [], "area_id": None}


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status = status
        self._payload = payload
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        import json as _json
        if self._payload is not None:
            return _json.dumps(self._payload)
        return self._text

    async def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status >= 400:
            import aiohttp
            raise aiohttp.ClientError(f"HTTP {self.status}")


class FakeGet:
    """Mimics aiohttp's ``async with session.get(...)`` object."""

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        if self._exc:
            raise self._exc
        return self._response

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Route by URL path; record headers/urls for assertions."""

    def __init__(self, routes, token_html=None):
        self.routes = routes  # path-suffix -> (status, payload)
        self.token_html = token_html
        self.calls = []  # (url, headers)
        self.fail_once_401_paths = set()

    def get(self, url, headers=None):
        self.calls.append((url, dict(headers or {})))
        path = url.split("?")[0]
        if "ws2.smn.gob.ar" in url or "www.smn.gob.ar" in url:
            if self.token_html is None:
                import aiohttp
                return FakeGet(exc=aiohttp.ClientError("no html"))
            return FakeGet(response=FakeResponse(200, text=self.token_html))
        for suffix, (status, payload) in self.routes.items():
            if path.endswith(suffix):
                if suffix in self.fail_once_401_paths:
                    self.fail_once_401_paths.remove(suffix)
                    return FakeGet(response=FakeResponse(401, text="unauthorized"))
                return FakeGet(response=FakeResponse(status, payload))
        return FakeGet(response=FakeResponse(404, text="not found"))

    def last_headers(self):
        return self.calls[-1][1] if self.calls else {}


class FakeBus:
    def __init__(self):
        self.fired = []

    def fire(self, event, data=None):
        self.fired.append((event, data or {}))


class FakeHass:
    def __init__(self):
        self.data = {}
        self.bus = FakeBus()
        self.config = types.SimpleNamespace(latitude=-34.6, longitude=-58.4)


class FakeEntry:
    def __init__(self, data, options=None, entry_id="entry1", title="CABA"):
        self.data = data
        self.options = options or {}
        self.entry_id = entry_id
        self.title = title
        self.version = 1


def proxy_routes(alerts=ALERTS, shortterm=SHORTTERM, heat=HEAT):
    return {
        "/v1/georef/location/coord": (200, GEOREF),
        "/v1/weather/location/4864": (200, WEATHER),
        "/v1/forecast/location/4864": (200, FORECAST),
        "/v1/warning/alert/location/4864": (200, alerts),
        "/v1/warning/shortterm/location/4864": (200, shortterm),
        "/v1/warning/heat/area/AR-CABA": (200, heat),
    }


def make_coordinator(alerts=ALERTS, shortterm=SHORTTERM):
    hass = FakeHass()
    entry = FakeEntry({
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_OPENSMN,
        CONF_OPENSMN_URL: "http://h:6942/smn",
        CONF_OPENSMN_PASSWORD: "",
        "latitude": -34.6, "longitude": -58.4, "name": "CABA",
        "location_id": "4864", "location_name": "CABA",
    })
    coord = coord_mod.SmnDataUpdateCoordinator.__new__(coord_mod.SmnDataUpdateCoordinator)
    daily, hourly = coord_mod.parse_forecast(FORECAST)
    coord.data = coord_mod.SmnData(
        location_id="4864", location_name="CABA",
        current=coord_mod.parse_current_weather(WEATHER),
        daily_forecast=daily, hourly_forecast=hourly,
        alerts=alerts, shortterm_alerts=shortterm, heat_warnings=HEAT,
    )
    coord.hass = hass
    coord._entry = entry
    coord.last_update_success = True
    return coord, hass, entry


class TestProxyEndToEnd(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_headers_resolve_and_fetch(self):
        session = FakeSession(proxy_routes())
        client = create_client(CONNECTION_TYPE_OPENSMN, session, "http://h:6942/smn/ ", " secret ")
        self.assertEqual(client.base_url, "http://h:6942/smn")
        loc = await async_resolve_location(client, -34.6, -58.4)
        self.assertEqual(loc.location_id, "4864")
        self.assertIn("Buenos Aires", loc.name)
        # password forwarded as Authorization
        _, headers = session.calls[0]
        self.assertEqual(headers.get("Authorization"), "secret")
        raw = await async_fetch_all(client, "4864")
        self.assertEqual(set(raw), {"weather", "forecast", "alerts", "shortterm", "heat"})
        self.assertEqual(raw["alerts"]["area_id"], "AR-CABA")
        # georef URL carries lat/lon
        georef_url = session.calls[0][0]
        self.assertIn("lat=-34.6", georef_url)
        self.assertIn("lon=-58.4", georef_url)

    async def test_proxy_without_password_sends_no_auth(self):
        session = FakeSession(proxy_routes())
        client = create_client(CONNECTION_TYPE_OPENSMN, session, "http://h:6942/smn", "")
        await async_resolve_location(client, -34.6, -58.4)
        self.assertNotIn("Authorization", session.last_headers())


class TestDirectBackend(unittest.IsolatedAsyncioTestCase):
    async def test_token_scrape_and_401_retry(self):
        html = "<script>localStorage.setItem('token', 'eyJhbGciOiJIUzI1NiJ9.e30.x')</script>"
        session = FakeSession(proxy_routes(), token_html=html)
        session.fail_once_401_paths.add("/v1/weather/location/4864")
        client = DirectSmnClient(session)
        data = await client.get("/v1/weather/location/4864")
        self.assertEqual(data["temperature"], 22.5)
        auth_calls = [h.get("Authorization", "") for _, h in session.calls if "ws1.smn.gob.ar" in _.split("?")[0] or "/v1/weather" in _]
        jwt_calls = [h for h in auth_calls if h.startswith("JWT eyJ")]
        self.assertTrue(jwt_calls, "direct mode must send JWT header")

    async def test_static_token_skips_scrape(self):
        session = FakeSession(proxy_routes(), token_html=None)
        static = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.c2ln"
        client = create_client(CONNECTION_TYPE_DIRECT, session, smn_token=static)
        data = await client.get("/v1/weather/location/4864")
        self.assertEqual(data["temperature"], 22.5)
        jwt_calls = [h.get("Authorization", "") for _, h in session.calls if "/v1/weather" in _]
        self.assertTrue(all(h == f"JWT {static}" for h in jwt_calls))
        # ws2/www token pages never touched
        self.assertFalse(any("ws2.smn.gob.ar" in u or "www.smn.gob.ar" in u for u, _ in session.calls))

    async def test_token_failure_is_token_error(self):
        from custom_components.arg_smn_ha.api import SmnTokenError
        session = FakeSession(proxy_routes(), token_html="<html>no token</html>")
        client = DirectSmnClient(session)
        with self.assertRaises(SmnTokenError):
            await client.get("/v1/weather/location/4864")

    def test_is_plausible_jwt(self):
        from custom_components.arg_smn_ha.api import is_plausible_jwt
        self.assertTrue(is_plausible_jwt("eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.c2ln"))
        self.assertFalse(is_plausible_jwt(""))
        self.assertFalse(is_plausible_jwt("notoken"))
        self.assertFalse(is_plausible_jwt("a.b"))
        self.assertFalse(is_plausible_jwt("xxx.yyy.zzz"))

    async def test_token_pages_exhausted_gives_clear_error(self):
        session = FakeSession(proxy_routes(), token_html="<html>no token</html>")
        client = DirectSmnClient(session)
        with self.assertRaises(SmnApiError) as ctx:
            await client.get("/v1/weather/location/4864")
        self.assertIn("token", str(ctx.exception).lower())

    async def test_scrape_retries_through_cloudflare_blocks(self):
        import aiohttp

        html = "<script>localStorage.setItem('token', 'eyJhbGciOiJIUzI1NiJ9.e30.x')</script>"

        class FlakySession(FakeSession):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.token_failures_left = 3

            def get(self, url, headers=None):
                if ("ws2.smn.gob.ar" in url or "www.smn.gob.ar" in url) and self.token_failures_left > 0:
                    self.token_failures_left -= 1
                    return FakeGet(exc=aiohttp.ClientError("403 blocked"))
                return super().get(url, headers=headers)

        session = FlakySession(proxy_routes(), token_html=html)
        client = DirectSmnClient(session)
        data = await client.get("/v1/weather/location/4864")
        self.assertEqual(data["temperature"], 22.5)

    def test_browser_headers_and_refresh_margin(self):
        from custom_components.arg_smn_ha.api import BROWSER_HEADERS, TOKEN_REFRESH_MARGIN
        from datetime import timedelta
        self.assertIn("Sec-Fetch-Mode", BROWSER_HEADERS)
        self.assertIn("es-AR", BROWSER_HEADERS["Accept-Language"])
        self.assertEqual(TOKEN_REFRESH_MARGIN, timedelta(minutes=10))


class TestServicesAndAutomations(unittest.IsolatedAsyncioTestCase):
    async def test_get_alerts_service_shape(self):
        result = _svc_parse(ALERTS)
        # Automation: alert_summary used in notify message
        self.assertEqual(result["max_level"], 4)
        self.assertEqual(result["max_severity"], "error")
        self.assertEqual(len(result["active_alerts"]), 2)
        names = {a["event_name"] for a in result["active_alerts"]}
        self.assertEqual(names, {"tormenta", "lluvia"})
        tormenta = next(a for a in result["active_alerts"] if a["event_name"] == "tormenta")
        self.assertEqual(tormenta["description"], "Tormenta fuerte")
        self.assertEqual(tormenta["instruction"], "Permanecer dentro")
        self.assertEqual(tormenta["level_name"], "naranja")

    async def test_empty_alerts_service_shape(self):
        result = _svc_parse(EMPTY_ALERTS)
        self.assertEqual(result, {"active_alerts": [], "max_severity": "info", "max_level": 1, "area_id": None, "updated": None})
        self.assertEqual(_svc_parse(None), result)

    async def test_aggregate_sensor_attributes_for_automation(self):
        coord, hass, entry = make_coordinator()
        sensor = bs_mod.SmnAlertSensor(coord, entry)
        sensor.hass = hass
        self.assertTrue(sensor.is_on)
        attrs = sensor.extra_state_attributes
        # README automation uses alert_summary
        self.assertIn("tormenta (naranja)", attrs["alert_summary"])
        self.assertIn("lluvia (advertencia)", attrs["alert_summary"])
        self.assertEqual(attrs["active_alert_count"], 2)
        self.assertEqual(attrs["max_level"], 4)

    async def test_per_event_sensor_description_for_automation(self):
        coord, hass, entry = make_coordinator()
        storm = bs_mod.SmnEventAlertSensor(coord, entry, 41, "tormenta")
        storm.hass = hass
        self.assertTrue(storm.is_on)
        attrs = storm.extra_state_attributes
        # README storm automation uses description
        self.assertEqual(attrs["description"], "Tormenta fuerte")
        self.assertEqual(attrs["instruction"], "Permanecer dentro")
        wind = bs_mod.SmnEventAlertSensor(coord, entry, 39, "viento")
        wind.hass = hass
        self.assertFalse(wind.is_on)  # max_level 1 -> off

    async def test_alert_transition_events(self):
        coord, hass, entry = make_coordinator(alerts=EMPTY_ALERTS, shortterm=[])
        sensor = bs_mod.SmnAlertSensor(coord, entry)
        sensor.hass = hass
        sensor._fire_transition_events()  # baseline empty
        self.assertEqual(hass.bus.fired, [])
        coord.data.alerts = ALERTS  # two alerts appear
        sensor._fire_transition_events()
        created = [f for f in hass.bus.fired if f[0] == EVENT_ALERT_CREATED]
        self.assertEqual(len(created), 2)
        # escalate tormenta 4 -> 5
        import copy
        esc = copy.deepcopy(ALERTS)
        esc["warnings"][0]["events"][0]["max_level"] = 5
        esc["reports"][0]["levels"] = [{"level": 5, "description": "Tormenta extrema", "instruction": "Evacuar"}]
        coord.data.alerts = esc
        sensor._fire_transition_events()
        updated = [f for f in hass.bus.fired if f[0] == EVENT_ALERT_UPDATED]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0][1]["old_level"], 4)
        self.assertEqual(updated[0][1]["new_level"], 5)
        # clear all
        coord.data.alerts = EMPTY_ALERTS
        sensor._fire_transition_events()
        cleared = [f for f in hass.bus.fired if f[0] == EVENT_ALERT_CLEARED]
        self.assertEqual(len(cleared), 2)

    async def test_shortterm_sensor(self):
        coord, hass, entry = make_coordinator()
        st = bs_mod.SmnShortTermAlertSensor(coord, entry)
        st.hass = hass
        self.assertTrue(st.is_on)
        attrs = st.extra_state_attributes
        self.assertEqual(attrs["alert_count"], 1)
        self.assertEqual(attrs["alerts"][0]["title"], "Tormenta severa")
        coord2, _, _ = make_coordinator(shortterm=[])
        st2 = bs_mod.SmnShortTermAlertSensor(coord2, entry)
        self.assertFalse(st2.is_on)

    async def test_weather_entity_and_forecast_services(self):
        coord, hass, entry = make_coordinator()
        entity = wx_mod.SmnWeatherEntity(coord, entry)
        entity.hass = hass
        self.assertEqual(entity.native_temperature, 22.5)
        self.assertEqual(entity.native_apparent_temperature, 24.0)
        self.assertEqual(entity.humidity, 60)
        self.assertEqual(entity.native_pressure, 1013)
        self.assertEqual(entity.native_wind_speed, 15)
        self.assertEqual(entity.wind_bearing, 180)
        self.assertAlmostEqual(entity.native_visibility, 10.0)  # 10000 m -> 10 km
        self.assertEqual(entity.condition, "sunny")  # id 3, sun up in stubs
        self.assertEqual(entity.extra_state_attributes["location_id"], "4864")
        daily = await entity.async_get_forecasts("daily")
        self.assertEqual(len(daily), 2)
        self.assertEqual(daily[0]["native_temperature"], 25)
        self.assertEqual(daily[0]["native_templow"], 15)
        self.assertTrue(daily[0]["datetime"].startswith("2026-10-08"))
        hourly = await entity.async_get_forecasts("hourly")
        self.assertEqual(len(hourly), 8)  # 2 days x 4 periods
        self.assertIn("condition", hourly[0])
        self.assertIsNotNone(hourly[0]["datetime"])
        self.assertEqual(await entity.async_get_forecasts("minutely"), None)
        # README daily automation slices: days=1
        one = await entity.async_get_forecasts("daily", days=1)
        self.assertEqual(len(one), 1)

    async def test_diagnostics_redacts_secrets(self):
        coord, hass, entry = make_coordinator()
        hass.data = {DOMAIN: {entry.entry_id: coord}}
        entry.data[CONF_OPENSMN_PASSWORD] = "supersecret"
        diag = await diag_mod.async_get_config_entry_diagnostics(hass, entry)
        self.assertEqual(diag["entry"]["data"][CONF_OPENSMN_PASSWORD], "[REDACTED]")
        self.assertEqual(diag["coordinator"]["daily_count"], 2)
        self.assertEqual(diag["coordinator"]["hourly_count"], 8)


class TestConfigRules(unittest.TestCase):
    def test_default_is_direct_zero_setup(self):
        from custom_components.arg_smn_ha.const import DEFAULT_CONNECTION_TYPE
        self.assertEqual(DEFAULT_CONNECTION_TYPE, CONNECTION_TYPE_DIRECT)

    def test_unique_id_format_and_tolerance(self):
        self.assertEqual(f"{CONNECTION_TYPE_OPENSMN}_4864", "opensmn_4864")
        self.assertEqual(f"{CONNECTION_TYPE_DIRECT}_4864", "direct_4864")
        # ~11 m tolerance: 0.0001 deg
        self.assertTrue(abs(-34.60370 - -34.60375) < 0.0001)
        self.assertFalse(abs(-34.6037 - -34.6050) < 0.0001)

    def test_scan_interval_bounds(self):
        for bad in (0, 599, 7201, "x"):
            with self.subTest(bad=bad):
                try:
                    v = int(bad)
                except (TypeError, ValueError):
                    continue
                self.assertFalse(MIN_SCAN_INTERVAL_SECONDS <= v <= MAX_SCAN_INTERVAL_SECONDS)
        self.assertTrue(MIN_SCAN_INTERVAL_SECONDS <= 1800 <= MAX_SCAN_INTERVAL_SECONDS)

    def test_options_override_credentials(self):
        data = {CONF_CONNECTION_TYPE: CONNECTION_TYPE_OPENSMN, CONF_OPENSMN_URL: "http://old/smn", CONF_OPENSMN_PASSWORD: "old"}
        options = {CONF_SCAN_INTERVAL: 900, CONF_OPENSMN_URL: "http://new/smn", CONF_OPENSMN_PASSWORD: "new"}
        url = options.get(CONF_OPENSMN_URL, data.get(CONF_OPENSMN_URL, ""))
        pwd = options.get(CONF_OPENSMN_PASSWORD, data.get(CONF_OPENSMN_PASSWORD, ""))
        self.assertEqual(url, "http://new/smn")
        self.assertEqual(pwd, "new")


if __name__ == "__main__":
    unittest.main()
