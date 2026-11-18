# Local developer PC recovery task repair. No factory/server/prod changes.
# Dry run by default; -Apply explicitly replaces the old login task.
[CmdletBinding()]
param([switch]$Apply, [string]$Repo = "C:\SanderTools\ZigbeeBridge")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskName = "Sander Zigbee Watchdog"
$target = "C:\SanderTools\zigbee-watchdog.ps1"
$source = Join-Path $Repo "deploy\Local-PC-ZigbeeWatchdog.ps1"
$ps = Join-Path $PSHOME "powershell.exe"
if (-not (Test-Path $source -PathType Leaf)) { throw "Missing repository source: $source" }
$tokens=$null
$errors=$null
[System.Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors) | Out-Null
if ($errors.Count -gt 0) { throw "Local watchdog PowerShell syntax check failed" }

Write-Host "=== Local Zigbee watchdog repair ==="
Write-Host ("Mode: " + $(if ($Apply) { "APPLY" } else { "DRY RUN" }))
Write-Host "Source: $source"
Write-Host "Installed script: $target"
Write-Host "Task: $taskName"
Write-Host "PowerShell execution policy: $(Get-ExecutionPolicy)"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Previous task state: $($existing.State)"
    Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime,LastTaskResult | Format-List
}
if (-not $Apply) {
    Write-Host "DRY RUN complete. No changes made."
    return
}
# Respect company execution-policy controls. Do not bypass or lower policy.
$policy=Get-ExecutionPolicy
if ($policy -in @("Restricted","AllSigned")) {
    throw "Execution policy $policy requires IT approval/signing before using a PS1 scheduled task. No bypass applied."
}
$person=[Security.Principal.WindowsIdentity]::GetCurrent().Name
if ($existing -and $existing.State -eq "Running") {
    throw "Existing task is running: stop it through the approved maintenance procedure before replacing."
}
# Check the script can run ONE pass in this interactive shell before scheduling.
Copy-Item -LiteralPath $source -Destination $target -Force
& $target -Once
# PowerShell script failures are terminating under ErrorActionPreference=Stop.
# LASTEXITCODE may be uninitialized when no native executable was invoked.
$action=New-ScheduledTaskAction -Execute $ps -Argument ('-NoProfile -NonInteractive -File "' + $target + '"')
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $person
$principal=New-ScheduledTaskPrincipal -UserId $person -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 5
$actual=Get-ScheduledTask -TaskName $taskName
$details=Get-ScheduledTaskInfo -TaskName $taskName
$actual | Select-Object TaskName,State | Format-Table
$details | Select-Object LastRunTime,LastTaskResult | Format-Table
if ($actual.State -ne "Running") {
    Write-Warning "Task not running: inspect Task Scheduler Operational events and script log; do not consider recovery enabled."
    Get-Content "C:\SanderTools\zigbee-watchdog.log" -Tail 15 -ErrorAction SilentlyContinue
    throw "Watchdog registration completed but runtime validation failed"
}
Write-Host "Local watchdog is running at user logon; not a pre-login server service."
