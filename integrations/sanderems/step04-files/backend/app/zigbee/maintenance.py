"""Restricted, audited Zigbee2MQTT maintenance. Disabled by default."""

import json
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request

ALLOWED_OPTIONS = {
    "temperature_calibration": (-50, 50),
    "humidity_calibration": (-50, 50),
}
PAIR_SECONDS = 60
_GATEWAY_LOCK = threading.RLock()


def maintenance_state():
    enabled = os.getenv("EMS_ZIGBEE_MAINTENANCE_ENABLED", "false").lower() == "true"
    audit_path = os.getenv("EMS_ZIGBEE_MAINTENANCE_AUDIT_PATH", "")
    origins = {x.strip().rstrip("/") for x in os.getenv("EMS_ZIGBEE_WRITE_ORIGINS", "").split(",") if x.strip()}
    return {
        "enabled": enabled and bool(audit_path) and bool(origins),
        "settings_enabled": os.getenv("EMS_ZIGBEE_DEVICE_OPTIONS_ENABLED", "false").lower() == "true",
        "pair_seconds": PAIR_SECONDS,
        "allowed_settings": sorted(ALLOWED_OPTIONS),
    }


def enforce_admin_write(request: Request, *, settings=False):
    state = maintenance_state()
    if not state["enabled"] or (settings and not state["settings_enabled"]):
        raise HTTPException(503, "Zigbee maintenance is disabled pending IT approval")
    allowed = {x.strip().rstrip("/") for x in os.getenv("EMS_ZIGBEE_WRITE_ORIGINS", "").split(",") if x.strip()}
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin or origin not in allowed:
        raise HTTPException(403, "Untrusted browser origin for Zigbee maintenance")


def validate_option(option, value):
    if option not in ALLOWED_OPTIONS or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Unsupported device setting or value")
    value = float(value)
    lower, upper = ALLOWED_OPTIONS[option]
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError("Device setting is outside its allowed range")
    return value


def audit_event(user, gateway, action, detail, status, event_id=None):
    """Durable append-only-by-convention record; fails closed without writable audit path."""
    path_text = os.getenv("EMS_ZIGBEE_MAINTENANCE_AUDIT_PATH", "")
    path = Path(path_text)
    if not path_text or not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
        raise OSError("Protected Zigbee audit file has not been configured")
    record = {
        "event_id": event_id or uuid.uuid4().hex,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "user": user,
        "gateway": gateway,
        "action": action,
        "details": detail,
        "status": status,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    line = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    return record["event_id"]


def execute_audited(observer, user, gateway, action, details, operation, payload):
    """Serializes commands and persists the intent before the MQTT publish."""
    with _GATEWAY_LOCK:
        try:
            event_id = audit_event(user, gateway, action, details, "requested")
        except OSError as exc:
            raise HTTPException(503, "Zigbee audit logging unavailable; command not sent") from exc
        try:
            response = observer.request(operation, payload)
            outcome = "acknowledged" if response.get("status") == "ok" else "rejected"
            error = None if outcome == "acknowledged" else "Zigbee2MQTT rejected the command"
        except Exception as exc:
            response = None
            outcome = "uncertain"
            error = "Command status uncertain; check gateway before retrying"
        try:
            audit_event(user, gateway, action, details, outcome, event_id)
        except OSError as exc:
            raise HTTPException(503, "Zigbee audit result unavailable; check gateway state") from exc
        if error:
            raise HTTPException(504 if outcome == "uncertain" else 502, error)
        return {"accepted": True, "event_id": event_id, "gateway_id": gateway}
