"""Check configured endpoints only; no network scanning or database."""
import argparse
import json
import socket
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="bridge/config.test.json")
    p.add_argument("--coordinator")
    p.add_argument("--bridge", action="store_true")
    args = p.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    targets = [("MQTT", cfg["mqtt_host"], cfg["mqtt_port"])]
    if args.coordinator:
        targets += [("Coordinator web", args.coordinator, 80), ("Zigbee radio", args.coordinator, 6638)]
    if args.bridge:
        targets.append(("Modbus bridge", cfg["modbus_host"], cfg["modbus_port"]))
    failed = False
    for name, host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"PASS {name}: {host}:{port}")
        except OSError as exc:
            failed = True
            print(f"FAIL {name}: {host}:{port} ({exc})")
    return int(failed)

if __name__ == "__main__":
    raise SystemExit(main())
