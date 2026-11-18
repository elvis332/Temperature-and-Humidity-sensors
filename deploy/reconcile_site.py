"""Review proposed device inventory changes; never edits EMS, Zigbee config, or SQL."""
import argparse
import json
from pathlib import Path

from deploy.site_registry import validate


IMMUTABLE = ("device_id", "ieee_address", "gateway_id", "unit_id")
REVIEW_FIELDS = ("friendly_name", "location", "offline_seconds")


def review(before, after):
    validate(before)
    validate(after)
    previous = {x["device_id"]: x for x in before["sensors"]}
    current = {x["device_id"]: x for x in after["sensors"]}
    created, updated, removed, blocked = [], [], [], []
    old_gw = {x["id"]: x for x in before["gateways"]}
    new_gw = {x["id"]: x for x in after["gateways"]}
    for gid in set(old_gw) & set(new_gw):
        for field in ("coordinator_transport", "coordinator_host", "coordinator_port", "mqtt_base_topic",
                      "modbus_port", "z2m_ui_port"):
            if old_gw[gid][field] != new_gw[gid][field]:
                blocked.append(f"{gid}: gateway.{field} changed; requires a dedicated migration plan")
    for dev_id in sorted(set(current) | set(previous)):
        if dev_id not in previous:
            created.append(dev_id)
            continue
        if dev_id not in current:
            removed.append(dev_id)
            continue
        old, new = previous[dev_id], current[dev_id]
        # A change in endpoint/unit, IEEE, or ID can silently mix sensor historical series.
        for field in IMMUTABLE[1:]:
            if old[field] != new[field]:
                blocked.append(f"{dev_id}: immutable {field} changed ({old[field]} -> {new[field]})")
        changed = [field for field in REVIEW_FIELDS if old.get(field, 900) != new.get(field, 900)]
        if changed:
            updated.append({"device_id": dev_id, "fields": changed})
    for gid in set(old_gw) - set(new_gw):
        blocked.append(f"{gid}: existing gateway removed")
    if removed:
        blocked.extend(f"{dev_id}: sensor removal requires explicit retirement/archival" for dev_id in removed)
    return {"added": created, "updated_for_review": updated, "removed": removed,
            "blockers": blocked, "automatically_applied": False,
            "note": "Proposal only. No EMS SQL, Zigbee network or Windows services modified."}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    result = review(json.loads(args.before.read_text(encoding="utf-8")),
                    json.loads(args.after.read_text(encoding="utf-8")))
    output = json.dumps(result, indent=2)
    print(output)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    return 2 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
