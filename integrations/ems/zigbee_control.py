"""Sander EMS Zigbee administrator service: isolated Zigbee2MQTT MQTT management.

This module does not import EMS, SQL, or write Zigbee configuration. It must be
mounted behind the existing EMS administrator dependency and EMS audit logger.
Never expose raw broker commands, untrusted URLs, firmware flashing or network resets.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from deploy.site_registry import validate

IEEE_RE = re.compile(r"^0x[0-9a-fA-F]{16}$")
FRIENDLY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
DEVICE_ID_RE = FRIENDLY_RE
# Allowlisted, measured environmental device controls only. No generic
# Zigbee2MQTT option injection, firmware change, group deletion or shell access.
WRITABLE_EXPOSES = {
    "comfort_temperature_min": (-10, 60),
    "comfort_temperature_max": (-10, 60),
    "comfort_humidity_min": (5, 95),
    "comfort_humidity_max": (5, 95),
    "temperature_calibration": (-10, 10),
    "humidity_calibration": (-20, 20),
}
DEFAULT_MAX_JOIN_SECONDS = 60


class ZigbeeControlError(Exception):
    pass


class Unavailable(ZigbeeControlError):
    pass


class InvalidRequest(ZigbeeControlError):
    pass


@dataclass
class _Pending:
    event: threading.Event
    response: dict | None = None


def _read_auth(path: str | None):
    if not path:
        return None
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not config.get("username") or not config.get("password"):
        raise InvalidRequest("Gateway MQTT credentials file requires username and password")
    return config


def exposed_names(features: Any) -> set[str]:
    """Collect writable exposed capability names from bridge/devices descriptions."""
    found = set()
    if isinstance(features, list):
        for feature in features:
            found |= exposed_names(feature)
    elif isinstance(features, dict):
        if isinstance(features.get("name"), str) and (features.get("access", 0) & 2):
            found.add(features["name"])
        found |= exposed_names(features.get("features", []))
    return found


def validate_setting(name: str, value: Any, features: Any) -> float:
    if name not in WRITABLE_EXPOSES:
        raise InvalidRequest("Setting is not approved for EMS management")
    if name not in exposed_names(features):
        raise InvalidRequest("Device does not advertise a writable expose for this setting")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequest("Setting must be numeric")
    import math
    if not math.isfinite(value) or not WRITABLE_EXPOSES[name][0] <= value <= WRITABLE_EXPOSES[name][1]:
        raise InvalidRequest("Setting is outside the permitted range")
    return float(value)


class ZigbeeGateway:
    """One MQTT client per Zigbee2MQTT gateway, listening to cached inventory.

    MQTT client IDs and base topics are distinct for multi-gateway installs.
    Network join, device writes and registration occur only on explicit admin API actions.
    """

    def __init__(self, gw: dict, *, broker="127.0.0.1", port=1883,
                 credentials_file: str | None = None, client_factory=None):
        self.gw = deepcopy(gw)
        self.id = gw["id"]
        self.prefix = gw["mqtt_base_topic"]
        self.broker, self.port = broker, port
        self.connected = False
        self.state = "offline"
        self.bridge_info: dict = {}
        self.devices: dict[str, dict] = {}
        self.events: list[dict] = []
        self._lock = threading.RLock()
        self._pending: dict[str, _Pending] = {}
        self._factory = client_factory or mqtt.Client
        self._auth = _read_auth(credentials_file)
        self._client = None

    def start(self):
        if self._client is not None:
            raise InvalidRequest("Gateway MQTT observer already started")
        client = self._factory(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sander-ems-admin-{self.id}")
        if self._auth:
            client.username_pw_set(self._auth["username"], self._auth["password"])
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client
        client.connect_async(self.broker, self.port, 30)
        client.loop_start()

    def close(self):
        if self._client is not None:
            self._client.disconnect()
            self._client.loop_stop()
            self._client = None
        with self._lock:
            self.connected = False
            self.state = "offline"
            for pending in self._pending.values():
                pending.event.set()

    def _on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            return
        with self._lock:
            self.connected = True
        client.subscribe([
            (f"{self.prefix}/bridge/devices", 1),
            (f"{self.prefix}/bridge/info", 1),
            (f"{self.prefix}/bridge/state", 1),
            (f"{self.prefix}/bridge/event", 1),
            (f"{self.prefix}/bridge/response/+", 1),
        ])

    def _on_disconnect(self, client, userdata, flags, reason, properties):
        with self._lock:
            self.connected = False
            self.state = "offline"
            for pending in self._pending.values():
                pending.event.set()

    def _on_message(self, client, userdata, message):
        try:
            raw = message.payload.decode("utf-8", errors="strict")
            obj = json.loads(raw)
        except (UnicodeError, ValueError):
            if message.topic == f"{self.prefix}/bridge/state":
                obj = raw if "raw" in locals() else ""
            else:
                return
        with self._lock:
            if message.topic == f"{self.prefix}/bridge/devices" and isinstance(obj, list):
                self.devices = {
                    str(device["ieee_address"]).lower(): device
                    for device in obj if isinstance(device, dict) and IEEE_RE.fullmatch(str(device.get("ieee_address", "")))
                }
            elif message.topic == f"{self.prefix}/bridge/info" and isinstance(obj, dict):
                # Never return raw bridge configuration, which may include sensitive data.
                self.bridge_info = {
                    "version": obj.get("version"), "permit_join": obj.get("permit_join"),
                    "restart_required": obj.get("restart_required"),
                    "coordinator": obj.get("coordinator", {}).get("ieee_address")
                    if isinstance(obj.get("coordinator"), dict) else None,
                    "channel": obj.get("network", {}).get("channel")
                    if isinstance(obj.get("network"), dict) else None,
                }
            elif message.topic == f"{self.prefix}/bridge/state":
                self.state = obj.get("state", "offline") if isinstance(obj, dict) else str(obj)
            elif message.topic == f"{self.prefix}/bridge/event" and isinstance(obj, dict):
                self.events.append({"type": obj.get("type"), "data": obj.get("data"), "at": time.time()})
                del self.events[:-100]
            elif message.topic.startswith(f"{self.prefix}/bridge/response/") and isinstance(obj, dict):
                tx = str(obj.get("transaction", ""))
                if tx in self._pending:
                    self._pending[tx].response = obj
                    self._pending[tx].event.set()

    def snapshot(self):
        with self._lock:
            return {
                "gateway_id": self.id, "mqtt_connected": self.connected,
                "zigbee2mqtt_state": self.state, "bridge": deepcopy(self.bridge_info),
                "device_count": len(self.devices),
                "coordinator_host": self.gw["coordinator_host"],
                "coordinator_port": self.gw["coordinator_port"],
                "transport": self.gw.get("coordinator_transport", "ethernet_tcp"),
            }

    def devices_snapshot(self):
        with self._lock:
            # Filter output: only inventory and exposes, never arbitrary vendor blobs.
            return [
                {"ieee_address": ieee, "friendly_name": item.get("friendly_name"),
                 "model_id": item.get("model_id"), "manufacturer": item.get("manufacturer"),
                 "supported": item.get("supported"), "type": item.get("type"),
                 "definition": {
                     "model": (item.get("definition") or {}).get("model"),
                     "exposes": (item.get("definition") or {}).get("exposes", []),
                 }}
                for ieee, item in sorted(self.devices.items())
            ]

    def by_ieee(self, ieee):
        if not isinstance(ieee, str) or not IEEE_RE.fullmatch(ieee):
            raise InvalidRequest("Invalid Zigbee IEEE address")
        with self._lock:
            row = self.devices.get(ieee.lower())
            if row is None:
                raise InvalidRequest("Sensor has not appeared in Zigbee2MQTT discovery")
            return deepcopy(row)

    def request(self, operation: str, payload: dict, timeout=12):
        if operation not in {"permit_join", "health_check", "device/options"}:
            raise InvalidRequest("Disallowed Zigbee management command")
        if self._client is None or not self.connected:
            raise Unavailable("MQTT observer is offline")
        tx = uuid.uuid4().hex
        pending = _Pending(threading.Event())
        with self._lock:
            self._pending[tx] = pending
        try:
            message = json.dumps({**payload, "transaction": tx}, separators=(",", ":"))
            info = self._client.publish(f"{self.prefix}/bridge/request/{operation}", message, qos=1)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise Unavailable("MQTT request could not be published")
            if not pending.event.wait(timeout):
                raise Unavailable("Zigbee2MQTT did not acknowledge the command")
            if pending.response is None:
                raise Unavailable("MQTT disconnected before command acknowledgment")
            if pending.response.get("status") != "ok":
                raise InvalidRequest("Zigbee2MQTT rejected command: " + str(pending.response.get("error", "unknown")))
            return {"acknowledged": True, "data": pending.response.get("data", {})}
        finally:
            with self._lock:
                self._pending.pop(tx, None)

    def permit_join(self, seconds: int):
        if type(seconds) is not int or seconds < 0 or seconds > DEFAULT_MAX_JOIN_SECONDS:
            raise InvalidRequest("Joining must be disabled (0) or enabled for at most 60 seconds")
        return self.request("permit_join", {"time": seconds, "device": "coordinator"})

    def set_device_option(self, ieee: str, option: str, value: Any):
        device = self.by_ieee(ieee)
        if option not in {"debounce", "filtered_optimistic"}:
            raise InvalidRequest("Unsupported Zigbee2MQTT device option")
        if not isinstance(value, bool) and option == "filtered_optimistic":
            raise InvalidRequest("filtered_optimistic must be boolean")
        if option == "debounce" and (type(value) is not int or not 0 <= value <= 10):
            raise InvalidRequest("debounce must be an integer 0–10")
        return self.request("device/options", {"id": device["ieee_address"], "options": {option: value}})

    def set_expose(self, ieee: str, setting: str, value: Any):
        device = self.by_ieee(ieee)
        features = (device.get("definition") or {}).get("exposes", [])
        number = validate_setting(setting, value, features)
        friendly_name = device.get("friendly_name")
        if not isinstance(friendly_name, str) or not FRIENDLY_RE.fullmatch(friendly_name):
            raise InvalidRequest("Unsafe friendly_name; use Zigbee2MQTT Advanced Maintenance")
        if not self.connected or self._client is None:
            raise Unavailable("MQTT observer is offline")
        info = self._client.publish(f"{self.prefix}/{friendly_name}/set",
                                    json.dumps({setting: number}), qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise Unavailable("MQTT publish failed")
        # A publish ACK is not proof that a sleeping battery device applied the value.
        return {"sent": True, "applied": False, "verification": "Wake the battery sensor and confirm next reported value"}


class ZigbeeFleet:
    """Immutable gateway inventory plus per-gateway MQTT observers."""
    def __init__(self, manifest: dict, *, credentials: dict | None = None,
                 client_factory=None, broker="127.0.0.1"):
        validate(manifest)
        self.manifest = deepcopy(manifest)
        self.gateways = {
            gw["id"]: ZigbeeGateway(gw, credentials_file=(credentials or {}).get(gw["id"]),
                                    client_factory=client_factory, broker=broker)
            for gw in manifest["gateways"]
        }

    def start(self):
        for gw in self.gateways.values():
            gw.start()

    def close(self):
        for gw in self.gateways.values():
            gw.close()

    def gateway(self, gateway_id):
        if gateway_id not in self.gateways:
            raise InvalidRequest("Unknown gateway")
        return self.gateways[gateway_id]

    def registration_plan(self, *, gateway_id: str, ieee_address: str,
                          device_id: str, location: str):
        if not DEVICE_ID_RE.fullmatch(device_id or ""):
            raise InvalidRequest("Invalid EMS device_id")
        if not isinstance(location, str) or not location.strip() or len(location) > 200:
            raise InvalidRequest("Exact physical location is required")
        gw = self.gateway(gateway_id)
        discovered = gw.by_ieee(ieee_address)
        model = (discovered.get("definition") or {}).get("model") or discovered.get("model_id")
        if model != "SNZB-02D":
            raise InvalidRequest("Only the validated SNZB-02D model is supported by the current telemetry profile")
        existing = self.manifest["sensors"]
        if any(s["device_id"] == device_id for s in existing):
            raise InvalidRequest("EMS device ID already registered")
        if any(s["ieee_address"].lower() == ieee_address.lower() for s in existing):
            raise InvalidRequest("IEEE already registered; re-registration would split history")
        reserved = {s["unit_id"] for s in existing if s["gateway_id"] == gateway_id}
        unit = next((n for n in range(1, 248) if n not in reserved), None)
        if unit is None:
            raise InvalidRequest("Gateway bridge has no free Modbus unit IDs")
        sensor = {
            "device_id": device_id, "ieee_address": ieee_address.lower(),
            "friendly_name": discovered["friendly_name"], "location": location.strip(),
            "gateway_id": gateway_id, "unit_id": unit, "offline_seconds": 900
        }
        proposal = deepcopy(self.manifest)
        proposal["sensors"].append(sensor)
        validate(proposal)
        return {
            "registration_status": "REVIEW_ONLY_NOT_IMPORTED",
            "sensor": sensor,
            "ems_device": {
                "device": {"id": device_id},
                "communication": {
                    "mode": "modbus_tcp", "ip_address": "127.0.0.1",
                    "port": gw.gw["modbus_port"], "modbus_unit_id": unit,
                },
                "profile_id": "SNZB02D"
            },
            "next_site_manifest": proposal,
            "warning": "Requires approved EMS Devices API registration, configuration rollout, and audit. No SQL writes made."
        }
