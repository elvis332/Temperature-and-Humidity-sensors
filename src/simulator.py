"""Send synthetic Zigbee2MQTT-format payloads, including alarms and an offline sensor."""
import json
import os
import time
from pathlib import Path
import paho.mqtt.client as mqtt


def main():
    cfg = json.loads(Path('config.json').read_text(encoding='utf-8'))
    if cfg['mode'] != 'simulation':
        raise SystemExit('Simulator disabled outside simulation mode')
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(os.getenv('MQTT_HOST', cfg['mqtt_host']), cfg['mqtt_port'])
    client.loop_start()
    for step in range(20):
        for i, sensor in enumerate(cfg['sensors']):
            if i == 1 and step >= 8:
                continue  # Provoke no-data/offline warning.
            high = i == 0 and 4 <= step < 8
            payload = {'temperature': 30 if high else 24, 'humidity': 69 if high else 52,
                       'battery': 90, '_simulated': True}
            client.publish(sensor['topic'], json.dumps(payload), qos=1).wait_for_publish()
        print('Published simulation step', step, flush=True)
        time.sleep(5)
    client.disconnect()
    client.loop_stop()


if __name__ == '__main__':
    main()
