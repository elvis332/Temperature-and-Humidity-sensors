import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from src.engine import Engine


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sensor = {'id': 'TH-02', 'topic': 'zigbee2mqtt/TH-02', 'temperature_min': 20,
                       'temperature_max': 28, 'humidity_min': 40, 'humidity_max': 65,
                       'temperature_jump': 2, 'humidity_jump': 10, 'jump_minutes': 10, 'offline_seconds': 60}
        self.engine = Engine({'mode': 'simulation', 'database': str(Path(self.tmp.name)/'test.db'), 'sensors': [self.sensor]})

    def tearDown(self):
        self.engine.db.close()
        self.tmp.cleanup()

    def send(self, temp, humidity):
        return self.engine.record(self.sensor['topic'], json.dumps({
            'temperature': temp, 'humidity': humidity, '_simulated': True}))

    def test_alarm_and_recovery(self):
        self.assertTrue(self.send(24, 52))
        self.assertFalse(self.engine.status()[1])
        self.send(31, 70)
        active = {r[1] for r in self.engine.status()[1]}
        self.assertTrue({'temperature_high', 'humidity_high', 'temperature_jump', 'humidity_jump'} <= active)
        self.send(25, 55)
        self.assertFalse({'temperature_high', 'humidity_high'} & {r[1] for r in self.engine.status()[1]})

    def test_reject_unmarked_and_invalid(self):
        self.assertFalse(self.engine.record(self.sensor['topic'], json.dumps({'temperature': 24, 'humidity': 52})))
        with self.assertRaises(ValueError):
            self.send(24, 105)

    def test_offline_and_recovery(self):
        self.engine.started = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.engine.check_offline()
        self.assertIn('offline', {r[1] for r in self.engine.status()[1]})
        self.send(24, 52)
        self.assertNotIn('offline', {r[1] for r in self.engine.status()[1]})


if __name__ == '__main__':
    unittest.main()
