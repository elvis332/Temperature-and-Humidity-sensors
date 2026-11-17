"""Read-only preflight on a staged Windows server before service installation."""
import argparse
import json
from pathlib import Path, PureWindowsPath

import yaml
from deploy.site_registry import validate


def evaluate(root, manifest):
    errors, warnings = [], []
    root = Path(root)
    validate(manifest)
    for gw in manifest["gateways"]:
        gid = gw["id"]
        z2m_entry = root / "zigbee2mqtt" / gid / "node_modules" / "zigbee2mqtt" / "index.js"
        z2m_data = root / "Config" / ("zigbee2mqtt." + gid)
        conf = z2m_data / "configuration.yaml"
        db = z2m_data / "database.db"
        if not z2m_entry.is_file():
            errors.append(f"{gid}: Zigbee2MQTT runtime missing: {z2m_entry}")
        if not conf.is_file() or not db.is_file() or db.stat().st_size == 0:
            errors.append(f"{gid}: missing preserved Zigbee network configuration/database; do NOT reset or auto-pair")
            continue
        try:
            value = yaml.safe_load(conf.read_text(encoding="utf-8-sig"))
            serial = value.get("serial") or {}
            mqtt = value.get("mqtt") or {}
            advanced = value.get("advanced") or {}
            expected = f"tcp://{gw['coordinator_host']}:{gw['coordinator_port']}"
            if serial.get("port") != expected:
                errors.append(f"{gid}: serial.port must be approved {expected}")
            if serial.get("adapter") != "ezsp":
                errors.append(f"{gid}: validated radio 7.3.1.0 requires ezsp (no silent firmware migration)")
            if mqtt.get("base_topic") != gw["mqtt_base_topic"]:
                errors.append(f"{gid}: MQTT base topic does not match site registry")
            if advanced.get("last_seen") != "ISO_8601":
                errors.append(f"{gid}: advanced.last_seen must be ISO_8601")
            if not isinstance(value.get("devices"), dict):
                warnings.append(f"{gid}: device friendly_name mapping not seen in configuration.yaml; confirm database preservation")
            for sensor in manifest["sensors"]:
                if sensor["gateway_id"] != gid:
                    continue
                devices = value.get("devices") or {}
                row = devices.get(sensor["ieee_address"].lower(), {})
                actual = row.get("friendly_name") if isinstance(row, dict) else None
                if actual and actual != sensor["friendly_name"]:
                    errors.append(f"{gid}: friendly name mismatch for {sensor['device_id']}; do not re-pair automatically")
                if not actual:
                    warnings.append(f"{gid}: confirm first pairing/rename for {sensor['device_id']} before EMS activation")
        except (ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
            errors.append(f"{gid}: invalid existing Zigbee2MQTT YAML: {exc}")
    return errors, warnings


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    args = p.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    errors, warnings = evaluate(args.root, manifest)
    for warning in warnings:
        print("WARNING:", warning)
    for error in errors:
        print("BLOCKER:", error)
    if errors:
        print("NOT READY: server prerequisite validation failed")
        return 2
    print("PASS: software directory and saved Zigbee network config preflight; server runtime untested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
