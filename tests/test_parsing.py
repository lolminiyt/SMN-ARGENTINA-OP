"""Forecast/current parsing + condition mapping (no HA runtime needed)."""
import sys
import types
import unittest
from pathlib import Path

from stubs import install_stubs

install_stubs()

ROOT = Path(__file__).resolve().parents[1]
for pkg, path in {
    "custom_components": str(ROOT / "custom_components"),
    "custom_components.arg_smn_ha": str(ROOT / "custom_components" / "arg_smn_ha"),
}.items():
    if pkg not in sys.modules:
        mod = types.ModuleType(pkg)
        mod.__path__ = [path]
        sys.modules[pkg] = mod

from custom_components.arg_smn_ha.coordinator import parse_current_weather, parse_forecast
from custom_components.arg_smn_ha.weather import format_condition


class TestParsing(unittest.TestCase):
    def test_parse_current(self):
        raw = {
            "temperature": 22.5, "feels_like": 24.0, "humidity": 60,
            "pressure": 1013, "visibility": 10000,
            "wind": {"speed": 15, "deg": 180},
            "weather": {"id": 3, "description": "Despejado"},
            "location": {"name": "CABA"},
        }
        cur = parse_current_weather(raw)
        self.assertEqual(cur["temperature"], 22.5)
        self.assertEqual(cur["wind_speed"], 15)
        self.assertEqual(cur["name"], "CABA")
        self.assertEqual(parse_current_weather(None), {})
        self.assertEqual(parse_current_weather("bad"), {})

    def test_parse_forecast(self):
        raw = {
            "forecast": [
                {
                    "date": "2026-10-08", "temp_max": 25, "temp_min": 15,
                    "early_morning": {"temperature": 16, "humidity": 80, "weather": {"id": 43}, "wind": {"speed_range": [10, 20], "deg": 90}},
                    "morning": {"temperature": 20, "humidity": 60, "weather": {"id": 25}, "wind": {"speed": 12, "deg": 90}},
                    "afternoon": {"temperature": 25, "humidity": 50, "weather": {"id": 3}, "wind": {"speed": 15, "deg": 180}},
                    "night": {"temperature": 18, "humidity": 70, "weather": {"id": 5}, "wind": {"speed": 8, "deg": 200}},
                }
            ]
        }
        daily, hourly = parse_forecast(raw)
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["temp_max"], 25)
        self.assertEqual(daily[0]["weather"], {"id": 3})
        self.assertEqual(len(hourly), 4)
        # speed_range mean
        self.assertAlmostEqual(hourly[0]["wind_speed"], 15.0)
        self.assertEqual(hourly[0]["datetime"], "2026-10-08T00:00:00")
        empty_daily, empty_hourly = parse_forecast({})
        self.assertEqual(empty_daily, [])
        self.assertEqual(empty_hourly, [])

    def test_format_condition_known_and_unknown(self):
        self.assertEqual(format_condition({"id": 3}, True), "sunny")
        self.assertEqual(format_condition({"id": 3}, False), "clear-night")
        self.assertEqual(format_condition({"id": 9999}, True), "sunny")
        self.assertEqual(format_condition(None, True), "sunny")
        self.assertEqual(format_condition({"no-id": 1}, False), "clear-night")


if __name__ == "__main__":
    unittest.main()
