"""Send one synthetic MQTT report to the isolated test namespace."""
import json
import os
import paho.mqtt.publish as publish

if __name__ == "__main__":
    publish.single("sander-test/TH-02", json.dumps({"temperature": -2.5, "humidity": 61.2,
                   "battery": 85, "linkquality": 180, "_simulated": True}),
                   hostname=os.getenv("MQTT_HOST", "127.0.0.1"), port=1883, qos=1)
