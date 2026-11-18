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
