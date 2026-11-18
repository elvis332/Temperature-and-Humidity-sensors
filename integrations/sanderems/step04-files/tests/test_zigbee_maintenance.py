import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from backend.app.zigbee.discovery import Observer, ObserverError
from backend.app.zigbee.maintenance import (
    audit_event, enforce_admin_write, execute_audited,
    maintenance_state, validate_option,
)


class FakeMessage:
    def __init__(self, topic, data):
        self.topic = topic
        self.payload = json.dumps(data).encode()


class FakeClient:
    def __init__(self, observer, response_status="ok", mismatched=False):
        self.observer = observer
        self.response_status = response_status
        self.mismatched = mismatched
        self.calls = []

    def publish(self, topic, body, qos, retain):
        self.calls.append((topic, json.loads(body), qos, retain))
        op = topic.split("/bridge/request/")[-1]
        transaction = "unknown" if self.mismatched else json.loads(body)["transaction"]
        self.observer._on_message(self, None, FakeMessage(
            self.observer.prefix + "/bridge/response/" + op,
            {"transaction": transaction, "status": self.response_status, "data": {}}
        ))
        return SimpleNamespace(rc=0)


class TestMaintenance(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def ready_env(self, audit_path):
        os.environ.update({
            "EMS_ZIGBEE_MAINTENANCE_ENABLED": "true",
            "EMS_ZIGBEE_MAINTENANCE_AUDIT_PATH": str(audit_path),
            "EMS_ZIGBEE_WRITE_ORIGINS": "https://ems.sander.example",
        })

    def test_locked_by_default(self):
        self.assertFalse(maintenance_state()["enabled"])
        with self.assertRaises(HTTPException) as ctx:
            enforce_admin_write(SimpleNamespace(headers={"origin": "https://ems.sander.example"}))
        self.assertEqual(ctx.exception.status_code, 503)

    def test_origin_required(self):
        with tempfile.TemporaryDirectory() as directory:
            self.ready_env(Path(directory) / "audit.jsonl")
            for origin in ("", "https://untrusted.invalid"):
                with self.assertRaises(HTTPException) as ctx:
                    enforce_admin_write(SimpleNamespace(headers={"origin": origin}))
                self.assertEqual(ctx.exception.status_code, 403)

    def test_settings_separately_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            self.ready_env(Path(directory) / "audit.jsonl")
            request = SimpleNamespace(headers={"origin": "https://ems.sander.example"})
            enforce_admin_write(request)
            with self.assertRaises(HTTPException):
                enforce_admin_write(request, settings=True)

    def test_calibration_allowlist_and_bounds(self):
        self.assertEqual(validate_option("temperature_calibration", 3), 3.0)
        self.assertEqual(validate_option("humidity_calibration", -50), -50.0)
        for key, value in (("dangerous_topic", 1), ("temperature_calibration", 60),
                           ("temperature_calibration", float("nan")),
                           ("temperature_calibration", True)):
            with self.assertRaises(ValueError):
                validate_option(key, value)

    def test_transaction_correlated_not_retained(self):
        observer = Observer({"id": "z1", "mqtt_base_topic": "z2m_z1", "coordinator_host": "192.168.1.5", "coordinator_port": 6638}, "127.0.0.1", 1883)
        observer.connected = True
        observer.state = "online"
        observer.client = FakeClient(observer)
        response = observer.request("permit_join", {"time": 60}, timeout=0.25)
        self.assertEqual(response["status"], "ok")
        self.assertFalse(observer.pending)
        topic, body, qos, retained = observer.client.calls[0]
        self.assertEqual(topic, "z2m_z1/bridge/request/permit_join")
        self.assertEqual(body["time"], 60)
        self.assertEqual(qos, 1)
        self.assertFalse(retained)

    def test_ignore_unmatched_response(self):
        observer = Observer({"id": "z1", "mqtt_base_topic": "z2m_z1", "coordinator_host": "192.168.1.5", "coordinator_port": 6638}, "127.0.0.1", 1883)
        observer.connected = True
        observer.state = "online"
        observer.client = FakeClient(observer, mismatched=True)
        with self.assertRaises(ObserverError):
            observer.request("permit_join", {"time": 60}, timeout=0.03)
        self.assertFalse(observer.pending)

    def test_audit_written_before_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            self.ready_env(path)
            class ObserverWithAuditCheck:
                def request(self, operation, payload):
                    entries = [json.loads(row) for row in path.read_text().splitlines()]
                    assert entries[0]["status"] == "requested"
                    assert entries[0]["user"] == "valen"
                    return {"status": "ok"}
            res = execute_audited(ObserverWithAuditCheck(), "valen", "gateway_a", "pair_60s",
                                  {"seconds": 60}, "permit_join", {"time": 60})
            entries = [json.loads(row) for row in path.read_text().splitlines()]
            self.assertEqual([r["status"] for r in entries], ["requested", "acknowledged"])
            self.assertEqual(entries[0]["event_id"], entries[1]["event_id"])
            self.assertTrue(res["accepted"])

    def test_missing_audit_prevents_publish(self):
        class NoPublish:
            def request(self, operation, payload):
                raise AssertionError("Must not publish")
        with self.assertRaises(HTTPException) as ctx:
            execute_audited(NoPublish(), "valen", "gw", "pair_60s", {}, "permit_join", {"time": 60})
        self.assertEqual(ctx.exception.status_code, 503)

    def test_failed_response_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            self.ready_env(path)
            class Rejected:
                def request(self, operation, payload):
                    return {"status": "error"}
            with self.assertRaises(HTTPException) as ctx:
                execute_audited(Rejected(), "valen", "gw", "sensor_option", {}, "device/options", {})
            self.assertEqual(ctx.exception.status_code, 502)
            statuses = [json.loads(row)["status"] for row in path.read_text().splitlines()]
            self.assertEqual(statuses, ["requested", "rejected"])


if __name__ == "__main__":
    unittest.main()
