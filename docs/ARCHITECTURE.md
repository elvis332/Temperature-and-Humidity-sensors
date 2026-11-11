# Architecture & requirements

## Current paths

```text
WTR10-E --RS485--> Waveshare --> existing Modbus collector ---------+
                                                                      |
SNZB-02D ~Zigbee~> SLZB-06M --> Zigbee2MQTT --> Mosquitto --> MQTT adapter
                                                                      |
                                  existing EMS ingestion/validation/historian
                                                SQL Server
                                  Environment page + Devices page
```

No modifications to WTR10-E. No MQTT-to-Modbus bridge is necessary if the existing normalized EMS ingestion interface is used. The EMS Modbus collector presently skips non-`modbus_tcp` devices, so a separate MQTT subscriber is required.

## Compatible data contract

Zigbee2MQTT publishes JSON to `zigbee2mqtt/TH-02` (friendly name example):
```json
{"temperature":24.8,"humidity":52.3,"battery":95}
```

In development only, the simulator includes `"_simulated": true`.

The adapter maps to the existing EMS format:
```json
{"schema_version":"1.0","device_id":"TH-02","timestamp":"2026-11-11T11:00:00+08:00","source":"MQTT_ZIGBEE","quality":"GOOD","points":[{"key":"temperature_c","value":24.8,"unit":"°C","quality":"GOOD"},{"key":"humidity_pct","value":52.3,"unit":"%RH","quality":"GOOD"},{"key":"battery_pct","value":95,"unit":"%","quality":"GOOD"}]}
```

## Alarm and fault rules (per sensor)

- **Limits:** high/low temperature and relative humidity; comparisons are strict outside configured bounds.
- **Rapid changes:** significant changes between nearby readings (configurable difference and maximum gap).
- **Offline:** no fresh incoming reading for a configured interval. Zigbee battery sensors may only publish on change, so tune this interval from observed behavior; 3 minutes may create false alarms.
- **Recovery:** close active alerts when conditions return to normal; retain history for audit.
- **Quality:** reject malformed, non-finite, implausible, and unregistered topic data; do not record missing readings as zero.
- **Test isolation:** the development SQLite historian tags all readings as simulation, and `--ems` blocks simulation mode.

**Device limits in production:** the existing EMS Devices page already allows per-point alarm_min/alarm_max. We should use those as the single production source of truth rather than maintain competing rule settings in two databases. The settings in `config.json` are for isolated development tests.

## Frontend integration

The existing `frontend/src/pages/EnvironmentPage.jsx` already displays readings, alarm ranges, historical trend charts and offline status. Reuse it and add:
- severity badge and fluctuation annotation to each sensor card;
- explicit simulated/real indicator; the current API treats `simulation` as non-live, so the UI needs a controlled simulation preview without confusing it with real data;
- per-sensor low-battery and lost-signal labels;
- alert history and acknowledgement (future endpoint/table, not yet implemented);
- no automatic AC control UI until engineering/IT approval.

## Future AC controls — OFF by design

A later control path can be: alarm event -> rule engine -> approval/permissions -> device protocol adapter -> feedback from HVAC -> verify recovery. Require min-on/off cycle protection, hysteresis, manual override, safety interlocks, audit logs, and fail-safe limits. **The present project cannot write to AC or other equipment.** Initial implementation should only log a proposed action (dry run).

## Deployment separation

1. Development PC: simulated MQTT -> SQLite, no production SQL writes.
2. Live pilot: real Zigbee MQTT -> validated EMS ingestion and SQL Server, after registering devices.
3. Production: IT-run Windows service, authentication/TLS and monitoring; replace developer IP with server address via configuration.

## Existing EMS references

- `backend/app/api/routes/environment.py`: dashboard queries, alarm limits, staleness
- `backend/app/core/config_loader.py`: profiles, per-device overrides
- `backend/app/telemetry/ingestion.py`: source-agnostic persistence
- `config/profiles/WTR10E.yaml`: model keys `temperature_c`/`humidity_pct`
- `frontend/src/pages/EnvironmentPage.jsx`: current UI
