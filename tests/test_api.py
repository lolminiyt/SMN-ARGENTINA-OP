"""Pure API helpers: URL building, token extraction, georef parsing."""
import sys
import types
import unittest
from pathlib import Path

from stubs import install_stubs

install_stubs()

# Avoid executing the real package __init__ (it needs HA + voluptuous):
# pre-register empty parent packages so only api.py/const.py load.
ROOT = Path(__file__).resolve().parents[1]
pkg_root = types.ModuleType("custom_components")
pkg_root.__path__ = [str(ROOT / "custom_components")]
pkg_domain = types.ModuleType("custom_components.arg_smn_ha")
pkg_domain.__path__ = [str(ROOT / "custom_components" / "arg_smn_ha")]
sys.modules["custom_components"] = pkg_root
sys.modules["custom_components.arg_smn_ha"] = pkg_domain

from custom_components.arg_smn_ha.api import (
    build_url,
    create_client,
    decode_jwt_expiry,
    extract_token_from_html,
    normalize_base_url,
    parse_georef_response,
)
from custom_components.arg_smn_ha.const import CONNECTION_TYPE_DIRECT, CONNECTION_TYPE_OPENSMN


class FakeSession:
    pass


class TestApiHelpers(unittest.TestCase):
    def test_normalize_base_url(self):
        self.assertEqual(normalize_base_url("http://h:6942/smn/"), "http://h:6942/smn")
        self.assertEqual(normalize_base_url("  http://h:6942/smn  "), "http://h:6942/smn")

    def test_build_url(self):
        self.assertEqual(
            build_url("http://h:6942/smn/", "/v1/weather/location/4864"),
            "http://h:6942/smn/v1/weather/location/4864",
        )
        self.assertEqual(
            build_url("http://h:6942/smn", "/v1/georef/location/coord", {"lat": -34.6, "lon": -58.4}),
            "http://h:6942/smn/v1/georef/location/coord?lat=-34.6&lon=-58.4",
        )

    def test_extract_token(self):
        html = "<script>localStorage.setItem('token', 'eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.x')</script>"
        self.assertTrue((extract_token_from_html(html) or "").startswith("eyJ"))
        self.assertIsNone(extract_token_from_html("<html>no token</html>"))

    def test_decode_jwt_expiry_malformed(self):
        self.assertIsNone(decode_jwt_expiry("not-a-jwt"))

    def test_parse_georef_dict_and_list(self):
        loc = parse_georef_response({"id": 4864, "name": "CABA"})
        self.assertEqual(loc.location_id, "4864")
        self.assertEqual(loc.name, "CABA")
        loc2 = parse_georef_response([{"id": "123", "nombre": "La Plata"}])
        self.assertEqual(loc2.location_id, "123")

    def test_parse_georef_not_found(self):
        from custom_components.arg_smn_ha.api import SmnNotFoundError

        with self.assertRaises(SmnNotFoundError):
            parse_georef_response([])

    def test_create_client_modes(self):
        proxy = create_client(CONNECTION_TYPE_OPENSMN, FakeSession(), "http://h:6942/smn", "")
        direct = create_client(CONNECTION_TYPE_DIRECT, FakeSession())
        self.assertEqual(proxy.base_url, "http://h:6942/smn")
        self.assertIsNotNone(direct)
        with self.assertRaises(Exception):
            create_client(CONNECTION_TYPE_OPENSMN, FakeSession(), "   ", "")


if __name__ == "__main__":
    unittest.main()
