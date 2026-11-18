"""Management tests use a fake broker and fake existing EMS admin guard.

No physical device, MQTT broker, production SQL, or Zigbee network is touched.
"""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import paho.mqtt.client as mqtt

from integrations.ems.zigbee_control import (
    ZigbeeFleet, ZigbeeGateway, InvalidRequest, Unavailable, exposed_names,
)

ROOT = Path(__file__).resolve().parents[2]
IEEE = "0xb0e8e8fffef4f4de"


def manifest():
    return json.loads((ROOT / "deploy/site-manifest.example.json").read_text(encoding="utf-8"))


def discovered(ieee=IEEE, friendly="TH-02"):
    return {
        "ieee_address": ieee, "friendly_name": friendly, "model_id": "SNZB-02D",
        "definition": {"model": "SNZB-02D", "exposes": [
            {"name": "temperature", "access": 1},
            {"name": "humidity", "access": 1},
            {"name": "comfort_temperature_max", "access": 3},
            {"name": "comfort_humidity_max", "access": 3},
            {"name": "temperature_calibration", "access": 3}
        ]}
    }


def deliver(gw, topic, content):
    gw._on_message(None, None, SimpleNamespace(
        topic=topic, payload=json.dumps(content).encode("utf-8"), retain=False))


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.messages = []
        self.subscriptions = []
        self.username = None
        self.on_message = None
        self.gateway = None
    def username_pw_set(self, username, password):
        self.username = username
    def connect_async(self, *args):
        return None
    def loop_start(self):
        return None
    def disconnect(self):
        return None
    def loop_stop(self):
        return None
    def subscribe(self, topics):
        self.subscriptions.extend(topics)
    def publish(self, topic, payload, qos):
        self.messages.append((topic, json.loads(payload), qos))
        data = json.loads(payload)
        if "/bridge/request/" in topic:
            prefix, command = topic.split("/bridge/request/", 1)
            deliver(self.gateway, prefix + "/bridge/response/" + command, {
                "transaction": data["transaction"], "status": "ok", "data": {}
            })
        return SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)


class ZigbeeManagementTests(unittest.TestCase):
    def setUp(self):
        self.site = manifest()
        self.fleet = ZigbeeFleet(self.site)
        self.gw = self.fleet.gateway("GW01")
        self.fake = FakeClient()
        self.fake.gateway = self.gw
        self.gw._client = self.fake
        self.gw.connected = True
        self.gw.state = "online"
        deliver(self.gw, "zigbee2mqtt/bridge/devices", [discovered()])

    def test_management_functions_bound_to_known_gateway(self):
        self.assertEqual(len(self.gw.devices_snapshot()), 1)
        self.assertEqual(self.gw.by_ieee(IEEE)["friendly_name"], "TH-02")
        self.assertEqual(self.gw.snapshot()["coordinator_port"], 6638)
        self.assertRaises(InvalidRequest, self.fleet.gateway, "GW99")
        self.assertRaises(InvalidRequest, self.gw.by_ieee, "TH-02")

    def test_pairing_restricted_to_short_manual_window(self):
        with self.assertRaises(InvalidRequest):
            self.gw.permit_join(254)
        result = self.gw.permit_join(60)
        self.assertTrue(result["acknowledged"])
        self.assertEqual(self.fake.messages[-1][1]["time"], 60)
        self.assertEqual(self.fake.messages[-1][1]["device"], "coordinator")
        self.gw.permit_join(0)
        self.assertEqual(self.fake.messages[-1][1]["time"], 0)

    def test_settings_allowlist_and_writable_exposes(self):
        names = exposed_names(discovered()["definition"]["exposes"])
        self.assertIn("comfort_temperature_max", names)
        self.assertNotIn("temperature", names)
        with self.assertRaises(InvalidRequest):
            self.gw.set_expose(IEEE, "temperature", 1)
        with self.assertRaises(InvalidRequest):
            self.gw.set_expose(IEEE, "comfort_temperature_max", 10000)
        result = self.gw.set_expose(IEEE, "comfort_temperature_max", 27)
        self.assertTrue(result["sent"])
        self.assertFalse(result["applied"])
        self.assertEqual(self.fake.messages[-1][0], "zigbee2mqtt/TH-02/set")
        self.assertEqual(self.fake.messages[-1][1], {"comfort_temperature_max": 27.0})

    def test_no_arbitrary_MQTT_commands(self):
        for op in ("touchlink/factory_reset", "restart", "converter/save", "device/remove"):
            with self.assertRaises(InvalidRequest):
                self.gw.request(op, {})

    def test_safe_option_requests(self):
        self.gw.set_device_option(IEEE, "debounce", 2)
        self.assertEqual(self.fake.messages[-1][0], "zigbee2mqtt/bridge/request/device/options")
        with self.assertRaises(InvalidRequest):
            self.gw.set_device_option(IEEE, "external_converter", "evil")

    def test_registration_is_review_only_and_no_identity_collision(self):
        # Current pilot device is already in manifest; pretend new sensor discovered.
        second = "0x0000000000000abc"
        deliver(self.gw, "zigbee2mqtt/bridge/devices", [discovered(), discovered(second, "TH-11")])
        plan = self.fleet.registration_plan(
            gateway_id="GW01", ieee_address=second,
            device_id="TH-11", location="2F SMT north"
        )
        self.assertEqual(plan["registration_status"], "REVIEW_ONLY_NOT_IMPORTED")
        self.assertEqual(plan["sensor"]["unit_id"], 2)
        self.assertEqual(plan["ems_device"]["communication"]["modbus_unit_id"], 2)
        self.assertEqual(len(self.fleet.manifest["sensors"]), 1, "No implicit live registry mutation")
        with self.assertRaises(InvalidRequest):
            self.fleet.registration_plan(
                gateway_id="GW01", ieee_address=IEEE,
                device_id="TH-02", location="2F")

    def test_request_timeout_and_mqtt_disconnect_safe(self):
        self.gw.connected = False
        with self.assertRaises(Unavailable):
            self.gw.permit_join(60)
        self.assertFalse(self.gw.snapshot()["mqtt_connected"])

    def test_multiple_gateways_have_distinct_topics(self):
        site = manifest()
        second = copy.deepcopy(site["gateways"][0])
        second.update(id="GW02", coordinator_host="192.168.35.12",
                      mqtt_base_topic="zigbee2mqtt-gw02", z2m_ui_port=8081, modbus_port=1503)
        site["gateways"].append(second)
        sensor = dict(site["sensors"][0])
        sensor.update(device_id="TH-15", ieee_address="0x0000000000000015",
                      friendly_name="TH-15", gateway_id="GW02", unit_id=1)
        site["sensors"].append(sensor)
        fleet = ZigbeeFleet(site)
        self.assertNotEqual(fleet.gateway("GW01").prefix, fleet.gateway("GW02").prefix)
        self.assertNotEqual(fleet.gateway("GW01").gw["modbus_port"], fleet.gateway("GW02").gw["modbus_port"])


if __name__ == "__main__":
    unittest.main()
