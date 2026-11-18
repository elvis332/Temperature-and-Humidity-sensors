# Modbus deployment / development guide (production candidate)

**Production reviewers:** see [Valen's production PR review, staging and rollback guide](VALEN_PRODUCTION_PR.md) before installing anything.

Do not run EMS collectors or aggregation locally. The local EMS .env points to production SQL. The standalone bridge contains no SQL/EMS imports. The old direct MQTT/SQL ingestion path has been removed from the current source tree.

## PC testing
Approved Mosquitto and Python 3.10+ with paho-mqtt 2.x. Use a local-only MQTT listener 127.0.0.1:1883. If the existing broker is bound only to a LAN address, update bridge/config.test.json and set MQTT_HOST in the simulator to that address, or have the approved local listener configured. Keep production broker isolated.
Run from repo root:
```powershell
py -m pip install -r requirements.txt
py -m unittest bridge.test_bridge -v
py -m bridge.bridge
# separate terminal
py -m bridge.simulate
py -m bridge.probe
```
Expected synthetic result: -2.5 C, 61.2%RH, 85%, LQI 180. After 15 seconds with no new reports, probe must return exception 0x0b. Test never starts EMS or touches SQL.

## Hardware
Power SLZB-06MU with Ethernet PoE or approved 5V USB-C. Set Zigbee coordinator/Ethernet mode, reserve IP and check TCP 6638. Confirm radio firmware and adapter type in device UI; current 7.3.1.0 firmware uses legacy ezsp; ember requires approved firmware upgrade. Install Zigbee2MQTT using an approved supported Windows method. Previous pnpm was blocked by Device Guard; do not circumvent security policy.
Configure Zigbee2MQTT using bridge/zigbee2mqtt.example.yaml (replace IP; confirm version/schema and firmware: 7.3.1.0 / EZSP v12 currently requires ezsp), including advanced.last_seen ISO_8601. Pair one SNZB-02D by holding its pairing button 5 seconds; rename TH-02; close permit join. Watch MQTT topic zigbee2mqtt/TH-02 and verify temperature, humidity, battery, linkquality and timestamp. All four fields must be received before the four-register profile can read successfully. Wake the sensor to obtain missing battery data if required. Compare LCD in Celsius with Modbus probe after a fresh report. Never invent missing values.

## Production — Valen only
Record exact installed versions: Mosquitto ___, Zigbee2MQTT ___, Node.js ___ (supported by release), pnpm ___ (release packageManager), Python ___, paho-mqtt ___, SLZB firmware ___. Use validated versions, not untested latest. Install Mosquitto as Windows service, Zigbee2MQTT and bridge using an IT-approved service wrapper (e.g. WinSW) with restart policies, dedicated service account, absolute executable/working/data paths, log rotation, and service dependencies on Mosquitto. Bridge start: Python executable -m bridge.bridge with BRIDGE_CONFIG pointing to absolute production JSON; environment secrets outside Git. Keep MQTT and Modbus bound to loopback when all services share server; secure MQTT with authentication/TLS as required. Set Zigbee2MQTT data directory and credentials; back up its network keys and coordinator data separately. Start broker, coordinator service, bridge, then existing EMS collector via normal production procedure. Do not start aggregation locally.
Copy profile config/profiles/SNZB02D.yaml into EMS; register each sensor in Devices with model SNZB02D, bridge IP 127.0.0.1, port 1502, unique unit ID (1–247). Do not overwrite TH-01 or WTR10E.yaml. Match topic/unit mapping to bridge production config; set per-device battery threshold and bridge offline timeout; restart bridge after config change. EMS UI stale grace is a separate 120-second default after the last successful collector event; actual display delay is bridge timeout plus UI grace and refresh. Use provisional 900-second Zigbee timeout, based on 2026-11-17 pilot reports about 1–2 minutes apart; revise after 24–72 hour observation. Preserve the already agreed factory sensor placement architecture.
Apply UI patch on a disposable EMS source copy, dry-run first: py integrations/modbus/apply_ui.py PATH_TO_EMS; add --apply only after checking. Review source diff. Set each battery point alarm_min in the existing Devices Points tab (default 20, inclusive red icon); no new threshold editor is required. UI stale grace is configured separately via settings_json.environment.offline_grace_seconds; a dedicated editor and validation for that grace remain to be implemented. LQI profile point is intended for existing Devices diagnostics; verify it is visible there and absent from Environment. Verify bilingual UI and build in approved dev environment without production DB. Deploy only after acceptance tests, LCD comparison, range survey, and approval.
