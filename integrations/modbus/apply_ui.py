"""Patch only the inspected EMS snapshot, never import EMS or read .env."""
import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def replace(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one match: {old[:90]}")
    return text.replace(old, new, 1)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("ems", type=Path)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    ems = args.ems
    api = ems / "backend/app/api/routes/environment.py"
    ui = ems / "frontend/src/pages/EnvironmentPage.jsx"
    a, u = api.read_text(encoding="utf-8-sig"), ui.read_text(encoding="utf-8-sig")
    a = replace(a, 'limit = max(OFFLINE_AFTER_SECONDS, 3 * sensor["sampling_seconds"])',
        'limit = sensor.get("offline_grace_seconds") or max(OFFLINE_AFTER_SECONDS, 3 * sensor["sampling_seconds"])')
    a = replace(a, '        sensors.append({',
        '''        zigbee = bool(settings_row and settings_row.profile_id == "SNZB02D")
        env = settings.get("environment") or {}
        sensors.append({
            "zigbee": zigbee,
            "battery_low_pct": (alarm_limits(settings_row, ("battery_pct",), profiles).get("battery_pct", {}).get("min", 20)) if zigbee else None,
            "offline_grace_seconds": env.get("offline_grace_seconds", 120) if zigbee else None,''')
    a = replace(a, 'TelemetryReading.point_key.in_(VALUE_KEYS)', 'TelemetryReading.point_key.in_((*VALUE_KEYS, "battery_pct"))')
    a = replace(a, '        sensor["alarms"] = []',
        '''        battery = series.get((sensor_id, "battery_pct"), [])
        sensor["battery_pct"] = battery[-1][1] if live and battery and sensor["zigbee"] else None
        sensor["alarms"] = []''')
    a = replace(a, '        sensor["attention"] = sensor["status"] in ("offline", "data_error", "no_data") or bool(sensor["alarms"])',
        '''        low_battery = sensor["zigbee"] and sensor["battery_pct"] is not None and sensor["battery_pct"] <= (sensor["battery_low_pct"] if sensor["battery_low_pct"] is not None else 20)
        sensor["attention"] = sensor["status"] in ("offline", "data_error", "no_data") or bool(sensor["alarms"]) or low_battery''')
    u = replace(u, 'import { useI18n } from "../i18n";', 'import { useI18n } from "../i18n";\nimport BatteryIcon from "./BatteryIcon";')
    u = replace(u, '        <span>{place}</span>', '        <span>{place}</span>\n        {sensor.zigbee && <BatteryIcon value={sensor.battery_pct} threshold={sensor.battery_low_pct} />}')
    if args.apply:
        api.write_text(a, encoding="utf-8")
        ui.write_text(u, encoding="utf-8")
        shutil.copyfile(HERE / "BatteryIcon.jsx", ui.parent / "BatteryIcon.jsx")
        shutil.copyfile(ROOT / "config/profiles/SNZB02D.yaml", ems / "config/profiles/SNZB02D.yaml")
        print("Patched development EMS copy. Review git diff; do not start EMS with production .env.")
    else:
        print("Source anchors matched. Dry run only; use --apply on a disposable development copy.")

if __name__ == "__main__":
    main()
