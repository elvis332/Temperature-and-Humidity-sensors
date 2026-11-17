# Sander Temperature & Humidity — Production candidate

**Status:** feature branch prepared for Valen/IT review; not deployed or merged to the EMS production system.

Live pilot verified 2026-11-17: SONOFF SNZB-02D (TH-02) -> SLZB-06MU Ethernet coordinator (192.168.50.20:6638, firmware 7.3.1.0 EZSP v12) -> Zigbee2MQTT 2.14.3 (legacy ezsp) -> local Mosquitto -> read-only Modbus bridge (127.0.0.1:1502 Unit 1). Fresh measurements (27.3 C, 57.6%RH, battery 100%, LQI 255) reached the actual EMS Modbus source reader. Automatic sensor rejoin occurred once after power restoration; production endurance remains unverified.

**Begin with [Valen's production PR review and acceptance instructions](docs/VALEN_PRODUCTION_PR.md).** For the failed developer-PC watchdog task (Ready, exit result 1), see [local task diagnosis and guarded repair](docs/WATCHDOG_RECOVERY.md).

## Key files
- bridge/bridge.py and bridge/config.production.example.json — read-only MQTT-to-Modbus bridge with 900-second provisional freshness cutoff, rejects stale/replayed reports.
- config/profiles/SNZB02D.yaml — four-register EMS profile for temperature, humidity, battery and LQI.
- integrations/modbus/apply_ui.py and BatteryIcon.jsx — additive EMS Environment integration, battery warning icon. Apply only on a disposable EMS staging checkout after reviewing anchors.
- deploy/zigbee2mqtt-service.xml and bridge-service.xml — IT-approved WinSW service templates; auto-start on reboot.
- deploy/recovery_supervisor.py — supervises only approved Windows service names; observes sensor freshness, never resets/re-pairs devices.
- deploy/Install-SanderWatchdogTask.ps1 — boot-time SYSTEM Scheduled Task installer; dry-run by default and only acts with explicit -Apply.
- deploy/recovery.example.json — production host/port/service names and sensor timeout.
- deploy/zigbee2mqtt.production-settings.example.yaml — review-only config excerpt, **not** replacement for existing network identity.

## Tests
    py -m pip install -r requirements.txt
    py -m unittest bridge.test_bridge deploy.test_recovery_supervisor deploy.test_contract -v
    py -m bridge.verify_ems PATH_TO_EMS_SOURCE.zip

GitHub Actions also runs isolated MQTT smoke tests. The final EMS runtime/API, database, 24-hour stability, Windows reboot and physical recovery acceptance tests are approval gates, not yet completed.

## Security / preservation
Do not start local EMS collectors or aggregation: existing local EMS .env targets production SQL Server. This bridge contains no EMS database connection. Keep production broker/Modbus local to server. Do not change the wired WTR10-E/TH-01, the current sensor placement plan, network keys, or Zigbee pairing. One and only one Zigbee2MQTT instance may access each coordinator. The working firmware requires legacy ezsp; ember upgrade is a separate IT-approved maintenance action.

This repository is the **sensor bridge/integration repository**, not the full Sander EMS source repository. Valen must separately review/apply the EMS source patch in the actual EMS staging branch before production merge.
