"""Test against isolated local Mosquitto at 127.0.0.1:1883."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
import paho.mqtt.publish as publish
from bridge.probe import read

class MQTTIntegration(unittest.TestCase):
    def test_end_to_end(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        topic = "sander-test/ci-" + uuid.uuid4().hex
        cfg = {"mqtt_host": "127.0.0.1", "mqtt_port": 1883, "client_id": topic.replace("/", "-"),
               "modbus_host": "127.0.0.1", "modbus_port": port,
               "sensors": [{"unit_id": 1, "topic": topic, "offline_seconds": 2}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            proc = subprocess.Popen([sys.executable, "-m", "bridge.bridge"],
                                    env={**os.environ, "BRIDGE_CONFIG": str(path)})
            try:
                payload = json.dumps({"temperature": -2.5, "humidity": 61.2, "battery": 20,
                                      "linkquality": 180, "_simulated": True})
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    publish.single(topic, payload, hostname="127.0.0.1", qos=1)
                    try:
                        actual = read(port=port)
                        break
                    except (OSError, RuntimeError):
                        time.sleep(0.25)
                else:
                    self.fail("Bridge did not receive MQTT data")
                self.assertEqual(actual, {"temperature_c": -2.5, "humidity_pct": 61.2, "battery_pct": 20, "lqi": 180})
                time.sleep(2.3)
                with self.assertRaisesRegex(RuntimeError, "0x0b"):
                    read(port=port)
                publish.single(topic, payload, hostname="127.0.0.1", qos=1)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        self.assertEqual(read(port=port), actual)
                        break
                    except RuntimeError:
                        time.sleep(0.1)
                else:
                    self.fail("Bridge did not recover")
            finally:
                proc.terminate()
                proc.wait(timeout=10)
