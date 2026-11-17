# Commissioning state — 2026-11-17

For the production rollout and acceptance plan, see [VALEN_PRODUCTION_PR.md](VALEN_PRODUCTION_PR.md).

## Verified local pilot
- SLZB-06MU is reachable at **192.168.50.20:6638**, dedicated PC adapter 192.168.50.10. This is the actual live pilot, not the proposed production address.
- Zigbee2MQTT 2.14.3 / zigbee-herdsman 11.2.0 with working **ezsp** driver. Radio reports firmware **7.3.1.0 build 176, EZSP v12**. Ember cannot initialize against this version; do not switch until Valen separately approves a radio firmware upgrade.
- SNZB-02D **TH-02** has rejoined automatically after coordinator power interruption at least once. At 2026-11-17 15:59:31 Taiwan time, fresh MQTT message: 27.3 C, 57.6%RH, 100% battery, LQI 255. Probe on 127.0.0.1:1502 Unit 1 decoded the same values.
- Local MQTT broker 1883, Z2M UI 8080, Modbus bridge 1502, recovery API 8002, preview UI 5175 were all accepting TCP connections. Developer PC has a per-login watchdog task but its continuous operation was not proved; it is not production service deployment.
- The local preview is not the actual SQL-backed production Environment endpoint. Original EMS .env points to production SQL. Do not start local collector/aggregator.
- Existing wired WTR10-E/TH-01 and factory placement architecture are unchanged.

## Critical deployment controls
- Back up original Z2M data and coordinator identity before any move; retain channel/PAN/network key, database and TH-02 ID. Stop dev instance before connecting production instance; only one process may own coordinator.
- Proposed production coordinator **192.168.35.11**, not yet approved/reserved by IT.
- Enable Z2M device availability for battery devices (passive 15 minutes pilot setting); matching bridge timeout 900 seconds, revise after 24–72 hour cadence observation to avoid false alarms.
- Use WinSW services for Mosquitto/Z2M/bridge process lifecycle and a startup Scheduled Task for conservative service-health supervision; do not migrate the old user-login watchdog task.
- Monitor software health separately from sensor freshness: an online MQTT socket or LQI reading cached at startup is not proof of a live sensor message. Sensor must produce a new last_seen timestamp.
- No automatic pairing, reboot loops for one sleeping sensor, coordinator factory reset or hardware writes.

## Verification commands (isolated)
    py -m unittest bridge.test_bridge deploy.test_recovery_supervisor deploy.test_contract -v
    py -m bridge.probe --unit 1
    py -m bridge.verify_ems PATH_TO_CURRENT_EMS.zip

Real broker smoke: python -m unittest bridge.test_mqtt_integration -v against approved isolated localhost Mosquitto. Original EMS staging source and SQL permissions are required for production-dashboard acceptance.
