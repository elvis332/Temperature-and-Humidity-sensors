# Merge the add-on into the existing Sander EMS (development copy first)

The provided Sander EMS source ZIP already contains the Environment page and telemetry tables. **Do not replace or delete WTR10-E code.**

1. Copy `integrations/sanderems/config/profiles/SNZB02D.yaml` into the EMS project `config/profiles/`.
2. Copy `integrations/sanderems/backend/app/api/routes/environment_signals.py` into `backend/app/api/routes/`.
3. In EMS `backend/app/api/router.py`, add `environment_signals` to the `from backend.app.api.routes import (...)` list and add `api_router.include_router(environment_signals.router)` alongside the existing environment router.
4. Copy `integrations/sanderems/frontend/src/pages/EnvironmentSignalStrip.jsx` into `frontend/src/pages/`.
5. In existing `frontend/src/pages/EnvironmentPage.jsx`, add `import EnvironmentSignalStrip from "./EnvironmentSignalStrip";` and add `<EnvironmentSignalStrip />` immediately after its error banner (before the sensor cards).
6. Keep the original Sander CSS classes; this component uses `panel` and `env-card-alarm` from the current frontend. Test both zh/en modes and `npm run build` on a development copy.

This new route computes current warnings using the existing SQL Server telemetry. It supports configurable `zigbee_alerts.temperature_jump`, `humidity_jump`, `jump_minutes` inside `device_settings.settings_json` (defaults: 2°C, 10%RH, 10 minutes). Existing per-device `alarm_min`/`alarm_max` continue to be edited using the Devices UI.

**Current limitation:** computed warnings are not yet a persistent acknowledgement/audit system. Local SQLite simulation stores open/closed transitions. A production SQL alert-history table and admin editor for rapid-change settings remain a later integration task.

There is no control endpoint. For HVAC, only a future independently authorized adapter should consume the alerts; no automatic write is allowed at this stage.
