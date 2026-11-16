import json
import threading
import time
import unittest
from bridge.bridge import Cache, Handler, Server
from bridge.probe import read

class TestBridge(unittest.TestCase):
    def setUp(self):
        self.cache = Cache([{"unit_id": 1, "topic": "sander-test/TH-02", "offline_seconds": 1}])
        self.cache.connection(True)
        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.cache = self.cache
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
    def send(self, retained=False):
        self.cache.update("sander-test/TH-02", json.dumps({"temperature": -2.5, "humidity": 61.2,
                          "battery": 85, "linkquality": 180}), retained)
    def probe(self):
        return read(port=self.server.server_address[1])
    def test_registers(self):
        self.send()
        self.assertEqual(self.probe(), {"temperature_c": -2.5, "humidity_pct": 61.2, "battery_pct": 85, "lqi": 180})
    def test_offline_and_recovery(self):
        self.send()
        self.cache.seen[1] = time.time()-2
        with self.assertRaisesRegex(RuntimeError, "0x0b"):
            self.probe()
        self.send()
        self.assertEqual(self.probe()["battery_pct"], 85)
    def test_retained_and_disconnect(self):
        self.send(True)
        with self.assertRaises(RuntimeError):
            self.probe()
        self.send()
        self.cache.connection(False)
        with self.assertRaises(RuntimeError):
            self.probe()

if __name__ == "__main__":
    unittest.main()
