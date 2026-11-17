# Windows deployment templates — for Valen/IT review

Start with [Valen production guide](../docs/VALEN_PRODUCTION_PR.md). These are templates, not installed services.

## Files
- zigbee2mqtt-service.xml: WinSW automatic process lifecycle for the validated Zigbee2MQTT version and preserved data.
- bridge-service.xml: read-only MQTT/Modbus bridge, dependent on Mosquitto.
- zigbee2mqtt.production-settings.example.yaml: compatible EZSP v12 settings excerpt only; never overwrite existing paired configuration.
- recovery_supervisor.py: conservative Windows service monitor (15-second checks; 4 repeated unhealthy checks, 5-minute restart cooldown), records TH-02 freshness without attempting re-pairing.
- recovery.example.json: private deployment config template; production address pending IT approval.
- Install-SanderWatchdogTask.ps1: guarded boot-time Scheduled Task under SYSTEM, independent of login. Dry run by default; use -Apply only with IT approval. Writes rotating audit logs.
- test_recovery_supervisor.py and test_contract.py: unit/contract tests.

Install approved WinSW from IT, place matching executable and XML in service folders, confirm actual paths, secured service account, broker name and ACLs. Keep broker and Modbus on loopback on one server. Don't put secrets in XML, scripts or Git. Broker/bridge/watchdog auth and TLS require Valen to supply approved runtime settings.

**Never run two Zigbee2MQTT instances against one SLZB-06MU.** The old development per-login Scheduled Task named "Sander Zigbee Watchdog" must be disabled before activating production startup monitoring. Service recovery must work even before login and must be tested under physical and software failure conditions.

The recovery task does not restart individual battery sensors; their Zigbee rejoin behavior is firmware-managed. It logs stale sensors, while the existing Modbus bridge returns exception 0x0b for unavailable data. This is safer than fabricating live readings or initiating automated pairing.
