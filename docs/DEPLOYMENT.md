# Developer PC → IT server handoff

The GitHub repo is the transfer source. Keep passwords and real MQTT payloads out of version control. The supplied Sander EMS ZIP remains a separate codebase.

## Current developer PC

Mosquitto: `192.168.21.115:1883`, Windows, temporarily unauthenticated LAN test. Run `python -m src.collector` and `python -m src.simulator` in separate terminals, then `python -m src.status`. Only simulated data enters local SQLite.

## Later installation in Sander EMS (NOT complete yet)

1. Merge `integrations/sanderems/config/profiles/SNZB02D.yaml` into the **existing** EMS `config/profiles` folder.
2. Register each Zigbee sensor in the existing EMS Devices page, IDs `TH-02` onward; **TH-01 is the existing WTR10-E**, do not overwrite it. Choose profile `SNZB02D` and set the floor and alarm thresholds. Register the points in EMS; the EMS historian rejects unknown device IDs.
3. Configure Zigbee2MQTT to use the broker, the SLZB-06M `ember` adapter, and a matching friendly name for each mapped MQTT topic.
4. Configure the collector with `mode: live`, authenticated internal MQTT endpoint, then run it from an environment where `backend.app` imports resolve (e.g. with the EMS project root on `PYTHONPATH`). Only after SQL schema and integration tests succeed, enable `python -m src.collector --ems`.
5. Verify retention policy, database privileges, Windows service startup, offline behavior, alarm/alert history, and selected frontend changes.
6. Configure broker firewall allowlist and TLS or secure network isolation. Do not deploy anonymous LAN MQTT to production.

## Safety / acceptance gates

- Simulated and live records must remain distinguishable.
- No automatic AC actions.
- SQL delivery failures currently require additional retry/replay testing before production. Do not assume continuous data persistence merely because local SQLite tests pass.
- Zigbee pairing, floor-to-floor RF coverage and real payloads cannot be verified until coordinator and sensors arrive.
