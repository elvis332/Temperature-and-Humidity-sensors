"""Review-time checks for service templates and the EMS integration contract."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DeploymentContract(unittest.TestCase):
    def test_windows_services_are_auto_and_same_server(self):
        for name, expected in (("bridge-service.xml", "SanderZigbeeBridge"),
                               ("zigbee2mqtt-service.xml", "SanderZigbee2MQTT")):
            root = ET.parse(ROOT / "deploy" / name).getroot()
            self.assertEqual(root.findtext("id"), expected)
            self.assertEqual(root.findtext("startmode"), "Automatic")
            self.assertEqual(root.findtext("depend"), "mosquitto")
            self.assertEqual(root.find("onfailure").attrib.get("action"), "restart")

    def test_consistent_sensor_mapping(self):
        cfg = json.loads((ROOT / "bridge" / "config.production.example.json").read_text())
        recovery = json.loads((ROOT / "deploy" / "recovery.example.json").read_text())
        profile = yaml.safe_load((ROOT / "config" / "profiles" / "SNZB02D.yaml").read_text())
        self.assertEqual(cfg["modbus_host"], "127.0.0.1")
        self.assertEqual(cfg["sensors"][0]["unit_id"], 1)
        self.assertEqual(cfg["sensors"][0]["offline_seconds"], 900)
        self.assertEqual(recovery["sensors"][0]["offline_seconds"], 900)
        self.assertEqual(cfg["sensors"][0]["topic"], recovery["sensors"][0]["topic"])
        self.assertEqual([p["key"] for p in profile["points"]],
                         ["temperature_c", "humidity_pct", "battery_pct", "lqi"])
        self.assertEqual([p["source"]["register_address"] for p in profile["points"]],
                         [0, 1, 2, 3])

    def test_compatible_driver_and_availability(self):
        settings = yaml.safe_load((ROOT / "bridge" / "zigbee2mqtt.example.yaml").read_text())
        self.assertEqual(settings["serial"]["adapter"], "ezsp")
        self.assertEqual(settings["advanced"]["last_seen"], "ISO_8601")
        self.assertEqual(settings["availability"]["passive"]["timeout"], 15)

    def test_ems_patch_has_no_database_or_wired_mutations(self):
        patch = (ROOT / "integrations" / "modbus" / "apply_ui.py").read_text()
        self.assertNotIn("create_all(", patch)
        self.assertNotIn("drop_all(", patch)
        self.assertNotIn("WTR10E.yaml\", \"w\"", patch)
        self.assertIn("BatteryIcon", patch)


if __name__ == "__main__":
    unittest.main()
