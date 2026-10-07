"""Release hygiene: manifest, hacs, translations and services stay in sync."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "arg_smn_ha"


class TestReleaseFiles(unittest.TestCase):
    def test_manifest(self):
        manifest = json.loads((COMP / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], "arg_smn_ha")
        self.assertTrue(manifest["config_flow"])
        self.assertTrue(manifest["codeowners"])
        self.assertTrue(manifest["version"])
        self.assertEqual(manifest["integration_type"], "service")
        self.assertEqual(manifest["iot_class"], "cloud_polling")

    def test_hacs_matches_manifest(self):
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        manifest = json.loads((COMP / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(hacs["filename"], manifest["domain"])
        self.assertFalse(hacs["content_in_root"])

    def test_translations_in_sync(self):
        strings = json.loads((COMP / "strings.json").read_text(encoding="utf-8"))
        en = json.loads((COMP / "translations" / "en.json").read_text(encoding="utf-8"))
        es = json.loads((COMP / "translations" / "es.json").read_text(encoding="utf-8"))
        self.assertEqual(strings, en, "strings.json and en.json must stay identical")
        # Same key tree in es (values may differ).
        def keys(o):
            if isinstance(o, dict):
                return {k: keys(v) for k, v in o.items()}
            return None
        self.assertEqual(keys(en), keys(es), "es.json key tree must match en.json")

    def test_entity_translation_keys_have_icons(self):
        strings = json.loads((COMP / "strings.json").read_text(encoding="utf-8"))
        icons = json.loads((COMP / "icon.json").read_text(encoding="utf-8"))
        entity_keys = set(strings.get("entity", {}).get("binary_sensor", {}))
        entity_keys |= set(strings.get("entity", {}).get("weather", {}))
        icon_keys = set(icons.get("entity", {}).get("binary_sensor", {}))
        icon_keys |= set(icons.get("entity", {}).get("weather", {}))
        missing = entity_keys - icon_keys
        self.assertFalse(missing, f"icon.json missing keys: {missing}")

    def test_services_yaml_loads(self):
        try:
            import yaml  # type: ignore
        except ImportError:
            self.skipTest("pyyaml not installed")
        with open(COMP / "services.yaml", encoding="utf-8") as f:
            services = yaml.safe_load(f)
        self.assertIn("get_alerts", services)
        self.assertIn("get_alerts_for_location", services)


if __name__ == "__main__":
    unittest.main()
