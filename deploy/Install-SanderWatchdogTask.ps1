# IT-approved SYSTEM startup health monitor, dry-run by default.
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Root = "C:\Sander",
    [string]$ConfigPath = "",
    [string]$TaskName = "Sander-Zigbee-Recovery"
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = Join-Path $Root "ZigbeeBridge"
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not $ConfigPath) { $ConfigPath = Join-Path $Root "Config\zigbee-recovery.json" }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Missing Python interpreter $python" }
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw "Missing recovery configuration $ConfigPath" }
if (-not (Test-Path (Join-Path $repo "deploy\recovery_supervisor.py"))) { throw "Missing recovery supervisor source" }
if ($TaskName -notmatch '^[A-Za-z0-9-]{5,100}$') { throw "Invalid task name" }
& $python -c "from deploy.recovery_supervisor import load_config; import sys; load_config(sys.argv[1]); print('Recovery config validated')" $ConfigPath
if ($LASTEXITCODE -ne 0) { throw "Recovery config failed validation" }
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($name in @("mosquitto", $config.z2m_service, $config.bridge_service)) {
    $service = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $service) { throw "Required Windows service is not installed: $name" }
}
$old = Get-ScheduledTask -TaskName "Sander Zigbee Watchdog" -ErrorAction SilentlyContinue
if ($old -and $old.State -ne "Disabled") {
    throw "The old developer-PC watchdog is still enabled: IT must disable it before this server supervisor."
}
$current = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($current) { throw "A task named $TaskName already exists. Never overwrite a running supervisor." }
Write-Host "Validated supervisor for $($config.z2m_service) / $($config.bridge_service)"
if (-not $Apply) { Write-Host "DRY RUN: No scheduled task installed"; return }

$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck=New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Approved elevation required for service startup task installation."
}
$logFile = Join-Path $Root ("Logs\ZigbeeRecovery\" + $TaskName + ".log")
New-Item -ItemType Directory -Force (Split-Path -Parent $logFile) | Out-Null
$arguments = '-u -m deploy.recovery_supervisor --config "' + $ConfigPath + '" --log-file "' + $logFile + '"'
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Sander Zigbee recovery supervisor; no pairing or SQL writes" | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3
$actual=Get-ScheduledTask -TaskName $TaskName
if ($actual.State -ne "Running") {
    $info=Get-ScheduledTaskInfo -TaskName $TaskName
    throw "Task not running (state $($actual.State), result $($info.LastTaskResult)); investigate log and Task Scheduler events"
}
Write-Host "Supervisor running: $TaskName; log $logFile"
