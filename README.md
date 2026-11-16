# Sander Temperature & Humidity — Modbus bridge baseline (2026-11-16)

**Active baseline: main — November 16, 2026.** The superseded direct MQTT/SQL prototype is removed from the current source tree. Do not run EMS collectors or aggregation locally: the EMS .env connects to production.

SNZB-02D -> SLZB-06MU (Ethernet) -> Zigbee2MQTT -> Mosquitto -> read-only MQTT/Modbus TCP bridge -> existing EMS collector.

## Local isolated test
Run these from the repo root:
```powershell
py -m pip install -r requirements.txt
py -m unittest bridge.test_bridge -v
py -m bridge.bridge
# separate terminal, while bridge is running
py -m bridge.simulate
py -m bridge.probe
```
Default broker: 127.0.0.1:1883; test topics sander-test/TH-02 and TH-03; Modbus 127.0.0.1:1502. If your broker listens on another address, update bridge/config.test.json and set MQTT_HOST for simulator. Test result expected: -2.5°C, 61.2%RH, 85%, LQI 180; after 15 seconds no fresh report, Modbus exception 0x0b. No SQL access.

## Files
- bridge/bridge.py — FC03 read-only server with topic/unit mapping, validation, staleness, retained-message protection.
- bridge/config.test.json / config.production.example.json — distinct namespaces, timeouts.
- bridge/zigbee2mqtt.example.yaml — Ethernet coordinator example, last_seen enabled.
- bridge/probe.py / simulate.py / test_bridge.py — independent test tools.
- config/profiles/SNZB02D.yaml — Modbus registers 0 signed temp ×10, 1 humidity ×10, 2 battery %, 3 LQI.
- integrations/modbus/ — additive EMS UI patch, five-segment battery icon.
- docs/MODBUS_DEPLOYMENT.md — Valen's installation and sensor onboarding guide.
- docs/RANGE_TEST.md — RF measurement template; no router until measured.

## Acceptance
- No changes to WTR10-E and no local production database access.
- Hardware, LCD comparison and range survey pending.
- Confirm approved installation of Zigbee2MQTT; previous Windows Device Guard restricted pnpm.
- Verify UI in an isolated dev copy, configurable battery threshold and offline timing, LQI on Devices only.
- Valen performs production deployment as Windows services after approval. Record exact software versions at commissioning.
