# One-click Sander server installer — Valen / IT

**Code status: staging candidate only.** No production server, SQL database or factory coordinator has been changed.

## Architecture: sensor/device registration at scale
Use deploy/site-manifest.example.json as the starting inventory. Each sensor has a stable EMS device ID, IEEE address, friendly_name, exact location, gateway ID, Modbus unit ID and offline timeout. Each gateway has an approved coordinator address, unique MQTT namespace, unique Modbus port and Zigbee2MQTT UI port.

Generator deploy/site_registry.py outputs:
- Independent bridge.<GW>.json and recovery.<GW>.json per gateway
- Two WinSW service XMLs per gateway (built-in least-privilege LocalService account)
- ems-device-registration-review.csv recording all sensor identities, locations, topics and Modbus endpoints
- deployment-summary.json

The EMS CSV is REVIEW_ONLY_NOT_IMPORTED. **It is not an actual EMS DB import.** Valen must use the actual EMS staging application and validate duplicate checking and registration before production.

For later sensor additions, run deploy/reconcile_site.py with --before old-site.json --after new-site.json before regenerating any configs. It reports additions and editable metadata updates and **blocks IEEE address, gateway, Modbus unit and existing gateway endpoint changes**, preventing accidental mixing of historical device series. This is a dry-run proposal, not an automatic upgrade or EMS import.

One Modbus bridge endpoint can address at most 247 unit IDs. A multi-gateway deployment uses distinct bridge TCP ports, allowing more devices in the EMS, but actual Zigbee RF capacity is independent and must be determined by range, route/mesh stability and load testing. Each physical coordinator has one Zigbee2MQTT process and one unique MQTT base topic.

## Prepare the Windows server once (Valen or IT)
- Check out this PR branch at C:\Sander\ZigbeeBridge. Create approved Python virtual environment at C:\Sander\ZigbeeBridge\.venv and install requirements.txt.
- Install approved Node.js; copy the **approved built** Zigbee2MQTT runtime for each GW to C:\Sander\zigbee2mqtt\GW01, etc.
- Configure IT-approved Mosquitto as a Windows service, running with authenticated localhost MQTT and topic ACL.
- Preserve Zigbee2MQTT network identity: securely copy full existing Zigbee2MQTT data, including configuration.yaml, database.db, channel, PAN, ext PAN, key, friendly names, state and coordinator backups, into C:\Sander\Config\zigbee2mqtt.GW01, etc. Do not regenerate network keys or factory reset the sensor. Firmware 7.3.1.0 / EZSP v12 requires current working adapter ezsp.
- Confirm serial.port points at the **IT-approved coordinator IP** (192.168.35.11 is a proposal, not a verified production IP). Configure advanced.last_seen=ISO_8601 and the registry's mqtt.base_topic. Do not replace the whole live YAML.
- Place a vetted WinSW x64 binary in C:\Sander\Tools\WinSW-x64.exe and pin its Get-FileHash SHA256 in the approval JSON. No downloads or binaries are shipped/auto-installed by our scripts.
- IT creates ACL-restricted per-gateway JSON broker credentials: C:\Sander\Config\mqtt-bridge-GW01.auth.json and C:\Sander\Config\mqtt-recovery-GW01.auth.json, each with fields username and password. Never commit passwords or grant Everyone/Users read access. Give only approved service identities access. Z2M has separate existing MQTT credentials in its protected config.
- Ensure LocalService can read code/config/credentials and write Zigbee data and service logs; SYSTEM can write watchdog logs. LocalService is deliberately used instead of LocalSystem for the WinSW-managed services.
- Adapt deploy/site-manifest.example.json into C:\Sander\Config\site-manifest.json. Enter real sensor locations, existing IEEE identities and actual chosen gateway addresses; no placeholder is acceptable for the installer.
- Adapt deploy/deployment-approval.example.json into C:\Sander\Config\deployment-approval.json. IT must name an authorized reviewer, set the actual server name and WinSW SHA256 hash and explicitly approve coordinator IP, broker security, service accounts, backup/cutover and installation. Approval does not substitute for company change control.

## Fast double-click process

**Step 1: OneClick-Check-SanderServer.cmd** — read-only. Validates credentials/access, correct folder structure and Zigbee database preservation, duplicate sensor IDs, unique TCP ports, approved software, coordinator access, and absence of already running duplicate Z2M processes or installed services.

**Step 2: OneClick-Install-SanderServer.cmd** — run only in an approved elevated IT session after Step 1 passes. Revalidates preconditions, generates a new staging configuration set, archives each Zigbee2MQTT data directory BEFORE service changes, copies configuration into approved paths without overwriting existing files, installs WinSW service wrappers, starts services and registers a SYSTEM-at-boot recovery Scheduled Task for each gateway. It produces a CSV for EMS registration review. On error, it attempts to roll back only newly installed services and tasks, and keeps backups and audit files.

Install location:
- C:\Sander\Staging\Install-YYYYMMDD-HHMMSS : generated files and registration CSV
- C:\Sander\Backups : full protected Zigbee2MQTT data backup archives
- C:\Sander\Config : protected runtime bridge/recovery configurations and IT-supplied broker credentials
- C:\Sander\Services : approved WinSW executable copies paired with generated XML
- C:\Sander\Logs\ZigbeeRecovery : per-gateway recovery logs

**Installer success means software services were registered/running, not that the EMS database integration was accepted.**

## Production acceptance gates
- IT confirms service account permissions, startup after OS reboot before login, recovery from process/broker outages and coordinator power restoration without sensor re-pairing.
- TH-02 fresh last_seen must reach MQTT -> Modbus -> real EMS API/SQL history; battery alarm, offline warning and return to online tested in staging.
- Wired TH-01/WTR10-E, existing factory lighting and EMS collectors must remain unchanged.
- Observe sensor reporting cadence for 24–72 hours to tune provisional 900-second offline threshold. Verify RF network physical capacity and routers before extensive rollout.
- Valen applies integrations/modbus/apply_ui.py on current EMS staging code and reviews integration diff; this repository cannot directly change the main EMS application without its actual repository.

**Rollback:** IT stops/unenrolls new services/tasks, restores preserved network only under approved change control, and separately rolls back EMS staging patch if needed. Never reset Zigbee devices automatically.

See VALEN_PRODUCTION_PR.md for details.
