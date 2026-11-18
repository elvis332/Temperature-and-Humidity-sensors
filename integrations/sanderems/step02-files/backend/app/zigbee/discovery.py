"""MQTT management observer. Not a Zigbee network coordinator or EMS collector.

Sensor telemetry continues in the separately installed Zigbee2MQTT/bridge services.
Never connect unless the Zigbee integration is explicitly enabled.
"""
import json
import os
import threading
from pathlib import Path


class ObserverError(Exception):
    pass


class Observer:
    def __init__(self, gateway, broker, port, credentials_file=None, client_factory=None):
        self.gateway = gateway
        self.prefix = gateway["mqtt_base_topic"]
        self.connected = False
        self.state = "offline"
        self.devices = {}
        self.lock = threading.RLock()
        self.client = None
        self.broker, self.port = broker, port
        self.credentials_file = credentials_file
        self.client_factory = client_factory

    def start(self):
        if self.client is not None:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise ObserverError("paho-mqtt missing; ask IT to install verified offline wheel") from exc
        factory = self.client_factory or mqtt.Client
        client = factory(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="sander-ems-" + self.gateway["id"])
        if self.credentials_file:
            values = json.loads(Path(self.credentials_file).read_text(encoding="utf-8"))
            if not values.get("username") or not values.get("password"):
                raise ObserverError("Invalid protected MQTT credentials")
            client.username_pw_set(values["username"], values["password"])
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(self.broker, self.port, 30)
        client.loop_start()
        self.client = client

    def close(self):
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
            self.client = None
        with self.lock:
            self.connected = False
            self.state = "offline"

    def _on_connect(self, client, userdata, flags, reason, props):
        if reason.is_failure:
            return
        with self.lock:
            self.connected = True
        client.subscribe([(self.prefix + "/bridge/" + part, 1) for part in
                          ("devices", "state")])

    def _on_disconnect(self, client, userdata, flags, reason, props):
        with self.lock:
            self.connected = False
            self.state = "offline"

    def _on_message(self, client, userdata, message):
        try:
            raw = message.payload.decode("utf-8")
            value = json.loads(raw)
        except (UnicodeError, ValueError):
            if message.topic != self.prefix + "/bridge/state":
                return
            value = raw
        with self.lock:
            if message.topic == self.prefix + "/bridge/devices" and isinstance(value, list):
                self.devices = {d["ieee_address"].lower(): d for d in value
                                if isinstance(d, dict) and isinstance(d.get("ieee_address"), str)}
            elif message.topic == self.prefix + "/bridge/state":
                self.state = value.get("state", "offline") if isinstance(value, dict) else str(value)

    def status(self):
        with self.lock:
            return {"gateway_id": self.gateway["id"], "mqtt_connected": self.connected,
                    "zigbee2mqtt_state": self.state, "device_count": len(self.devices),
                    "coordinator_host": self.gateway["coordinator_host"],
                    "coordinator_port": self.gateway["coordinator_port"]}

    def discovered(self):
        with self.lock:
            return [{"ieee_address": ieee,
                     "friendly_name": v.get("friendly_name") if isinstance(v.get("friendly_name"), str) else "",
                     "model": ((v.get("definition") if isinstance(v.get("definition"), dict) else {})
                               .get("model") or v.get("model_id") or "")}
                    for ieee, v in sorted(self.devices.items())][:256]
