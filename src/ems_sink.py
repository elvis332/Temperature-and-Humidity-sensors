"""Optional live-only adapter using the existing Sander EMS ingestion path."""
from datetime import datetime
from zoneinfo import ZoneInfo
from backend.app.core.config_loader import load_ems_configuration
from backend.app.telemetry.ingestion import IngestionService
from .engine import decode


class EMSSink:
    def __init__(self):
        self.ingestion = IngestionService(load_ems_configuration())

    def ingest(self, topic, payload, sensors):
        result = decode(topic, payload, sensors, 'live')
        if not result:
            return
        sensor, values = result
        points = [
            {'key': key, 'value': values[field], 'unit': unit, 'quality': 'GOOD'}
            for key, field, unit in (
                ('temperature_c', 'temperature', '°C'),
                ('humidity_pct', 'humidity', '%RH'),
                ('battery_pct', 'battery', '%'),
            ) if field in values
        ]
        return self.ingestion.ingest({
            'schema_version': '1.0',
            'device_id': sensor['id'],
            'timestamp': datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),
            'source': 'MQTT_ZIGBEE',
            'quality': 'GOOD',
            'points': points,
        })
