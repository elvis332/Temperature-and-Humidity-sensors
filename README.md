# Sander Temperature & Humidity — Zigbee MQTT integration

**Status: v0.1 development / simulated sensor testing. No SLZB-06M hardware yet.**

This repository adds **SONOFF SNZB-02D → SLZB-06M → Zigbee2MQTT → Mosquitto** to the existing SanderFactoryEMS. The successful WTR10-E/Modbus path remains unchanged.

## Principles
- **One EMS:** devices remain `environment_sensor` with point keys `temperature_c`, `humidity_pct`; battery is `battery_pct`.
- **Separate input adapters:** the existing WTR10-E collector stays intact; Zigbee MQTT has its own collector.
- **No fake production data:** simulated payloads are marked `_simulated: true`, stored only in a development SQLite database, and blocked from the EMS SQL sink.
- **Per-sensor policy:** independent temperature/humidity limits, rapid-change thresholds, and loss-of-signal timers.
- **No automatic actuation:** a future AC control adapter may consume approved alarm events, but no AC commands are implemented or enabled.
- **Portable:** code in GitHub; broker IP/password, sensor mapping, and production settings stay outside application logic.

## Local test (Windows)
Python 3.10+ and Mosquitto already installed. Edit `config.json` to match the broker IP (`192.168.21.115` for the current development PC). This is an unauthenticated **temporary** LAN test only.

```powershell
py -m pip install -r requirements.txt
py -m src.collector
# Separate terminal:
py -m src.simulator
# After publishing:
py -m src.status
py -m unittest discover -s tests -v
```

**Hardware transition:** change `mode` from `simulation` to `live`, stop the simulator, install the SMLIGHT SLZB-06M + Zigbee2MQTT, pair devices, and assign Zigbee2MQTT friendly names matching `config.json` topics. The same payload parsing and alarm rules will be used. Actual end-to-end hardware validation remains required.

## Project map
- `src/engine.py`: MQTT payload checks, SQLite historian, persistent alarm transitions
- `src/collector.py`: Paho MQTT subscription and offline watchdog
- `src/simulator.py`: synthetic SNZB-02D-like JSON publisher
- `src/status.py`: CLI for readings and active alerts
- `src/ems_sink.py`: opt-in live-only adapter to existing EMS `IngestionService`
- `config.json`: development broker, registered topics, per-sensor settings
- `integrations/sanderems/config/profiles/SNZB02D.yaml`: model profile for the existing Devices page
- `docs/ARCHITECTURE.md`: integration contract and planned UI/controls
- `docs/DEPLOYMENT.md`: move from developer PC to company Git

## EMS source reviewed
The provided `SanderEMS-main(2).zip` includes `config/profiles/WTR10E.yaml`, `backend/app/telemetry/ingestion.py`, `backend/app/api/routes/environment.py`, and `frontend/src/pages/EnvironmentPage.jsx`. Those files are **not** copied into this repository and are not modified in this stage.

**Release gate:** simulation tests are not proof of a working Zigbee radio, SQL Server integration, or real AC control. Production setup requires authorization, device registration, schema compatibility tests, authenticated MQTT, firewall rules, and alarms tested with real devices.
