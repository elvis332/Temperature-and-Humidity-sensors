"""EMS FastAPI route factory for Zigbee Advanced Maintenance.

NO standalone app or independent login: caller MUST inject the current EMS
administrator dependency and existing audit sink. Never mount as a public route.
The router does not import SQL or alter production EMS configuration.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from integrations.ems.zigbee_control import (
    ZigbeeFleet, InvalidRequest, Unavailable, ZigbeeControlError,
)

ADMIN_PROXY_RE = re.compile(r"^/admin/zigbee/native/[A-Za-z0-9]{1,16}/$")


class JoinPayload(BaseModel):
    seconds: int = Field(ge=0, le=60)


class RegistrationPayload(BaseModel):
    gateway_id: str
    ieee_address: str
    device_id: str
    location: str


class ExposePayload(BaseModel):
    setting: str
    value: float


class OptionPayload(BaseModel):
    option: str
    value: Any


class ConnectionProposal(BaseModel):
    coordinator_host: str
    coordinator_port: int = Field(ge=1, le=65535)
    coordinator_transport: str = "ethernet_tcp"


def create_admin_router(
    fleet: ZigbeeFleet,
    *,
    require_ems_admin: Callable,
    audit_change: Callable,
    register_transaction: Callable | None = None,
    native_proxy_paths: dict[str, str] | None = None,
) -> APIRouter:
    """Mount under the existing EMS authenticated API router.

    require_ems_admin must be the **real** EMS dependency that rejects unauthenticated,
    unauthorized users. Audit callback must persist in the existing EMS audit system.
    register_transaction must apply a single approved EMS and bridge registration
    transaction, otherwise registration commit is intentionally unavailable.
    """
    if not callable(require_ems_admin) or not callable(audit_change):
        raise ValueError("Require existing EMS administrator authentication and audit logging")
    paths = native_proxy_paths or {}
    for gateway, url in paths.items():
        if gateway not in fleet.gateways or not isinstance(url, str) or not ADMIN_PROXY_RE.fullmatch(url):
            raise ValueError("Advanced Maintenance URL must be an approved same-origin admin-only proxy path")

    router = APIRouter(prefix="/admin/zigbee", tags=["Zigbee Admin"],
                       dependencies=[Depends(require_ems_admin)])

    def _actor(actor):
        if isinstance(actor, dict):
            return str(actor.get("id") or actor.get("username") or "unknown-admin")
        return str(getattr(actor, "id", None) or getattr(actor, "username", None) or "unknown-admin")

    def _audit(name: str, principal, **detail):
        # Fail closed if audit pipeline fails. No sensitive MQTT payloads included.
        try:
            audit_change({"action": name, "actor": _actor(principal), **detail})
        except Exception as exc:
            raise HTTPException(status_code=503, detail="EMS audit subsystem unavailable") from exc

    def _gateway(gateway_id: str):
        try:
            return fleet.gateway(gateway_id)
        except InvalidRequest as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _perform(fn):
        try:
            return fn()
        except InvalidRequest as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Unavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/capabilities")
    def capabilities():
        return {
            "registration_commit_enabled": register_transaction is not None,
            "pairing_max_seconds": 60,
            "advanced_native_requires_it_proxy": True,
            "automatic_pairing_at_startup": False,
            "network_changes_apply_live": False,
        }

    @router.get("/gateways")
    def gateways():
        return [gw.snapshot() for gw in fleet.gateways.values()]

    @router.get("/gateways/{gateway_id}/devices")
    def discovered_devices(gateway_id: str):
        return _gateway(gateway_id).devices_snapshot()

    @router.get("/gateways/{gateway_id}/events")
    def recent_events(gateway_id: str):
        gw = _gateway(gateway_id)
        with gw._lock:
            return list(gw.events[-25:])

    @router.get("/gateways/{gateway_id}/advanced")
    def advanced_maintenance(gateway_id: str):
        _gateway(gateway_id)
        return {
            "gateway_id": gateway_id,
            "native_admin_path": paths.get(gateway_id),
            "configured": gateway_id in paths,
            "notice": "Native Zigbee2MQTT frontend must be routed through existing EMS administrator-authenticated reverse proxy with websocket support. Never expose direct port 8080."
        }

    @router.post("/gateways/{gateway_id}/permit-join")
    def permit_join(gateway_id: str, payload: JoinPayload, principal=Depends(require_ems_admin)):
        gw = _gateway(gateway_id)
        _audit("zigbee.permit_join.requested", principal, gateway=gateway_id,
               seconds=payload.seconds)
        result = _perform(lambda: gw.permit_join(payload.seconds))
        _audit("zigbee.permit_join.acknowledged", principal, gateway=gateway_id,
               seconds=payload.seconds)
        return result

    @router.post("/gateways/{gateway_id}/devices/{ieee_address}/expose")
    def set_expose(gateway_id: str, ieee_address: str, payload: ExposePayload,
                   principal=Depends(require_ems_admin)):
        gw = _gateway(gateway_id)
        _audit("zigbee.expose.requested", principal, gateway=gateway_id,
               ieee_address=ieee_address, setting=payload.setting)
        result = _perform(lambda: gw.set_expose(ieee_address, payload.setting, payload.value))
        _audit("zigbee.expose.sent_unverified", principal, gateway=gateway_id,
               ieee_address=ieee_address, setting=payload.setting)
        return result

    @router.post("/gateways/{gateway_id}/devices/{ieee_address}/option")
    def set_option(gateway_id: str, ieee_address: str, payload: OptionPayload,
                   principal=Depends(require_ems_admin)):
        gw = _gateway(gateway_id)
        _audit("zigbee.option.requested", principal, gateway=gateway_id,
               ieee_address=ieee_address, option=payload.option)
        result = _perform(lambda: gw.set_device_option(ieee_address, payload.option, payload.value))
        _audit("zigbee.option.acknowledged", principal, gateway=gateway_id,
               ieee_address=ieee_address, option=payload.option)
        return result

    @router.post("/registration/plan")
    def registration_plan(payload: RegistrationPayload, principal=Depends(require_ems_admin)):
        plan = _perform(lambda: fleet.registration_plan(**payload.model_dump()))
        _audit("zigbee.registration.plan", principal, gateway=payload.gateway_id,
               device_id=payload.device_id, ieee_address=payload.ieee_address)
        return plan

    @router.post("/registration/commit")
    def commit_registration(payload: RegistrationPayload, principal=Depends(require_ems_admin)):
        if register_transaction is None:
            raise HTTPException(status_code=501,
                                detail="EMS database/bridge registration adapter not installed; no changes made")
        plan = _perform(lambda: fleet.registration_plan(**payload.model_dump()))
        _audit("zigbee.registration.commit_requested", principal, gateway=payload.gateway_id,
               device_id=payload.device_id, ieee_address=payload.ieee_address)
        try:
            # Real EMS must atomically synchronize registration, bridge config,
            # existing Devices records and audited rollback. NEVER raw SQL here.
            result = register_transaction(plan, principal)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="EMS registration failed; verify rollback") from exc
        _audit("zigbee.registration.committed", principal, gateway=payload.gateway_id,
               device_id=payload.device_id, ieee_address=payload.ieee_address)
        return {"committed": True, "result": result}

    @router.post("/gateways/{gateway_id}/network/propose")
    def propose_network(gateway_id: str, payload: ConnectionProposal,
                        principal=Depends(require_ems_admin)):
        gw = _gateway(gateway_id)
        if payload.coordinator_transport != "ethernet_tcp":
            raise HTTPException(status_code=422, detail="SLZB-06MU requires Ethernet TCP; not RS-485 Modbus")
        import ipaddress
        try:
            # require concrete private/IT-routable IP, no localhost/public network tricks
            ip = ipaddress.ip_address(payload.coordinator_host)
            if not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
                raise ValueError("unacceptable")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Approved private coordinator IP required") from exc
        _audit("zigbee.network.proposal", principal, gateway=gateway_id)
        return {
            "status": "REVIEW_ONLY_NO_LIVE_NETWORK_CHANGE",
            "current": {"host": gw.gw["coordinator_host"],
                        "port": gw.gw["coordinator_port"]},
            "proposed": {"host": payload.coordinator_host,
                         "port": payload.coordinator_port},
            "warning": "IT must approve SLZB-OS network change, server routing, backup and Z2M serial.port update before cutover."
        }

    return router
