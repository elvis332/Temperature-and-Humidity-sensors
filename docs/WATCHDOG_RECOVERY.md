# Local PC Task Scheduler recovery — 2026-11-17

The old local task named **Sander Zigbee Watchdog** showed:
- Task State: Ready
- LastTaskResult: 1
- No watchdog PowerShell process or log
- zigbee-watchdog.ps1 exists

**That is a failed/terminated task, NOT a healthy watchdog.**
Return code 1 does not identify the cause; it may be execution policy, action arguments, script runtime, filesystem ACL, or another failure. Check Task Scheduler Operational events and the registered task action. Do not bypass corporate execution policy.

## Diagnose (read-only)

From a local clone of this GitHub feature branch:

    powershell.exe -NoProfile -File .\deploy\Diagnose-LocalWatchdog.ps1

This reads the task, last result, action, effective execution policies, TaskScheduler/Operational events and local logs. It does not start or stop services.

## Repair the development PC (not production)

Use a checked-out local copy of this branch at a location that Windows trusts and company policy allows. The startup installer defaults to **DRY RUN**:

    powershell.exe -NoProfile -File .\deploy\Install-LocalWatchdog.ps1 -Repo "C:\Path\To\Temperature-and-Humidity-sensors"

The dry run validates the script and the old task. With explicit user approval and Windows policy permitting unsigned local scripts:

    powershell.exe -NoProfile -File .\deploy\Install-LocalWatchdog.ps1 -Repo "C:\Path\To\Temperature-and-Humidity-sensors" -Apply

What -Apply does:
1. Checks the script syntax and current execution policy (refuses Restricted/AllSigned; no bypass).
2. Refuses to overwrite a running watchdog process.
3. Copies reviewed deploy/Local-PC-ZigbeeWatchdog.ps1 into C:\SanderTools\zigbee-watchdog.ps1.
4. Runs one bounded health pass (may launch Zigbee2MQTT only if broker/coordinator are reachable, no Z2M dashboard and **no Zigbee2MQTT process exists**).
5. Re-registers the same task at current-user logon, not system boot; starts the task.
6. Checks that the task **remains Running** and prints the last result/log; if not, fails with actionable error.

Local script logs WATCHDOG START and each state transition to C:\SanderTools\zigbee-watchdog.log. It never resets Zigbee, deletes/re-pairs sensors, changes IP or EMS SQL. It does not kill a hung process, and refuses to start a second coordinator owner. If a running Z2M process is unhealthy, the local watchdog warns only. Avoid using Task Scheduler plus the new server recovery supervisor simultaneously.

## Production is different

Use docs/VALEN_PRODUCTION_PR.md for the company server. The production setup uses:
- IT-approved Mosquitto, Zigbee2MQTT and bridge **Windows services** configured to start at OS boot before login.
- deploy/Install-SanderWatchdogTask.ps1 with approved -Apply to register **Sander-Zigbee-Recovery** under SYSTEM, supervising only named Windows services with cooldown and MQTT heartbeat health checks. This installer has its own DRY RUN mode and refuses coexistence with the old login watchdog.
- Actual EMS staging validation and Valen approval for SQL, Env page, history and alarms.

Nothing in this source repository alone installs on a live server. IT must configure service credentials, access controls, coordinator IP, backup and rollback.

## Acceptance

- Scheduled Task Running AND log contains recent WATCHDOG START and STATUS lines; Ready plus result 1 is failure.
- With appropriate permissions and an approved test plan, terminate **only** the test Z2M process; watchdog should restore it within its poll/retry window, preserving network identity. Do not test power loss until the software test passes.
- Confirm real TH-02 last_seen, Modbus registers and the local preview resume with a new report.
- On production, repeat for OS restart before login, broker failure, stalled coordinator/radio, and 24–72h stability.
