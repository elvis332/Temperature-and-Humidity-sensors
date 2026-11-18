"""HTTP integration tests: all routes require the existing EMS admin guard.

No live broker, local EMS .env, collector, SQL or site hardware is used.
"""
import unittest
from pathlib import Path
import json
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from integrations.ems.zigbee_api import create_admin_router
from integrations.ems.zigbee_control import ZigbeeFleet
from integrations.ems.test_zigbee_control import FakeClient, deliver, discovered, IEEE


ROOT = Path(__file__).resolve().parents[2]


class EMSAdminApiTests(unittest.TestCase):
    def setUp(self):
        manifest = json.loads((ROOT / "deploy/site-manifest.example.json").read_text(encoding="utf-8"))
        self.fleet = ZigbeeFleet(manifest)
        gw = self.fleet.gateway("GW01")
        gw._client = FakeClient()
        gw._client.gateway = gw
        gw.connected = True
        gw.state = "online"
        deliver(gw, "zigbee2mqtt/bridge/devices", [discovered()])
        self.audits = []

        def require_admin(request: Request):
            if request.headers.get("x-test-ems-admin") != "allowed":
                raise HTTPException(status_code=403, detail="Administrator required")
            return {"id": "test_admin"}

        app = FastAPI()
        app.include_router(create_admin_router(
            self.fleet, require_ems_admin=require_admin,
            audit_change=lambda record: self.audits.append(record)
        ), prefix="/api")
        self.client = TestClient(app)
        self.headers = {"x-test-ems-admin": "allowed"}

    def test_non_admin_cannot_discover_or_open_pairing(self):
        self.assertEqual(self.client.get("/api/admin/zigbee/gateways").status_code, 403)
        self.assertEqual(self.client.post("/api/admin/zigbee/gateways/GW01/permit-join",
                                          json={"seconds": 60}).status_code, 403)
        self.assertEqual(len(self.audits), 0)

    def test_administrator_discovery_and_registration_proposal(self):
        response = self.client.get("/api/admin/zigbee/gateways/GW01/devices",
                                   headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["ieee_address"], IEEE)
        caps = self.client.get("/api/admin/zigbee/capabilities", headers=self.headers).json()
        self.assertFalse(caps["registration_commit_enabled"])
        result = self.client.post("/api/admin/zigbee/registration/plan", headers=self.headers,
                                  json={"gateway_id": "GW01", "ieee_address": IEEE,
                                        "device_id": "TH-02", "location": "2F"})
        self.assertEqual(result.status_code, 422)  # already registered identity
        response = self.client.post("/api/admin/zigbee/registration/commit",
                                    headers=self.headers,
                                    json={"gateway_id":"GW01", "ieee_address":IEEE,
                                          "device_id":"TH-02", "location":"2F"})
        self.assertEqual(response.status_code, 501)
        self.assertFalse(self.audits)

    def test_bounded_join_and_admin_audit(self):
        response = self.client.post("/api/admin/zigbee/gateways/GW01/permit-join",
                                    headers=self.headers, json={"seconds": 60})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["acknowledged"])
        self.assertEqual(self.audits[0]["action"], "zigbee.permit_join.requested")
        self.assertEqual(self.audits[-1]["action"], "zigbee.permit_join.acknowledged")
        self.assertEqual(self.client.post("/api/admin/zigbee/gateways/GW01/permit-join",
                           headers=self.headers, json={"seconds": 254}).status_code, 422)

    def test_injected_registration_transaction_commits_once_without_real_sql(self):
        gw = self.fleet.gateway("GW01")
        other = "0x0000000000000abc"
        deliver(gw, "zigbee2mqtt/bridge/devices", [discovered(), discovered(other, "TH-11")])
        operations = []
        def admin(request: Request):
            return {"id": "staging-admin"}
        def fake_ems_transaction(plan, user):
            operations.append(plan["sensor"]["device_id"])
            return {"committed": True, "staging_mock": True}
        app = FastAPI()
        app.include_router(create_admin_router(
            self.fleet, require_ems_admin=admin, audit_change=lambda event: self.audits.append(event),
            register_transaction=fake_ems_transaction), prefix="/api")
        body = {"gateway_id": "GW01", "ieee_address": other,
                "device_id": "TH-11", "location": "2F SMT"}
        with TestClient(app) as client:
            result = client.post("/api/admin/zigbee/registration/commit", json=body)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json()["committed"])
            repeated = client.post("/api/admin/zigbee/registration/commit", json=body)
            self.assertEqual(repeated.status_code, 422)
        self.assertEqual(operations, ["TH-11"])
        self.assertEqual(len(self.fleet.manifest["sensors"]), 2)

    def test_network_proposal_is_not_an_ip_write(self):
        result = self.client.post("/api/admin/zigbee/gateways/GW01/network/propose",
                                  headers=self.headers,
                                  json={"coordinator_host":"192.168.35.55",
                                        "coordinator_port":6638,
                                        "coordinator_transport":"ethernet_tcp"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "REVIEW_ONLY_NO_LIVE_NETWORK_CHANGE")
        self.assertEqual(self.fleet.gateway("GW01").gw["coordinator_host"], "192.168.35.11")
        bad = self.client.post("/api/admin/zigbee/gateways/GW01/network/propose",
                               headers=self.headers, json={"coordinator_host":"8.8.8.8",
                                  "coordinator_port":6638, "coordinator_transport":"ethernet_tcp"})
        self.assertEqual(bad.status_code, 422)

    def test_native_ui_link_requires_admin_and_approved_same_origin_path(self):
        self.assertEqual(self.client.get("/api/admin/zigbee/gateways/GW01/advanced").status_code, 403)
        response = self.client.get("/api/admin/zigbee/gateways/GW01/advanced", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["configured"])
        def admin():
            return {"id": "admin"}
        with self.assertRaises(ValueError):
            create_admin_router(self.fleet, require_ems_admin=admin, audit_change=lambda _: None,
                                native_proxy_paths={"GW01": "http://192.168.50.20:8080/"})

    def test_async_audit_adapter_is_rejected_without_sending_mqtt(self):
        gw = self.fleet.gateway("GW01")
        before = len(gw._client.messages)
        def admin(request: Request):
            return {"id": "admin"}
        async def unsupported_async_audit(event):
            return None
        app = FastAPI()
        app.include_router(create_admin_router(
            self.fleet, require_ems_admin=admin,
            audit_change=unsupported_async_audit), prefix="/api")
        with TestClient(app) as client:
            response = client.post("/api/admin/zigbee/gateways/GW01/permit-join",
                                   json={"seconds":60})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(gw._client.messages), before)

    def test_audit_failure_blocks_mqtt_commands(self):
        gw = self.fleet.gateway("GW01")
        before = len(gw._client.messages)
        def admin(request: Request):
            return {"id": "admin"}
        def bad_audit(record):
            raise RuntimeError("audit storage unavailable")
        app = FastAPI()
        app.include_router(create_admin_router(self.fleet, require_ems_admin=admin,
                                                audit_change=bad_audit), prefix="/api")
        with TestClient(app) as client:
            result = client.post("/api/admin/zigbee/gateways/GW01/permit-join",
                                 json={"seconds": 60})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(len(gw._client.messages), before)


if __name__ == "__main__":
    unittest.main()
