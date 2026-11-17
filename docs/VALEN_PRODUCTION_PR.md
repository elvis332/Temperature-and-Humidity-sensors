# Valen review: Sander Zigbee production deployment (PR bundle)

**Review first; do not execute on the factory server until IT/Valen approves.**
This repository contains the bridge and an EMS integration patch, **not** the full EMS application repository. After approving this PR, Valen must apply/review the EMS patch on the actual EMS staging branch and open its own application PR if that is a separate repository. The current local EMS preview is not a production backend.

## Verified pilot baseline (2026-11-17)
- SLZB-06MU on Ethernet 192.168.50.20:6638 (PC adapter 192.168.50.10), Silicon Labs radio 7.3.1.0 / EZSP v12; Zigbee2MQTT 2.14.3, zigbee-herdsman 11.2.0, Node 24.20.0, adapter **ezsp**. Do **not** change to ember on this firmware. Firmware upgrade is a separate approved maintenance item.
- TH-02 (SONOFF SNZB-02D) has automatically rejoined at least once after coordinator power loss. At 2026-11-17 15:59 Taiwan, verified MQTT and Modbus values 27.3 C, 57.6%RH, battery 100%, LQI 255. This proves a successful event, not full production resilience.
- Read-only bridge: MQTT 127.0.0.1:1883 -> Modbus 127.0.0.1:1502 Unit 1. Existing EMS Modbus reader successfully decoded four points. Local Environment UI/battery preview has been built; production SQL/dashboard runtime acceptance is pending.
- WTR10-E/TH-01 is existing working equipment; **never overwrite or modify** it. Sensor placement architecture is already agreed and remains unchanged.

## 1. Security and cutover preconditions
1. Confirm server OS, allowed applications, WinSW version, service account (least privilege), real Mosquitto Windows service name, Windows Application Control and approved Node/Python versions. Install WinSW only from approved corporate source.
2. Reserve/verify proposed production coordinator address **192.168.35.11**, TCP 6638 accessible from server. No static IP change in this PR. Keep 192.168.50.20 until cutover approval.
3. Back up **entire** existing Zigbee2MQTT data folder (including configuration.yaml, database.db, state files, network keys, coordinator_backup.json if present) and SLZB settings/firmware inventory. Stop the development instance before the production instance opens TCP 6638. Never run two Zigbee2MQTT instances against one coordinator.
4. Preserve Zigbee PAN ID, extended PAN ID, channel, network key, device database and friendly names. Never reset coordinator or automatically enable Permit join.
5. Broker uses localhost listener and IT-approved authentication/ACL. Secure service credentials outside Git; configure Zigbee2MQTT MQTT authentication in protected runtime config, and bridge/watchdog via protected environment variables MQTT_USER/MQTT_PASSWORD (and TLS if required). Never commit secrets.
6. With all services co-located, bind Modbus to 127.0.0.1 only. Keep port 8080 frontend loopback; remote management via approved reverse proxy/tunnel if required.

## 2. Install production software (Valen only)
Directory model (paths in service XML must be adjusted if IT chooses alternatives):
- C:\Sander\zigbee2mqtt : approved built Zigbee2MQTT runtime and preserved data path C:\Sander\Config\zigbee2mqtt
- C:\Sander\ZigbeeBridge : checkout of this repository plus .venv, requirements.txt installed
- C:\Sander\Config\zigbee-bridge.json : private copy of bridge/config.production.example.json
- C:\Sander\Config\zigbee-recovery.json : private copy of deploy/recovery.example.json
- C:\Sander\Services : approved WinSW executable + tailored XML template per service
- C:\Sander\Logs : ACL-limited rotating logs

Start order: Mosquitto -> Zigbee2MQTT -> bridge -> existing EMS collector using the **normal company deployment**. Use existing SQL Server only in an approved staging/production context, never from the developer PC.

Zigbee2MQTT configuration: **do not replace configuration.yaml** with example YAML. While stopped, edit just mqtt server/credentials, serial.port to approved coordinator address, serial.adapter=ezsp, advanced.last_seen=ISO_8601, frontend localhost, availability.enabled=true and availability.passive.timeout=15 (minutes). Preserve all generated network identity and device mappings. Device availability is supplemental: read-only bridge independently rejects stale timestamps.

Production staleness is provisionally 900 seconds, based on pilot observations of reports approximately 1–2 minutes apart. Observe a full 24–72 hours in actual installations and tune both Zigbee2MQTT passive timeout and bridge offline_seconds to avoid false alarms; battery devices can report less often when stable. EMS UI's own grace period and collector polling interval are separate controls. Document final threshold with Valen.

Install WinSW service wrappers from deploy/zigbee2mqtt-service.xml and deploy/bridge-service.xml after verifying actual paths, dependencies, credentials, log paths and running one successful foreground test. Configure Mosquitto's Windows service automatic startup/recovery with IT. WinSW handles process crashes; a separate supervisor handles stopped services and repeated unresponsive port health. Do not duplicate service restarters.

## 3. Server watchdog: reviewed Scheduled Task at system boot
Run from an **elevated, IT-approved** PowerShell on the server after both WinSW services exist:

    powershell.exe -NoProfile -File C:\Sander\ZigbeeBridge\deploy\Install-SanderWatchdogTask.ps1

This command is dry-run by default and validates configuration and service names. After Valen accepts it:

    powershell.exe -NoProfile -File C:\Sander\ZigbeeBridge\deploy\Install-SanderWatchdogTask.ps1 -Apply

Creates **Sander-Zigbee-Recovery** under SYSTEM at OS startup (not dependent on login). Writes rolling audit logs to C:\Sander\Logs\ZigbeeRecovery\supervisor.log and uses service control manager. It checks every 15 seconds and after repeated failures/cooldown can restart the specifically named Zigbee2MQTT and bridge Windows services only if their upstream dependencies are reachable. It does NOT start ad hoc node.exe, reset Zigbee, open pairing, change hardware, restart the broker or touch EMS SQL. A silent sensor only raises a warning, not a restart loop. The older per-login **Sander Zigbee Watchdog** must be disabled first; installers refuse simultaneous active supervisors.

The watchdog requires service control permissions; the installer uses an elevated SYSTEM task and must be approved by IT. Review Task Scheduler security, auditing, event history and service ACLs before sign-off. If IT prefers an approved Windows watchdog service, do not also install the Scheduled Task.

## 4. EMS application integration: separate approval gate
The existing app is *not* in this GitHub repository; do not pretend this PR has modified it. Valen must use the actual EMS staging source, never the server's live production checkout for an initial patch.

1. Obtain current EMS branch/ZIP, review the actual Devices, Modbus source, telemetry schema, Environment API and UI. Check compatibility using:
       py -m bridge.verify_ems PATH_TO_CURRENT_EMS.zip
2. Run dry-run: py integrations/modbus/apply_ui.py PATH_TO_DISPOSABLE_EMS_COPY
3. Only with matched source anchors, apply: py integrations/modbus/apply_ui.py PATH_TO_DISPOSABLE_EMS_COPY --apply
4. Review diff for backend/app/api/routes/environment.py, frontend/src/pages/EnvironmentPage.jsx and BatteryIcon.jsx, plus config/profiles/SNZB02D.yaml. Never change WTR10E.yaml, existing TH-01 records, the lighting controller, or production .env.
5. Run Python compile, frontend npm CI/build, backend route tests and approved staging SQL integration. Register TH-02 via existing Devices UI, communication modbus_tcp, profile SNZB02D, 127.0.0.1:1502, Unit ID 1; apply point alarm_min 20 on battery_pct. Check that LQI is available for diagnostics but not shown as a primary Environment chart.
6. Verify actual persistent data, historical charts, threshold, stale/unavailable state, recovery and access permissions in EMS staging. Only then propose the EMS application PR for Valen to accept and merge.

The developer-PC-only preview (port 5175) uses an isolated API and volatile history; **it is not evidence of production SQL integration**.

## 5. Acceptance tests and rollback
- Fresh TH-02 report updates MQTT last_seen, Modbus registers 0–3, and actual EMS persisted values and charts. Compare LCD.
- Stop Zigbee2MQTT Windows service: check WinSW/SCM and supervisor recover it; a service lock/healthy instance does not trigger a second process.
- Broker interruption: bridge reports offline/no fresh registers (Modbus exception 0x0b) and later resumes automatically; no stale values displayed as live.
- Coordinator power interruption: no automated pairing/reset, preserved network identity; TH-02 rejoins and live data resumes **without touching sensor button**. Record actual recovery latency over repeated trials.
- Sensor remains offline: EMS warns and preserves last good historical data, never fabricates fresh points.
- Server reboot, including before login: broker/Zigbee2MQTT/bridge/supervisor start, fresh MQTT -> Modbus -> EMS resumes, logs persist.
- Battery warning threshold inclusive <=20%; existing wired WTR10-E/TH-01 and lighting unaffected.
- Stability observation: at least 24 hours after commissioning, preferably 72 hours to tune battery sensor report intervals and alert thresholds.

Rollback: stop supervisor Scheduled Task, stop the new WinSW services and restore approved pre-cutover Zigbee2MQTT data backup and coordinator IP only via IT change procedure. Revert the EMS integration commit in its own application repo if needed. Do not delete/re-pair sensors as part of rollback and do not touch wired telemetry.

## Explicit review blockers
- Actual EMS repository/branch and its target SQL Server staging environment are not connected here. Valen must test/approve integration in that repository separately.
- Server address 192.168.35.11, service credentials, broker ACL, full reboot behavior, and production 24+ hour endurance remain unverified.
- Legacy EZSP is a compatibility exception for current 7.3.1.0 firmware. Ember migration requires approved firmware upgrade and backup plan; not bundled in this PR.
