# Read-only diagnosis of a failed local Zigbee watchdog Scheduled Task.
[CmdletBinding()]
param()
$ErrorActionPreference = "Continue"
$taskName = "Sander Zigbee Watchdog"
Write-Host "=== TASK ==="
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) { Write-Host "NOT REGISTERED"; return }
$task | Select-Object TaskName,State | Format-List
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime,LastTaskResult,NumberOfMissedRuns | Format-List
Write-Host "=== ACTION ==="
$task.Actions | Select-Object Execute,Arguments,WorkingDirectory | Format-List
Write-Host "=== EXECUTION POLICY ==="
Get-ExecutionPolicy -List | Format-Table
Write-Host "=== WINDOWS TASK SCHEDULER RECENT EVENTS ==="
try {
    Get-WinEvent -FilterHashtable @{LogName="Microsoft-Windows-TaskScheduler/Operational";StartTime=(Get-Date).AddDays(-2)} -MaxEvents 120 -ErrorAction Stop |
        Where-Object { $_.Message -like "*$taskName*" } |
        Select-Object -First 12 TimeCreated,Id,LevelDisplayName,Message | Format-List
} catch { Write-Host "TaskScheduler Operational event log unavailable: $($_.Exception.Message)" }
Write-Host "=== WATCHDOG LOG ==="
if (Test-Path "C:\SanderTools\zigbee-watchdog.log") {
    Get-Content "C:\SanderTools\zigbee-watchdog.log" -Tail 20
} else { Write-Host "No watchdog log exists; process may never have started" }
Write-Host "=== PROCESS ==="
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like "*zigbee-watchdog.ps1*" } |
    Select-Object ProcessId,CommandLine | Format-List
