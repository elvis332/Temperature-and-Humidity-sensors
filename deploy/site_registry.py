"""Validate site inventory and generate deterministic gateway deployment files.

No network connections, SQL operations, pairing, or Windows service installation.
The EMS CSV is a review manifest, NOT an automatic database import.
"""
import argparse
import csv
import ipaddress
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

GATEWAY_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}$")
SENSOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
IEEE = re.compile(r"^0x[0-9a-fA-F]{16}$")
HOST = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$")
FIELDS = ("device_id", "ieee_address", "friendly_name", "location",
          "gateway_id", "mqtt_topic", "modbus_host", "modbus_port",
          "modbus_unit_id", "profile_id", "offline_seconds", "status")


def validate(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")
    if manifest.get("schema_version") != 1:
        raise ValueError("Expected schema_version 1")
    gateways, sensors = manifest.get("gateways"), manifest.get("sensors")
    if not isinstance(gateways, list) or not gateways:
        raise ValueError("At least one gateway is required")
    if not isinstance(sensors, list) or not sensors:
        raise ValueError("At least one sensor is required")
    by_id = {}
    used_ports, used_topics, used_devids, used_ieees, used_units = set(), set(), set(), set(), set()
    for gw in gateways:
        name = gw.get("id")
        if not isinstance(name, str) or not GATEWAY_ID.fullmatch(name) or name in by_id:
            raise ValueError("Gateway id must be unique and contain only letters/digits")
        host = gw.get("coordinator_host")
        if not isinstance(host, str) or not HOST.fullmatch(host):
            raise ValueError(f"{name}: invalid coordinator host")
        for prop in ("coordinator_port", "modbus_port", "z2m_ui_port"):
            value = gw.get(prop)
            if type(value) is not int or not 1 <= value <= 65535:
                raise ValueError(f"{name}: invalid {prop}")
        for prop in ("modbus_port", "z2m_ui_port"):
            port = gw[prop]
            if port in used_ports or port in (1883,):
                raise ValueError(f"Duplicate/reserved server port {port}")
            used_ports.add(port)
        base = gw.get("mqtt_base_topic")
        if not isinstance(base, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", base):
            raise ValueError(f"{name}: invalid mqtt_base_topic")
        if base in used_topics:
            raise ValueError("MQTT base topics must be unique across gateways")
        used_topics.add(base)
        by_id[name] = gw
    for sensor in sensors:
        device_id = sensor.get("device_id")
        ieee = sensor.get("ieee_address")
        name = sensor.get("friendly_name")
        gid = sensor.get("gateway_id")
        unit = sensor.get("unit_id")
        location = sensor.get("location")
        offline = sensor.get("offline_seconds", 900)
        if not isinstance(device_id, str) or not SENSOR_ID.fullmatch(device_id) or device_id in used_devids:
            raise ValueError("Missing, invalid or duplicate EMS device_id")
        if not isinstance(ieee, str) or not IEEE.fullmatch(ieee) or ieee.lower() in used_ieees:
            raise ValueError(f"{device_id}: invalid/duplicate IEEE address")
        if not isinstance(name, str) or not SENSOR_ID.fullmatch(name):
            raise ValueError(f"{device_id}: invalid friendly_name")
        if gid not in by_id:
            raise ValueError(f"{device_id}: unknown gateway")
        if type(unit) is not int or not 1 <= unit <= 247:
            raise ValueError(f"{device_id}: Modbus unit ID must be 1–247 per endpoint")
        if (gid, unit) in used_units:
            raise ValueError(f"{device_id}: duplicate Modbus unit on gateway")
        if not isinstance(location, str) or not location.strip():
            raise ValueError(f"{device_id}: location required for EMS registration")
        if type(offline) is not int or offline < 300:
            raise ValueError(f"{device_id}: offline_seconds must be at least 300")
        if any(x["gateway_id"] == gid and x["friendly_name"] == name for x in sensors
               if x is not sensor):
            raise ValueError(f"{device_id}: duplicate Zigbee friendly_name on gateway")
        used_ieees.add(ieee.lower())
        used_devids.add(device_id)
        used_units.add((gid, unit))
    return by_id


def service_xml(name, title, executable, arguments, workingdir, data=None, env=None):
    root = ET.Element("service")
    for key, value in (("id", name), ("name", title),
                       ("executable", executable), ("arguments", arguments),
                       ("workingdirectory", workingdir)):
        ET.SubElement(root, key).text = str(value)
    if data:
        ET.SubElement(root, "env", name="ZIGBEE2MQTT_DATA", value=str(data))
    if env:
        ET.SubElement(root, "env", name="BRIDGE_CONFIG", value=str(env))
    # Least-privilege built-in account; IT must grant read access to config/keys and write access to logs.
    ET.SubElement(ET.SubElement(root, "serviceaccount"), "username").text = r"NT AUTHORITY\LocalService"
    ET.SubElement(root, "depend").text = "mosquitto"
    ET.SubElement(root, "startmode").text = "Automatic"
    ET.SubElement(root, "stoptimeout").text = "30 sec"
    ET.SubElement(root, "onfailure", action="restart", delay="30 sec")
    ET.SubElement(root, "log", mode="roll")
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=False) + "\n"


def build(manifest, root=r"C:\Sander"):
    by_id = validate(manifest)
    rootw = PureWindowsPath(root)
    if not rootw.is_absolute() or str(rootw.drive).startswith("\\"):
        raise ValueError("Install root must be a local absolute Windows drive path")
    output = {}
    rows = []
    site = manifest.get("site_id", "SanderSite")
    for gid, gw in by_id.items():
        own = [s for s in manifest["sensors"] if s["gateway_id"] == gid]
        if not own:
            raise ValueError(f"{gid}: no assigned sensors")
        prefix = gw["mqtt_base_topic"]
        z2m_service = "SanderZ2M" + gid
        bridge_service = "SanderBridge" + gid
        z2m_root = str(rootw / "zigbee2mqtt" / gid)
        z2m_data = str(rootw / "Config" / ("zigbee2mqtt." + gid))
        bridge_root = str(rootw / "ZigbeeBridge")
        bridge_path = str(rootw / "Config" / ("bridge." + gid + ".json"))
        recovery_path = str(rootw / "Config" / ("recovery." + gid + ".json"))
        mqtt_sensors = [
            {"unit_id": s["unit_id"], "topic": prefix + "/" + s["friendly_name"],
             "offline_seconds": s.get("offline_seconds", 900)}
            for s in own
        ]
        bridge = {
            "mqtt_host": "127.0.0.1", "mqtt_port": 1883,
            "mqtt_auth_file": str(rootw / "Config" / ("mqtt-bridge-" + gid + ".auth.json")),
            "client_id": f"sander-bridge-{gid}",
            "modbus_host": "127.0.0.1", "modbus_port": gw["modbus_port"],
            "sensors": mqtt_sensors
        }
        recovery = {
            "mqtt_host": "127.0.0.1", "mqtt_port": 1883,
            "mqtt_auth_file": str(rootw / "Config" / ("mqtt-recovery-" + gid + ".auth.json")),
            "coordinator_host": gw["coordinator_host"],
            "coordinator_port": gw["coordinator_port"],
            "z2m_host": "127.0.0.1", "z2m_port": gw["z2m_ui_port"],
            "bridge_host": "127.0.0.1", "bridge_port": gw["modbus_port"],
            "z2m_service": z2m_service, "bridge_service": bridge_service,
            "client_id": f"sander-recovery-{gid}",
            "check_interval_seconds": 15, "failures_before_action": 4,
            "restart_cooldown_seconds": 300, "z2m_health_timeout_seconds": 1800,
            "bridge_health_topic": prefix + "/bridge/health",
            "sensors": [{"topic": s["topic"], "offline_seconds": s["offline_seconds"]}
                        for s in mqtt_sensors]
        }
        node = r"C:\Program Files\nodejs\node.exe"
        output[f"bridge.{gid}.json"] = json.dumps(bridge, indent=2) + "\n"
        output[f"recovery.{gid}.json"] = json.dumps(recovery, indent=2) + "\n"
        output[f"{z2m_service}.xml"] = service_xml(
            z2m_service, f"Sander Zigbee2MQTT {gid}", node,
            str(PureWindowsPath(z2m_root) / "node_modules" / "zigbee2mqtt" / "index.js"),
            z2m_root, data=z2m_data)
        output[f"{bridge_service}.xml"] = service_xml(
            bridge_service, f"Sander Zigbee Modbus Bridge {gid}",
            str(rootw / "ZigbeeBridge" / ".venv" / "Scripts" / "python.exe"),
            "-m bridge.bridge", bridge_root, env=bridge_path)
        for s in own:
            rows.append({
                "device_id": s["device_id"], "ieee_address": s["ieee_address"].lower(),
                "friendly_name": s["friendly_name"], "location": s["location"],
                "gateway_id": gid,
                "mqtt_topic": prefix + "/" + s["friendly_name"],
                "modbus_host": "127.0.0.1",
                "modbus_port": gw["modbus_port"], "modbus_unit_id": s["unit_id"],
                "profile_id": "SNZB02D", "offline_seconds": s.get("offline_seconds", 900),
                "status": "REVIEW_ONLY_NOT_IMPORTED"
            })
    # Stable audit manifest ensures explicit approval before EMS database actions.
    import io
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    output["ems-device-registration-review.csv"] = stream.getvalue()
    output["deployment-summary.json"] = json.dumps({
        "site_id": site, "gateway_count": len(by_id),
        "sensor_count": len(rows), "installed": False,
        "ems_registered": False, "coordinators_paired": False,
        "notes": "Approval-only manifest; these files do NOT install services or write EMS SQL."
    }, indent=2) + "\n"
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", default=r"C:\Sander")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="Write new files; never overwrite")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        outputs = build(manifest, root=args.root)
        print(f"Validated site: {len(manifest['gateways'])} gateways, {len(manifest['sensors'])} sensors")
        for name in outputs:
            print(f"  {name}")
        if not args.write:
            print("DRY RUN: no files changed. Add --write to stage files.")
            return 0
        if args.output.exists() and any(args.output.iterdir()):
            raise ValueError("Output directory must be empty; existing config files are never overwritten")
        args.output.mkdir(parents=True, exist_ok=True)
        for name, text in outputs.items():
            (args.output / name).write_text(text, encoding="utf-8")
        print("Generated review artifacts. No Windows services or EMS device records installed.")
        return 0
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
