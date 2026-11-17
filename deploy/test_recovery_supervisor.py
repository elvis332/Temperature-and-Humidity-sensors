"""Unit tests for production recovery logic; never manipulate Windows services."""
import json
import tempfile
import unittest
from pathlib import Path

from deploy.recovery_supervisor import Freshness, choose_action, load_config


class Decisions(unittest.TestCase):
    def test_restart_only_after_repeated_unhealthy_checks(self):
        self.assertIsNone(choose_action(upstream=True, port_ready=False, service="RUNNING",
                                        failures=3, threshold=4, elapsed=900))
        self.assertEqual("restart", choose_action(upstream=True, port_ready=False,
                                                  service="RUNNING", failures=4,
                                                  threshold=4, elapsed=900))

    def test_start_stopped_service_after_two_checks(self):
        self.assertEqual("start", choose_action(upstream=True, port_ready=False,
                                                service="STOPPED", failures=2,
                                                threshold=4, elapsed=900))
        self.assertIsNone(choose_action(upstream=True, port_ready=False,
                                        service="STOPPED", failures=1,
                                        threshold=4, elapsed=900))

    def test_never_restart_without_upstream_or_during_cooldown(self):
        for upstream, ready, elapsed in ((False, False, 900),
                                         (True, True, 900),
                                         (True, False, -1)):
            self.assertIsNone(choose_action(upstream=upstream, port_ready=ready,
                                            service="RUNNING", failures=20,
                                            threshold=4, elapsed=elapsed))

    def test_nonservice_process_must_not_be_restarted(self):
        self.assertIsNone(choose_action(upstream=True, port_ready=False,
                                        service="MISSING", failures=30,
                                        threshold=4, elapsed=900))


class Messages(unittest.TestCase):
    def test_fresh_and_stale(self):
        clock = lambda: 100000.0
        cache = Freshness([{"topic": "zigbee2mqtt/TH-02", "offline_seconds": 900}], clock)
        valid = json.dumps({"last_seen": "1970-01-02T03:46:30+00:00"})
        self.assertTrue(cache.update("zigbee2mqtt/TH-02", valid))
        self.assertEqual(cache.states()["zigbee2mqtt/TH-02"], "ONLINE")
        self.assertFalse(cache.update("zigbee2mqtt/TH-02", valid))
        self.assertFalse(cache.update("zigbee2mqtt/TH-02", valid, retained=True))
        self.assertFalse(cache.update("zigbee2mqtt/other", valid))
        old = json.dumps({"last_seen": "1970-01-01T00:00:00+00:00"})
        self.assertFalse(cache.update("zigbee2mqtt/TH-02", old))

    def test_no_timestamp_cannot_claim_online(self):
        cache = Freshness([{"topic": "zigbee2mqtt/TH-02", "offline_seconds": 900}])
        self.assertFalse(cache.update("zigbee2mqtt/TH-02", '{"temperature":25}'))
        self.assertEqual(cache.states()["zigbee2mqtt/TH-02"], "NO_FRESH_REPORT")


class Configuration(unittest.TestCase):
    def test_loopback_guard_and_timeouts(self):
        p = Path(__file__).resolve().parent / "recovery.example.json"
        original = json.loads(p.read_text())
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "config.json"
            target.write_text(json.dumps(original))
            self.assertEqual(load_config(target)["sensors"][0]["offline_seconds"], 900)
            original["bridge_host"] = "192.168.21.12"
            target.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                load_config(target)


if __name__ == "__main__":
    unittest.main()
