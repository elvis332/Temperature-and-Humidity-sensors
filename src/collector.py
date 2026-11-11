"""Run from repository root: python -m src.collector [--ems]."""
import argparse
import json
import os
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from .engine import Engine


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ems', action='store_true')
    args = ap.parse_args()
    cfg = json.loads(Path('config.json').read_text(encoding='utf-8'))
    if args.ems and cfg['mode'] == 'simulation':
        raise SystemExit('Simulation cannot enter the EMS historian. Commission live hardware first.')
    engine = Engine(cfg)
    sink = None
    if args.ems:
        from .ems_sink import EMSSink
        sink = EMSSink()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='sander-zigbee-collector')
    if os.getenv('MQTT_USER'):
        client.username_pw_set(os.environ['MQTT_USER'], os.getenv('MQTT_PASSWORD', ''))

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print('MQTT connection failed:', reason_code)
            return
        for sensor in cfg['sensors']:
            client.subscribe(sensor['topic'], qos=1)
        print('Connected, monitoring', len(cfg['sensors']), 'sensors', flush=True)

    def on_message(client, userdata, msg):
        if msg.retain:
            return  # Replayed retained values are not new measurements.
        try:
            if engine.record(msg.topic, msg.payload):
                if sink:
                    sink.ingest(msg.topic, msg.payload, cfg['sensors'])
                print('Stored:', msg.topic, flush=True)
        except (ValueError, json.JSONDecodeError) as exc:
            print('Rejected:', msg.topic, exc, flush=True)
        except Exception as exc:
            print('Storage/EMS error:', msg.topic, exc, flush=True)

    client.on_connect, client.on_message = on_connect, on_message

    def watchdog():
        while True:
            time.sleep(5)
            engine.check_offline()

    threading.Thread(target=watchdog, daemon=True).start()
    client.connect(os.getenv('MQTT_HOST', cfg['mqtt_host']), cfg['mqtt_port'], keepalive=60)
    client.loop_forever(retry_first_connection=True)


if __name__ == '__main__':
    main()
