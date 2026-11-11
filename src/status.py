"""Print current readings and unresolved alerts from the development database."""
import json
from pathlib import Path
from .engine import Engine

if __name__ == '__main__':
    engine = Engine(json.loads(Path('config.json').read_text(encoding='utf-8')))
    readings, alerts = engine.status()
    print('SENSORS (device, timestamp, mode, temperature, humidity, battery)')
    for row in readings:
        print(*row)
    print('ACTIVE ALERTS (device, rule, opened, detail)')
    for row in alerts:
        print(*row)
