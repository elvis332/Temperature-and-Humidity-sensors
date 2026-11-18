"""Read-only Zigbee2MQTT discovery for the existing EMS Devices page.

This does not pair, register or configure any device. Nothing connects at API startup;
IT must explicitly enable discovery and configure a validated gateway manifest.
"""
import json
import os
import re
import threading
from ipaddress import ip_address
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import require_admin
from backend.app.zigbee.discovery import Observer, ObserverError

router = APIRouter(prefix="/admin/zigbee", tags=["Zigbee discovery"],
                   dependencies=[Depends(require_admin)])
_lock = threading.RLock()
_observers = {}
_gateway_identity = {}
_IDENT = re.compile(r"^[A-Za-z0-9_-]{1,50}$")


def _load_gateways():
    path = Path(os.getenv("EMS_ZIGBEE_MANIFEST", "C:/Sander/Config/site-manifest.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        gateways = data["gateways"]
        if not isinstance(gateways, list) or len(gateways) > 25:
            raise ValueError("Invalid gateway list")
        seen_ids, seen_topics = set(), set()
        for item in gateways:
            if not isinstance(item, dict):
                raise ValueError("Invalid gateway")
            gid, topic, host = (item.get("id"), item.get("mqtt_base_topic"),
                                item.get("coordinator_host"))
            if not isinstance(gid, str) or not _IDENT.fullmatch(gid) or gid in seen_ids:
                raise ValueError("Invalid gateway id")
            if not isinstance(topic, str) or not _IDENT.fullmatch(topic) or topic in seen_topics:
                raise ValueError("Invalid MQTT topic")
            if not isinstance(host, str):
                raise ValueError("Invalid gateway address")
            addr = ip_address(host)
            if addr.version != 4 or not addr.is_private or addr.is_loopback or addr.is_unspecified:
                raise ValueError("Invalid gateway address")
            port = item.get("coordinator_port")
            if not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("Invalid gateway TCP port")
            if item.get("coordinator_transport", "ethernet_tcp") != "ethernet_tcp":
                raise ValueError("Unsupported coordinator transport")
            seen_ids.add(gid)
            seen_topics.add(topic)
        return gateways
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=503,
                            detail="Zigbee gateway manifest is unavailable or invalid") from None


def _observer_for(gateway):
    gid = gateway["id"]
    identity = (gateway["mqtt_base_topic"], gateway["coordinator_host"],
                gateway.get("coordinator_port", 6638))
    with _lock:
        if gid in _observers:
            if _gateway_identity[gid] != identity:
                raise HTTPException(status_code=409,
                                    detail="Gateway configuration changed; administrator restart required")
            return _observers[gid]
        # Keep discovery strictly on the local server's MQTT broker.
        broker = os.getenv("EMS_ZIGBEE_MQTT_HOST", "127.0.0.1")
        if broker not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(status_code=503, detail="MQTT must use the local EMS broker")
        try:
            port = int(os.getenv("EMS_ZIGBEE_MQTT_PORT", "1883"))
            if not 1 <= port <= 65535:
                raise ValueError("Invalid port")
            credentials = os.getenv("EMS_ZIGBEE_MQTT_CREDENTIALS_FILE") or None
            observer = Observer(gateway, broker, port, credentials_file=credentials)
            observer.start()
        except (ObserverError, OSError, ValueError, RuntimeError):
            raise HTTPException(status_code=503,
                                detail="Zigbee MQTT observer unavailable") from None
        _observers[gid] = observer
        _gateway_identity[gid] = identity
        return observer


@router.get("/discovery")
def discovery():
    if os.getenv("EMS_ZIGBEE_DISCOVERY_ENABLED", "false").lower() not in {"true", "yes", "1"}:
        return {"enabled": False, "gateways": []}
    gateways = []
    for gateway in _load_gateways():
        observer = _observer_for(gateway)
        state = observer.status()
        gateways.append({"gateway_id": gateway["id"],
                         "mqtt_connected": state["mqtt_connected"],
                         "zigbee2mqtt_state": state["zigbee2mqtt_state"],
                         "devices": observer.discovered()})
    return {"enabled": True, "gateways": gateways}

# Narrow maintenance interface: administrator, trusted browser origin,
# IT feature flags, durable audit and correlated Zigbee2MQTT acknowledgement.
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from fastapi import Request
from backend.app.zigbee.maintenance import (
    enforce_admin_write, maintenance_state, validate_option, execute_audited,
)


class PairAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seconds: Literal[0, 60]
    confirmation: str = Field(max_length=50)


class DeviceOptionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ieee_address: str = Field(pattern=r"^0x[0-9a-fA-F]{16}$")
    key: Literal["temperature_calibration", "humidity_calibration"]
    value: float
    confirmation: str = Field(max_length=18)


def _online_gateway(gateway_id):
    if os.getenv("EMS_ZIGBEE_DISCOVERY_ENABLED", "false").lower() not in {"true", "yes", "1"}:
        raise HTTPException(503, "Zigbee discovery is disabled")
    gateway = next((g for g in _load_gateways() if g["id"] == gateway_id), None)
    if not gateway:
        raise HTTPException(404, "Unknown Zigbee gateway")
    observer = _observer_for(gateway)
    status = observer.status()
    if not status["mqtt_connected"] or status["zigbee2mqtt_state"] != "online":
        raise HTTPException(503, "Gateway Zigbee2MQTT is not online")
    return observer


@router.get("/maintenance")
def maintenance_status():
    return maintenance_state()


@router.post("/gateways/{gateway_id}/pair")
def pair_gateway(gateway_id: str, body: PairAction, request: Request, user=Depends(require_admin)):
    enforce_admin_write(request)
    if body.confirmation != gateway_id:
        raise HTTPException(422, "Confirm the exact gateway ID")
    observer = _online_gateway(gateway_id)
    action = "pair_60s" if body.seconds == 60 else "pair_stop"
    return execute_audited(observer, user.username, gateway_id, action,
                           {"seconds": body.seconds}, "permit_join", {"time": body.seconds})


@router.post("/gateways/{gateway_id}/device-options")
def change_device_option(gateway_id: str, body: DeviceOptionAction,
                         request: Request, user=Depends(require_admin)):
    enforce_admin_write(request, settings=True)
    observer = _online_gateway(gateway_id)
    ieee = body.ieee_address.lower()
    if body.confirmation.lower() != ieee:
        raise HTTPException(422, "Confirm the exact sensor IEEE address")
    if not any(d["ieee_address"].lower() == ieee and d["model"] == "SNZB-02D"
               for d in observer.discovered()):
        raise HTTPException(409, "Only discovered SNZB-02D sensors can be configured")
    try:
        value = validate_option(body.key, body.value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return execute_audited(observer, user.username, gateway_id, "sensor_option",
                           {"ieee": ieee, "setting": body.key, "value": value},
                           "device/options", {"id": ieee, "options": {body.key: value}})
