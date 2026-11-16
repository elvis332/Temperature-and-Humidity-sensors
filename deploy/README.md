# Valen: Windows service templates (not installed)

Use an IT-approved WinSW release. These XML files are templates, not executable service installers. Confirm actual software versions, absolute paths, built Zigbee2MQTT entry point and service dependencies. Use a dedicated service account and secure MQTT credentials outside Git; grant only required data/log permissions. Do not copy the development EMS .env.

1. Install Mosquitto using approved Windows installer and configure the authenticated broker. Verify service name (template assumes mosquitto).
2. Install and build approved Zigbee2MQTT release; configure its data directory, network keys, coordinator IP and last_seen.
3. Install Python virtual environment under bridge project root; install requirements.txt. Save production bridge JSON outside Git.
4. For each XML template, place the approved WinSW executable beside the XML using the same filename stem; customize paths/credentials/account/dependencies. Validate via manual console startup first, then use the wrapper's install/start commands with administrator permission. Check service status and logs.
5. Test restart, broker outage, stale data and recovery. Start/enable existing EMS collector on production server only through Valen's normal deployment process.

See docs/COMMISSIONING.md and docs/MODBUS_DEPLOYMENT.md. No automatic production installation, database access or HVAC control is included.
