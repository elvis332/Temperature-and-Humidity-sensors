# Valen / IT review only until -Apply is passed.
# Runs approved recovery at OS startup regardless of user logon.
[CmdletBinding()]
param([switch]$Apply, [string]$Root = "C:\Sander", [string]$TaskName = "Sander-Zigbee-Recovery")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = Join-Path $Root "ZigbeeBridge"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$config = Join-Path $Root "Config\zigbee-recovery.json"
$z2m = "SanderZigbee2MQTT"
$bridge = "SanderZigbeeBridge"

Write-Host "=== Sander Zigbee startup recovery ==="
if ($Apply) { Write-Host "Mode: APPLY" } else { Write-Host "Mode: DRY RUN" }
Write-Host "Repository: $repo"
Write-Host "Python: $python"
Write-Host "Configuration: $config"
Write-Host "Task: $TaskName"

$items = @($python, $config, (Join-Path $repo "deploy\recovery_supervisor.py"))
foreach ($item in $items) {
    if (-not (Test-Path $item -PathType Leaf)) { throw "Required installation file missing: $item" }
}
& $python -c "from deploy.recovery_supervisor import load_config; import sys; load_config(sys.argv[1]); print('Recovery configuration validated')" $config
if ($LASTEXITCODE -ne 0) { throw "Python configuration validation failed" }
foreach ($service in @("mosquitto", $z2m, $bridge)) {
    $found = Get-Service -Name $service -ErrorAction SilentlyContinue
    if (-not $found) { throw "Required Windows service missing: $service" }
    Write-Host "$service : $($found.Status)"
}
$old = Get-ScheduledTask -TaskName "Sander Zigbee Watchdog" -ErrorAction SilentlyContinue
if ($old -and $old.State -ne "Disabled") {
    throw "Old development watchdog task is present. Disable it with IT approval before server installation."
}
if (-not $Apply) {
    Write-Host "DRY RUN passed. No task or service changes made."
    return
}
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Apply requires an approved elevated IT PowerShell session."
}
$logFile = Join-Path $Root "Logs\ZigbeeRecovery\supervisor.log"
$logDir = Split-Path $logFile -Parent
New-Item -Path $logDir -ItemType Directory -Force | Out-Null
$arguments = '-u -m deploy.recovery_supervisor --config "' + $config + '" --log-file "' + $logFile + '"'
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Sander Zigbee health supervisor, no pairing or hardware writes" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
Write-Host "Startup task registered; verify Task Scheduler history and WinSW service logs."
