"""Opt-in EMS staging-only UI patch.

Does not inspect .env, import EMS backend, access SQL or change production.
Requires a deliberate JSX slot marker placed by Valen in DevicesPage.jsx.
"""
import argparse
import shutil
from pathlib import Path

MARKER = "{/* SANDER_ZIGBEE_ADMIN_SLOT */}"
IMPORT = 'import ZigbeeAdminPanel from "./ZigbeeAdminPanel";'


def prepare(ems_root: Path):
    page = Path(ems_root) / "frontend/src/pages/DevicesPage.jsx"
    text = page.read_text(encoding="utf-8-sig")
    if text.count(MARKER) != 1:
        raise ValueError("Valen must insert exactly one SANDER_ZIGBEE_ADMIN_SLOT marker inside the administrator Devices JSX")
    if "ZigbeeAdminPanel" in text.replace(MARKER, ""):
        raise ValueError("Zigbee panel already referenced; verify git diff before modifying")
    if not ("export default" in text or "function DevicesPage" in text):
        raise ValueError("Unexpected DevicesPage layout; review source first")
    return page, IMPORT + "\n" + text.replace(MARKER,
            '<ZigbeeAdminPanel />')
    # Valen must pass an approved EMS CSRF token prop when the app uses cookie sessions.
    # Never disable existing server-side CSRF checks to make this component work.


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ems_root", type=Path)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    try:
        page, updated = prepare(args.ems_root)
        component = Path(__file__).resolve().parent / "ZigbeeAdminPanel.jsx"
        output = page.parent / "ZigbeeAdminPanel.jsx"
        if output.exists():
            raise ValueError("Panel component file already exists; refuse overwrite")
        if args.apply:
            shutil.copyfile(component, output)
            page.write_text(updated, encoding="utf-8")
            print("Patched disposable EMS Devices page. Inspect git diff, CSRF prop and admin guard; do NOT deploy automatically.")
        else:
            print("DRY RUN: JSX slot found, panel can be staged. No file changes.")
    except (ValueError, OSError) as exc:
        print("BLOCKED:", exc)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
