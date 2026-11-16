# Resume here — hardware commissioning

## Recorded state (2026-11-16)
- SLZB-06MU and SNZB-02D available. Coordinator AP was accessible at 192.168.1.1. Reported core firmware v3.2.6.dev3, radio firmware 20231030; recheck.
- Development PC company Ethernet 192.168.21.123; secondary adapter 192.168.50.10/24. Proposed coordinator 192.168.50.20 never answered ARP/TCP; **not a confirmed address**.
- pnpm.exe blocked by Device Guard; npm Zigbee2MQTT onboarding attempted, normal startup unverified. Use approved supported installation. Do not bypass policy.
- WTR10-E working; leave unchanged. Never start local EMS collector or aggregation: .env points to production.

## Resume sequence
1. Establish Ethernet via approved DHCP network or isolated router; obtain actual coordinator IP from lease/MAC. Restore DHCP on secondary PC adapter if using DHCP. Do not change main company adapter.
2. Confirm web and TCP 6638: `py -m bridge.preflight --coordinator VERIFIED_IP` (also checks local MQTT). Do not use a guessed IP.
3. Configure approved Zigbee2MQTT using bridge/zigbee2mqtt.example.yaml. Match radio firmware and adapter to installed version; old firmware may require approved upgrade for ember. Back up before firmware changes.
4. Enable last_seen ISO_8601, pair SNZB-02D, rename TH-02, disable permit join. Verify zigbee2mqtt/TH-02 payload: temperature, humidity, battery, linkquality, last_seen.
5. Stop simulator/test bridge. Copy bridge/config.production.example.json to a private local config outside Git. Set BRIDGE_CONFIG to absolute path; confirm actual MQTT host and loopback Modbus 1502. Start `py -m bridge.bridge`. No SQL.
6. Run `py -m bridge.probe --unit 1`; compare temperature/RH with LCD, verify battery/LQI. Observe real report cadence, tune offline timeout, verify stale exception/recovery.
7. Complete docs/RANGE_TEST.md, including dead zones; no router until measured.
8. Verify EMS UI build in isolated approved dev environment; Valen deploys Windows services only after acceptance.

## Repeatable software tests
```powershell
py -m pip install -r requirements.txt
py -m unittest bridge.test_bridge -v
py -m bridge.verify_ems "PATH_TO_SanderEMS.zip"
py -m bridge.preflight
```
Optional real-broker smoke test: `py -m unittest bridge.test_mqtt_integration -v` against isolated localhost Mosquitto. The source compatibility test extracts only six explicit source files; never .env, database files, collector, or aggregation. Record test results and exact installed versions.

## Acceptance state
Isolated actual EMS reader test exercised negative temperature, two unit IDs, offline and recovery with synthetic payloads. UI source anchors checked. Hardware, MQTT broker end-to-end, frontend build/runtime, Windows service installation and range measurements still require verification. No production database access or equipment writes.
