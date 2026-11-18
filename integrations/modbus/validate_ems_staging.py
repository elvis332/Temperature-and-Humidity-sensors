"""Source-only EMS integration acceptance. Never imports EMS, collector, or SQL.

Run on a disposable/staging EMS checkout after apply_ui.py --apply.
Does NOT confirm actual SQL-backed runtime behavior: Valen must test that separately.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

POINTS = ("temperature_c", "humidity_pct", "battery_pct", "lqi")


def inspect_staging(ems):
    ems = Path(ems)
    errors = []
    checks = []
    api = ems / "backend/app/api/routes/environment.py"
    page = ems / "frontend/src/pages/EnvironmentPage.jsx"
    battery = ems / "frontend/src/pages/BatteryIcon.jsx"
    profile = ems / "config/profiles/SNZB02D.yaml"
    wired = ems / "config/profiles/WTR10E.yaml"

    for path in (api, page, battery, profile, wired):
        if path.is_file():
            checks.append(f"FILE {path.relative_to(ems)}")
        else:
            errors.append(f"Missing {path.relative_to(ems)}")

    if api.is_file():
        code = api.read_text(encoding="utf-8-sig")
        try:
            compile(code, str(api), "exec")  # no import, no database access
            checks.append("Python API syntax")
        except SyntaxError as exc:
            errors.append(f"API syntax error: {exc}")
        for needle in ('"zigbee"', '"battery_pct"', '"battery_low_pct"',
                       '"offline_grace_seconds"'):
            if needle not in code:
                errors.append(f"Environment API missing integration marker {needle}")
        if '"battery_pct"' in code:
            checks.append("Battery and offline API integration markers")
    if page.is_file():
        code = page.read_text(encoding="utf-8-sig")
        for needle in ("BatteryIcon", "sensor.battery_pct", "sensor.battery_low_pct"):
            if needle not in code:
                errors.append(f"Environment page missing integration marker {needle}")
        if "BatteryIcon" in code:
            checks.append("Environment page battery UI")
    if battery.is_file():
        code = battery.read_text(encoding="utf-8-sig")
        if "threshold" not in code or "value" not in code:
            errors.append("BatteryIcon does not accept value/threshold")
        else:
            checks.append("Battery threshold indicator")
    if profile.is_file():
        try:
            data = yaml.safe_load(profile.read_text(encoding="utf-8-sig"))
            if data["profile"]["id"] != "SNZB02D":
                errors.append("Wrong profile ID")
            points = data["points"]
            if tuple(p["key"] for p in points) != POINTS:
                errors.append("Wrong profile point ordering")
            if tuple(p["source"]["register_address"] for p in points) != (0, 1, 2, 3):
                errors.append("Wrong Modbus register addresses")
            if any(p.get("writable") is not False for p in points):
                errors.append("A Zigbee point is unexpectedly writable")
            if points[2]["alarm"]["min"] != 20:
                errors.append("Battery default alarm threshold must be 20%")
            if not errors:
                checks.append("Four-register read-only sensor profile")
        except (KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"Invalid Zigbee profile: {exc}")

    return {"staging_path": str(ems), "checks": checks, "errors": errors,
            "ready_for_runtime_acceptance": not bool(errors),
            "not_tested": ["staging SQL reads/writes", "EMS collector scheduled polling",
                           "live authentication", "historical charts persisted in SQL",
                           "battery/offline alarm runtime behavior",
                           "WTR10-E non-regression", "server reboot and power recovery"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ems", type=Path, help="Disposable or staging EMS checkout")
    p.add_argument("--frontend-build", action="store_true",
                   help="Run npm build only after the user verifies this is not production")
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    result = inspect_staging(args.ems)
    if result["errors"]:
        for error in result["errors"]:
            print("FAIL", error)
    else:
        for check in result["checks"]:
            print("PASS", check)
    print("NOTE Source checks cannot verify production or staging SQL behavior.")
    if args.frontend_build and not result["errors"]:
        frontend = args.ems / "frontend"
        if not (frontend / "package.json").exists():
            result["errors"].append("frontend/package.json missing")
        else:
            cmd = "npm.cmd" if sys.platform == "win32" else "npm"
            run = subprocess.run([cmd, "run", "build"], cwd=frontend, check=False)
            if run.returncode:
                result["errors"].append("Frontend build failed")
            else:
                result["checks"].append("Frontend build")
    result["ready_for_runtime_acceptance"] = not bool(result["errors"])
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
