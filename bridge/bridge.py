"""Read-only MQTT -> Modbus TCP. No EMS/SQL imports."""
import json
import logging
import math
import os
import socketserver
import struct
import threading
import time
from datetime import datetime
from pathlib import Path

FIELDS = ("temperature", "humidity", "battery", "linkquality")
LIMITS = ((-40, 80), (0, 100), (0, 100), (0, 255))


class Cache:
    def __init__(self, sensors):
        self.sensors = {s["unit_id"]: s for s in sensors}
        self.topics = {s["topic"]: s["unit_id"] for s in sensors}
        if len(self.sensors) != len(sensors) or len(self.topics) != len(sensors):
            raise ValueError("Duplicate unit ID or MQTT topic")
        if any(not 1 <= s["unit_id"] <= 247 or s["offline_seconds"] <= 0 for s in sensors):
            raise ValueError("Invalid unit ID or offline timeout")
        self.values, self.seen = {}, {}
        self.lock = threading.Lock()
        self.connected = False

    def connection(self, online):
        with self.lock:
            self.connected = online
            if not online:
                self.values.clear()
                self.seen.clear()

    def update(self, topic, payload, retained=False):
        unit = self.topics.get(topic)
        if unit is None or retained:
            return
        obj = json.loads(payload)
        if not isinstance(obj, dict):
            raise ValueError("Expected JSON object")
        # Reject simulated messages on real sensor topics.
        if obj.get("_simulated") and not topic.startswith("sander-test/"):
            return
        parsed = {}
        for i, key in enumerate(FIELDS):
            if key not in obj or obj[key] is None:
                continue
            value = obj[key]
            low, high = LIMITS[i]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Invalid {key}: {value!r}")
            parsed[i] = round(value * (10 if i < 2 else 1)) & 0xffff
        if not parsed:
            return
        # Require Zigbee2MQTT last_seen in production: cached/replayed reports
        # must not extend freshness. Test topics use the receipt time.
        now = time.time()
        stamp = obj.get("last_seen")
        if stamp:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("last_seen must include timezone")
            now = dt.timestamp()
            if now > time.time() + 5:
                raise ValueError("Future last_seen")
        elif not topic.startswith("sander-test/"):
            return
        with self.lock:
            if not self.connected or now <= self.seen.get(unit, 0):
                return
            self.values.setdefault(unit, {}).update(parsed)
            self.seen[unit] = now

    def read(self, unit, start, count):
        with self.lock:
            if unit not in self.sensors:
                return 0x0b, ()
            if count < 1 or start + count > 4:
                return 0x02, ()
            if not self.connected or time.time() - self.seen.get(unit, 0) > self.sensors[unit]["offline_seconds"]:
                return 0x0b, ()
            data = self.values.get(unit, {})
            if any(i not in data for i in range(start, start + count)):
                return 0x0b, ()
            return 0, tuple(data[i] for i in range(start, start + count))


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(30)
        try:
            while True:
                header = self.rfile.read(7)
                if len(header) != 7:
                    return
                tid, protocol, length, unit = struct.unpack(">HHHB", header)
                if protocol != 0 or not 2 <= length <= 254:
                    return
                pdu = self.rfile.read(length - 1)
                if len(pdu) != length - 1:
                    return
                fc = pdu[0]
                if fc != 3:
                    reply = bytes((fc | 0x80, 1))
                elif len(pdu) != 5:
                    reply = b"\x83\x03"
                else:
                    start, count = struct.unpack(">HH", pdu[1:])
                    error, values = self.server.cache.read(unit, start, count)
                    reply = bytes((0x83, error)) if error else bytes((3, len(values)*2)) + struct.pack(">" + "H"*len(values), *values)
                self.wfile.write(struct.pack(">HHHB", tid, 0, len(reply)+1, unit) + reply)
        except (OSError, TimeoutError):
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    import paho.mqtt.client as mqtt
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = json.loads(Path(os.getenv("BRIDGE_CONFIG", "bridge/config.test.json")).read_text(encoding="utf-8"))
    cache = Cache(cfg["sensors"])
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg["client_id"])
    if os.getenv("MQTT_USER"):
        client.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
    if cfg.get("mqtt_tls"):
        client.tls_set(ca_certs=cfg.get("mqtt_ca"))
    def connected(c, _, flags, reason, properties):
        cache.connection(not reason.is_failure)
        if not reason.is_failure:
            c.subscribe([(topic, 1) for topic in cache.topics])
            logging.info("MQTT connected; monitoring %s", list(cache.topics))
    def disconnected(c, _, flags, reason, properties):
        cache.connection(False)
    def message(c, _, msg):
        try:
            cache.update(msg.topic, msg.payload, msg.retain)
        except (ValueError, TypeError, OverflowError) as exc:
            logging.warning("Rejected %s: %s", msg.topic, exc)
    client.on_connect, client.on_disconnect, client.on_message = connected, disconnected, message
    client.connect_async(cfg["mqtt_host"], cfg["mqtt_port"], 30)
    client.loop_start()
    try:
        with Server((cfg["modbus_host"], cfg["modbus_port"]), Handler) as server:
            server.cache = cache
            logging.info("Read-only FC03 bridge listening on %s", server.server_address)
            server.serve_forever()
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
