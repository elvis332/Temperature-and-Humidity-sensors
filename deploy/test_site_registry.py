"""Deterministic scale, identity and service-generation tests. No Windows/SQL side effects."""
import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from deploy.site_registry import build, validate
from deploy.server_preflight import evaluate


ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / "deploy/site-manifest.example.json").read_text(encoding="utf-8"))


class SiteRegistryTests(unittest.TestCase):
    def test_single_gateway_generates_ems_registration_and_read_only_bridge(self):
        outputs = build(example())
        self.assertIn("bridge.GW01.json", outputs)
        self.assertIn("recovery.GW01.json", outputs)
        self.assertIn("SanderBridgeGW01.xml", outputs)
        bridge = json.loads(outputs["bridge.GW01.json"])
        recovery = json.loads(outputs["recovery.GW01.json"])
        self.assertEqual(bridge["sensors"][0]["topic"], "zigbee2mqtt/TH-02")
        self.assertEqual(bridge["sensors"][0]["unit_id"], 1)
        self.assertEqual(bridge["modbus_host"], "127.0.0.1")
        self.assertNotEqual(bridge["mqtt_auth_file"], recovery["mqtt_auth_file"])
        self.assertIn("REVIEW_ONLY_NOT_IMPORTED", outputs["ems-device-registration-review.csv"])
        self.assertIn("SNZB02D", outputs["ems-device-registration-review.csv"])
        root = ET.fromstring(outputs["SanderBridgeGW01.xml"])
        self.assertEqual(root.findtext("serviceaccount/username"), r"NT AUTHORITY\LocalService")
        self.assertEqual(root.findtext("startmode"), "Automatic")

    def test_multiple_gateways_over_single_modbus_unit_limit(self):
        manifest = example()
        gw = copy.deepcopy(manifest["gateways"][0])
        gw.update(id="GW02", mqtt_base_topic="zigbee2mqtt-gw02",
                  modbus_port=1503, z2m_ui_port=8081,
                  coordinator_host="192.168.35.12")
        manifest["gateways"].append(gw)
        sensor = manifest["sensors"][0]
        manifest["sensors"] = []
        for idx in range(248):
            item = dict(sensor)
            item["device_id"] = f"TH-{idx+2:03d}"
            item["friendly_name"] = item["device_id"]
            item["ieee_address"] = f"0x{idx+1:016x}"
            item["gateway_id"] = "GW01" if idx < 247 else "GW02"
            item["unit_id"] = idx+1 if idx < 247 else 1
            item["location"] = f"Zone {idx+1}"
            manifest["sensors"].append(item)
        out = build(manifest)
        self.assertEqual(len(json.loads(out["bridge.GW01.json"])["sensors"]), 247)
        self.assertEqual(len(json.loads(out["bridge.GW02.json"])["sensors"]), 1)
        self.assertIn("SanderBridgeGW02.xml", out)
        self.assertIn("SanderZ2MGW02.xml", out)
        self.assertIn("1503", out["ems-device-registration-review.csv"])
        self.assertNotEqual(json.loads(out["recovery.GW01.json"])["client_id"],
                            json.loads(out["recovery.GW02.json"])["client_id"])

    def test_reject_duplicate_unit_and_ieee_and_id(self):
        for change in ("unit_id", "ieee_address", "device_id"):
            manifest = example()
            other = copy.deepcopy(manifest["sensors"][0])
            other["device_id"] = "TH-03"
            other["friendly_name"] = "TH-03"
            other["unit_id"] = 2
            other["ieee_address"] = "0x0000000000000002"
            other[change] = manifest["sensors"][0][change]
            manifest["sensors"].append(other)
            with self.assertRaises(ValueError):
                validate(manifest)

    def test_reject_conflicting_ports_and_topics(self):
        manifest = example()
        gw = dict(manifest["gateways"][0], id="GW02")
        manifest["gateways"].append(gw)
        with self.assertRaises(ValueError):
            validate(manifest)

    def test_uninstalled_preflight_reports_missing_paired_data(self):
        with tempfile.TemporaryDirectory() as folder:
            errors, warnings = evaluate(Path(folder), example())
            self.assertTrue(errors)
            self.assertIn("preserved Zigbee network", "\n".join(errors))

    def test_valid_staged_config_preserves_network_identity(self):
        manifest = example()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            entry = root / "zigbee2mqtt/GW01/node_modules/zigbee2mqtt/index.js"
            entry.parent.mkdir(parents=True)
            entry.write_text("mock existing runtime")
            datadir = root / "Config/zigbee2mqtt.GW01"
            datadir.mkdir(parents=True)
            cfg = {
                "serial": {"port": "tcp://192.168.35.11:6638", "adapter": "ezsp"},
                "mqtt": {"base_topic": "zigbee2mqtt"},
                "advanced": {"last_seen": "ISO_8601"},
                "devices": {"0xb0e8e8fffef4f4de": {"friendly_name": "TH-02"}},
            }
            (datadir/"configuration.yaml").write_text(
                json.dumps(cfg), encoding="utf-8")
            (datadir/"database.db").write_text("existing paired IEEE network data")
            errors, warnings = evaluate(root, manifest)
            self.assertFalse(errors, errors)


if __name__ == "__main__":
    unittest.main()
