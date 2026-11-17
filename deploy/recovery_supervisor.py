"""Production-safe Zigbee software supervisor for approved Windows services.

This process never pairs, resets, flashes, or changes a coordinator, sensor, or EMS.
It never directly launches node.exe: Service Control Manager owns process lifecycle.
"""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from urllib.request import urlopen

import paho.mqtt.client as mqtt

LOG = logging.getLogger("sander.zigbee.recovery")
SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("mqtt_host", "z2m_host", "bridge_host"):
        if config[key] not in LOOPBACK:
            raise ValueError(f"{key} must be loopback for the one-server deployment")
    for key in ("z2m_service", "bridge_service"):
        if not SERVICE_NAME.fullmatch(config[key]):
            raise ValueError(f"Unsafe Windows service name: {key}")
    for key in ("mqtt_port", "coordinator_port", "z2m_port", "bridge_port"):
        if not isinstance(config[key], int) or not 1 <= config[key] <= 65535:
            raise ValueError(f"Invalid {key}")
    for key, minimum in (("check_interval_seconds", 5),
                         ("failures_before_action", 2),
                         ("restart_cooldown_seconds", 60)):
        if not isinstance(config[key], int) or config[key] < minimum:
            raise ValueError(f"Invalid {key}")
    topics = [item["topic"] for item in config["sensors"]]
    if len(topics) != len(set(topics)):
        raise ValueError("Duplicate sensor topic")
    for entry in config["sensors"]:
        if not entry["topic"].startswith("zigbee2mqtt/"):
            raise ValueError("Unexpected sensor topic namespace")
        if not isinstance(entry["offline_seconds"], int) or entry["offline_seconds"] < 300:
            raise ValueError("Sensor timeout must be at least five minutes")
    return config


def tcp_open(host, port, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ready(host, port):
    try:
        with urlopen(f"http://{host}:{port}/", timeout=3) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def service_state(name):
    """Only configured WinSW service names can be passed here."""
    result = subprocess.run(["sc.exe", "query", name], capture_output=True,
                            text=True, timeout=10, check=False)
    output = result.stdout + result.stderr
    if result.returncode != 0:
        return "MISSING" if "1060" in output else "UNKNOWN"
    if re.search(r"\bRUNNING\b", output):
        return "RUNNING"
    if re.search(r"\bSTOPPED\b", output):
        return "STOPPED"
    return "PENDING"


def sc_action(action, name):
    result = subprocess.run(["sc.exe", action, name], capture_output=True,
                            text=True, timeout=15, check=False)
    if result.returncode != 0:
        LOG.warning("sc.exe %s %s failed: %s", action, name,
                    (result.stderr or result.stdout).strip()[-400:])
        return False
    return True


def restart_service(name, wait=30):
    if not sc_action("stop", name):
        return False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        state = service_state(name)
        if state == "STOPPED":
            return sc_action("start", name)
        if state in ("MISSING", "UNKNOWN"):
            return False
        time.sleep(1)
    LOG.error("%s did not stop within %ss; refusing duplicate start", name, wait)
    return False


def choose_action(*, upstream, port_ready, service, failures, threshold, elapsed):
    """Pure decision function. Do not restart on individual sensor silence."""
    if not upstream or port_ready or elapsed < 0:
        return None
    if service == "STOPPED" and failures >= 2:
        return "start"
    if service == "RUNNING" and failures >= threshold:
        return "restart"
    return None


class Freshness:
    """Sensor last_seen monitoring; never treats retained/cached data as fresh."""
    def __init__(self, sensors, clock=time.time):
        self.clock = clock
        self.timeouts = {s["topic"]: s["offline_seconds"] for s in sensors}
        self.seen = {}
        self.lock = Lock()

    def update(self, topic, payload, retained=False):
        if retained or topic not in self.timeouts:
            return False
        try:
            obj = json.loads(payload)
            raw = obj.get("last_seen")
            if not isinstance(raw, str):
                return False
            seen = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if seen.tzinfo is None:
                return False
            stamp = seen.timestamp()
        except (ValueError, TypeError, AttributeError):
            return False
        now = self.clock()
        if not now - self.timeouts[topic] <= stamp <= now + 5:
            return False
        with self.lock:
            if stamp <= self.seen.get(topic, 0):
                return False
            self.seen[topic] = stamp
        return True

    def states(self):
        now = self.clock()
        with self.lock:
            return {topic: ("ONLINE" if now - self.seen[topic] <= timeout else "STALE")
                    if topic in self.seen else "NO_FRESH_REPORT"
                    for topic, timeout in self.timeouts.items()}


def supervise(config, once=False):
    freshness = Freshness(config["sensors"])
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="sander-production-recovery-monitor")
    user = __import__("os").environ.get("MQTT_USER")
    if user:
        password = __import__("os").environ.get("MQTT_PASSWORD")
        if password is None:
            raise RuntimeError("MQTT_USER is set but MQTT_PASSWORD is missing")
        client.username_pw_set(user, password)
    if config.get("mqtt_tls"):
        client.tls_set(ca_certs=config.get("mqtt_ca"))

    def on_connect(c, userdata, flags, reason, properties):
        if not reason.is_failure:
            c.subscribe([(topic, 1) for topic in freshness.timeouts])
            LOG.info("MQTT observer connected")
        else:
            LOG.warning("MQTT observer connection refused: %s", reason)

    def on_disconnect(c, userdata, flags, reason, properties):
        LOG.warning("MQTT observer disconnected: %s", reason)

    def on_message(c, userdata, message):
        if freshness.update(message.topic, message.payload, message.retain):
            LOG.info("Fresh sensor data: %s", message.topic)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect_async(config["mqtt_host"], config["mqtt_port"], 30)
    client.loop_start()

    failures = {"z2m": 0, "bridge": 0}
    previous = {}
    last_action = {}
    interval = config["check_interval_seconds"]
    try:
        while True:
            mqtt_ok = tcp_open(config["mqtt_host"], config["mqtt_port"])
            coordinator_ok = tcp_open(config["coordinator_host"], config["coordinator_port"])
            z2m_ready = http_ready(config["z2m_host"], config["z2m_port"])
            bridge_ready = tcp_open(config["bridge_host"], config["bridge_port"])
            now = time.monotonic()
            items = (
                ("z2m", config["z2m_service"], mqtt_ok and coordinator_ok, z2m_ready),
                ("bridge", config["bridge_service"], mqtt_ok, bridge_ready),
            )
            for key, name, upstream, port_ok in items:
                state = service_state(name)
                failures[key] = 0 if port_ok or not upstream else failures[key] + 1
                elapsed = now - last_action.get(key, -10**9)
                action = choose_action(upstream=upstream, port_ready=port_ok,
                                       service=state, failures=failures[key],
                                       threshold=config["failures_before_action"],
                                       elapsed=elapsed - config["restart_cooldown_seconds"])
                if state == "MISSING":
                    LOG.error("Required Windows service %s not installed; no ad-hoc process start", name)
                if action:
                    LOG.warning("%s unhealthy for %s checks; %s service %s",
                                key, failures[key], action, name)
                    last_action[key] = now
                    failures[key] = 0
                    if action == "start":
                        sc_action("start", name)
                    else:
                        restart_service(name)
                status = (port_ok, state, upstream)
                if previous.get(key) != status:
                    LOG.info("%s reachable=%s service=%s upstream=%s",
                             key, port_ok, state, upstream)
                    previous[key] = status
            for topic, status in freshness.states().items():
                if previous.get(topic) != status:
                    LOG.warning("sensor %s status=%s (never initiate pairing/reset)", topic, status)
                    previous[topic] = status
            if once:
                break
            time.sleep(interval)
    finally:
        client.disconnect()
        client.loop_stop()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--log-file", default=None, help="Append rotating IT-visible recovery audit log")
    p.add_argument("--once", action="store_true",
                   help="One read-only pass through checks; no start/restart actions")
    args = p.parse_args()
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_path, maxBytes=2_000_000,
                                            backupCount=5, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s")
    if sys.platform != "win32":
        raise SystemExit("Run supervisor on the approved Windows server only")
    config = load_config(args.config)
    if args.once:
        # Safe diagnostics without service actions.
        for name, host, port in (
            ("mqtt", config["mqtt_host"], config["mqtt_port"]),
            ("coordinator", config["coordinator_host"], config["coordinator_port"]),
            ("z2m", config["z2m_host"], config["z2m_port"]),
            ("bridge", config["bridge_host"], config["bridge_port"]),
        ):
            LOG.info("%s port open: %s", name, tcp_open(host, port))
        for key in ("z2m_service", "bridge_service"):
            LOG.info("%s: %s", config[key], service_state(config[key]))
        return
    supervise(config)


if __name__ == "__main__":
    main()
