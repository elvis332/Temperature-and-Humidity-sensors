# Sander EMS Zigbee Devices and Advanced Maintenance — Valen staging integration

**Code delivered in this PR:** multi-gateway discovery, bounded pairing, sensor registration proposal, approved settings, admin-only API route factory, native dashboard link contract, Devices React component, and guarded bridge sensor registry hot reload.

**NOT YET LIVE IN THE MAIN EMS:** The actual Sander EMS source repository is not accessible here. Its existing administrator dependency, audit logger, Devices API/SQL transaction, CSRF handling, and routing are application-specific and MUST be integrated and tested by Valen on the approved staging branch. The Zigbee management component deliberately refuses unsupported SQL registration or unsafe native management access rather than bypassing them.

## 1. Architecture

    Sensor(s) SNZB-02D -- Zigbee --> GW01 SLZB-06MU Ethernet TCP :6638
                                     --> Zigbee2MQTT service GW01
                                     --> Mosquitto broker (loopback)
                                     --> read-only gateway Modbus bridge :1502
                                     --> existing EMS telemetry reader / SQL history
                                   \--> authenticated EMS Zigbee admin controller

    Another coordinator GW02 --> Zigbee2MQTT service GW02 (distinct base topic)
                               --> bridge :1503 --> SAME existing EMS Devices model
                               --> SAME EMS Zigbee admin controller

A newly installed coordinator can start with zero paired sensors. The existing site registry now allows that. Initial pairing needs the battery device's button and a short join window; later restarts/rejoins should be automatic without re-registering. Each physical coordinator has one Zigbee2MQTT owner. SLZB-06MU uses Ethernet/PoE, NOT RS-485 Modbus. The built-in MQTT toggle in SLZB-OS can stay OFF; the external Zigbee2MQTT service publishes MQTT.

## 2. EMS backend mount (Valen must review current source)

Install this repository as a reviewed Python package into the approved EMS staging backend environment, not into the developer computer's production-SQL-linked environment:

    py -m pip install -e "C:\Sander\ZigbeeBridge[ems]"

Integration pseudocode (must be adapted to the CURRENT EMS router and actual admin/audit helpers; DO NOT paste over app startup blindly):

    from integrations.ems.zigbee_control import ZigbeeFleet
    from integrations.ems.zigbee_api import create_admin_router

    fleet = ZigbeeFleet(
        approved_site_manifest,
        credentials={"GW01": r"C:\Sander\Config\mqtt-admin-GW01.auth.json"},
        broker="127.0.0.1",
    )

    # Add fleet.start() and fleet.close() to existing FastAPI startup/shutdown.
    # Inject the existing EMS security dependency which FAILS for non-admins.
    # Inject the existing authenticated audit logger.
    router = create_admin_router(
        fleet,
        require_ems_admin=existing_ems_require_admin,
        audit_change=existing_ems_audit_write,
        register_transaction=None,
        native_proxy_paths={},
    )
    existing_api_router.include_router(router)

The router prefix is /admin/zigbee; if the EMS app's API router uses /api, full URL becomes /api/admin/zigbee. No independent login or bypass routes are introduced. For cookie-based EMS auth, enforce the same existing CSRF protections on all management POSTs; the React component accepts a csrfToken prop. Never disable CSRF to make it work.

Backend API operations already implemented:
- GET /gateways : live MQTT and Zigbee2MQTT status, coordinator network endpoint, counts
- GET /gateways/{gateway}/devices : discovered devices from Zigbee2MQTT bridge/devices
- GET /gateways/{gateway}/events : recent pairing/interview events
- GET /gateways/{gateway}/advanced : secure proxy path or "not configured"
- POST /gateways/{gateway}/permit-join : maximum 60 seconds, or 0 to close
- POST /gateways/{gateway}/devices/{ieee}/expose : allowlisted comfort limits and calibration, requires supported writable expose; sending to sleeping device does not prove it applied
- POST /gateways/{gateway}/devices/{ieee}/option : narrow approved Zigbee2MQTT device options
- POST /gateways/{gateway}/network/propose : reviewed change proposal ONLY; never writes SLZB IP or gateway config
- POST /registration/plan : review-only SNZB-02D mapping with free Modbus ID, unique IEEE, physical location
- POST /registration/commit : explicitly 501 until real EMS database + bridge registration transaction is supplied; DOES NOT write SQL automatically

Every route is protected by EMS admin dependency, and every write request logs a pre-command audit event. If the EMS audit service is unavailable, management writes are denied.

## 3. EMS Devices page (Valen staging only)

The new component is integrations/ems/ZigbeeAdminPanel.jsx.

Option A: after reviewing the current DevicesPage.jsx, add an administrator-only Zigbee tab and import the component. Pass the existing EMS CSRF token if applicable. Render only to authorized admins; server-side API authorization still applies.

Option B: place this EXACT marker inside the existing administrator Devices JSX:

    {/* SANDER_ZIGBEE_ADMIN_SLOT */}

Then run the staging-only patch (dry-run by default):

    py integrations/ems/apply_devices_page.py C:\PATH\TO\DISPOSABLE_EMS_CHECKOUT
    py integrations/ems/apply_devices_page.py C:\PATH\TO\DISPOSABLE_EMS_CHECKOUT --apply

It copies the React component beside DevicesPage.jsx and inserts the mount. The script refuses to modify an unknown page without this marker. Review git diff, app CSS/spacing, auth/CSRF integration and frontend build. The new panel does NOT start the production EMS backend, collector or SQL from a development computer.

## 4. Native Zigbee2MQTT Advanced Maintenance

The full native UI includes Exposes, Reporting, Bind, Groups, Settings, Device Interview, Logs and other functions. Exposing its port 8080 to everyone is unsafe. Keep each Zigbee2MQTT frontend bound to 127.0.0.1:8080 (GW01), :8081 (GW02) etc.

Valen/IT sets up HTTPS **same-origin admin-only reverse-proxy** for each frontend with WebSocket upgrade and real EMS session authorization on BOTH regular HTTP and WebSocket requests. Suggested paths:
- /admin/zigbee/native/GW01/
- /admin/zigbee/native/GW02/

Only after this route is independently secured should the path be passed to create_admin_router(native_proxy_paths=...). This code checks the path format, and the Devices component only displays the advanced link after it is configured. Do not ship a public 8080 URL, tokens or credentials to the browser. Do not expose unreviewed Zigbee external JavaScript converters, OTA firmware or reset buttons to non-admins. Use Zigbee2MQTT's native security settings plus trusted EMS authentication, subject to Valen's actual reverse-proxy capabilities.

## 5. Registration commit and continuous telemetry

This PR supplies registration plans and mapping checks, but **the SQL registration implementation depends on current EMS source**. The optional register_transaction adapter is the exact integration point. It must use existing EMS Devices models/API, preserve wired WTR10-E/TH-01, check duplicate device IDs and IEEE addresses, and coordinate BOTH:
- A successful EMS device record using existing Modbus TCP source profile SNZB02D, with gateway bridge host/port and allocated unit ID.
- An authorized atomic update to the gateway bridge JSON mapping file. The bridge polls for validated changes every 10 seconds and subscribes newly approved sensor topics WITHOUT restarting Zigbee2MQTT. It refuses silent Modbus unit/topic identity remaps.

An EMS SQL transaction and a file update cannot automatically be one atomic operation. Implement compensating rollback and idempotency for this external registration workflow, then test repeated registration, failures, retry, and collector history before enabling registration_commit_enabled. Until this adapter is proven, registration remains a REVIEW proposal (no false claim of live registration).

For sensors already paired and registered, fresh readings flow automatically to the Modbus bridge and existing EMS polling after normal restarts. Values with stale last_seen are rejected. Battery alarms (default 20%) and offline views require integration of the previously supplied Environment patch into the CURRENT EMS app.

## 6. Broker credentials and server security

IT must provision a separate secret JSON credential for the EMS management client per gateway:
- C:\Sander\Config\mqtt-admin-GW01.auth.json
- C:\Sander\Config\mqtt-admin-GW02.auth.json

The broker ACL must grant read on the exact gateway base_topic/bridge info, devices, state, events and responses; write only to approved bridge request topics and device set topics as required. Never share broker credentials with the React frontend or commit them to Git. The one-click server preflight checks secret files and approved server settings but does not create identities or lower network permissions.

Device radio firmware remains working EZSP v12 with adapter ezsp until a separate tested firmware migration. Zigbee2MQTT remains a Windows service; the browser tab is not responsible for keeping it alive. Distinguish the SLZB OS MQTT switch from the external Zigbee2MQTT MQTT broker.

## 7. Production acceptance gates

- Non-admin cannot call ANY API path, initiate pairing or access native frontend, including its WebSocket endpoint.
- Multiple gateways with different topics and Modbus endpoints; one Zigbee2MQTT process per coordinator.
- Add an empty gateway, join SNZB-02D with its physical button, observe new IEEE, create registration plan, activate the approved EMS registration transaction once implemented.
- Confirm live temperature, RH, battery, LQI and truly fresh last_seen; test sleeping sensor changes and return-to-online.
- Confirm actual SQL-backed historical records, alarms and report charts, with no regressions to wired devices or lighting.
- Confirm existing registration IDs remain stable after changing names, restarts or adding sensors.
- Reboot Windows BEFORE user login; services, MQTT, bridge and EMS admin management must reconnect automatically. Log faults and confirm sensor recovery.
- Stop/restart and physical coordinator power loss tests, plus 24–72 hours of stability before production approval.
- Keep protected full Zigbee network backup, Windows service rollback, EMS rollback and IT change record.

References: Zigbee2MQTT official MQTT Topics and Messages, Security, Exposes and Frontend documentation.
