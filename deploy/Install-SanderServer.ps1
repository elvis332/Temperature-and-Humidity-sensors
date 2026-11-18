# Sander Zigbee / Modbus server installer. Windows PowerShell 5.1.
# Default: read-only validation. -Install requires IT signed-off approval.json and elevation.
# Does not patch EMS, change SQL, pair sensors, flash firmware, or change coordinator IP.
[CmdletBinding()]
param([switch]$Install, [string]$Root="C:\Sander")
Set-StrictMode -Version Latest
$ErrorActionPreference="Stop"

$repo=Join-Path $Root "ZigbeeBridge"
$python=Join-Path $repo ".venv\Scripts\python.exe"
$manifestFile=Join-Path $Root "Config\site-manifest.json"
$approvalFile=Join-Path $Root "Config\deployment-approval.json"
$winsw=Join-Path $Root "Tools\WinSW-x64.exe"
$node="C:\Program Files\nodejs\node.exe"
$registered=New-Object System.Collections.Generic.List[string]
$tasks=New-Object System.Collections.Generic.List[string]
$staged=$null

function MustExist([string]$path) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing prerequisite: $path" }
}
function ExecChecked([string]$exe,[string[]]$args) {
    & $exe @args
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $exe $($args -join ' ')" }
}
function TestPort([string]$hostName,[int]$port) {
    $client=New-Object System.Net.Sockets.TcpClient
    try {
        $async=$client.BeginConnect($hostName,$port,$null,$null)
        if (-not $async.AsyncWaitHandle.WaitOne(2500)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch { return $false }
    finally { $client.Close() }
}
function CheckPrivateFile([string]$file) {
    MustExist $file
    $auth=Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $auth.username -or -not $auth.password) { throw "Invalid protected MQTT credential file: $file" }
    $acl=Get-Acl -LiteralPath $file
    foreach ($entry in $acl.Access) {
        $identity=$entry.IdentityReference.Value
        if ($entry.AccessControlType -eq "Allow" -and $identity -match '(^Everyone$|\\Everyone$|\\Users$|Authenticated Users)' -and $entry.FileSystemRights.ToString() -match 'Read|Modify|FullControl|Write') {
            throw "MQTT secret ACL permits broad user access: $file ($identity). Ask IT to secure the file."
        }
    }
}
Write-Host "SANDER SERVER SETUP | $(if ($Install) {'INSTALL'} else {'VALIDATE ONLY'})"
if (-not ($Root -match '^[A-Za-z]:\\')) { throw "Root must be an absolute local Windows drive" }
foreach ($file in @($python,$manifestFile,$approvalFile,$winsw,$node,(Join-Path $repo "deploy\site_registry.py"),(Join-Path $repo "deploy\server_preflight.py"))) { MustExist $file }

$approval=Get-Content -LiteralPath $approvalFile -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($key in @("coordinator_ip_approved","broker_security_approved","service_accounts_approved","backup_and_cutover_approved","authorized_for_server_install")) {
    if ($approval.$key -ne $true) { throw "Valen/IT approval is missing: $key" }
}
if (-not $approval.approved_by -or $approval.approved_by -match 'REPLACE|TBD') { throw "approval.approved_by must name an authorized IT reviewer" }
if ($approval.server_name -ne $env:COMPUTERNAME) { throw "Approval server name mismatch. Expected $env:COMPUTERNAME" }
$hash=(Get-FileHash -Algorithm SHA256 -LiteralPath $winsw).Hash
if ($approval.winsw_sha256 -ne $hash) { throw "Unapproved WinSW binary: SHA256 hash mismatch" }

$site=Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($sensor in $site.sensors) {
    if ([string]::IsNullOrWhiteSpace($sensor.location) -or $sensor.location -match 'UPDATE|TBD|PLACEHOLDER') {
        throw "Sensor $($sensor.device_id) has unapproved location; update site manifest before installation."
    }
}
$broker=Get-Service -Name "mosquitto" -ErrorAction SilentlyContinue
if (-not $broker -or $broker.Status -ne "Running") { throw "IT-approved Mosquitto Windows service must already be running" }
$models=Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*zigbee2mqtt*index.js*" }
if ($models) { throw "A Zigbee2MQTT node process already exists on this server; refuse duplicate coordinator ownership." }

Push-Location $repo
try {
    ExecChecked $python @("-m","deploy.site_registry","--manifest",$manifestFile,"--root",$Root,"--output",(Join-Path $Root "Staging\PREVIEW"))
    ExecChecked $python @("-m","deploy.server_preflight","--root",$Root,"--manifest",$manifestFile)
} finally { Pop-Location }

foreach ($gw in $site.gateways) {
    $gid=$gw.id
    if (-not (TestPort $gw.coordinator_host $gw.coordinator_port)) { throw "Coordinator $gid is not reachable from this server; no changes made" }
    foreach ($role in @("bridge","recovery","admin")) {
        CheckPrivateFile (Join-Path $Root ("Config\mqtt-" + $role + "-" + $gid + ".auth.json"))
    }
    $zservice="SanderZ2M" + $gid
    $bservice="SanderBridge" + $gid
    foreach ($svc in @($zservice,$bservice)) {
        if (Get-Service -Name $svc -ErrorAction SilentlyContinue) {
            throw "Service $svc already installed; this installer never overwrites/upgrades existing services"
        }
    }
    if (Get-ScheduledTask -TaskName ("Sander-Zigbee-Recovery-" + $gid) -ErrorAction SilentlyContinue) {
        throw "Existing recovery task $gid present; this installer will not replace it"
    }
}
$old=Get-ScheduledTask -TaskName "Sander Zigbee Watchdog" -ErrorAction SilentlyContinue
if ($old -and $old.State -ne "Disabled") { throw "Legacy development login watchdog is enabled; IT must disable it before server cutover" }
if (-not $Install) {
    Write-Host "PRE-FLIGHT PASSED. No changes made. Valen can run -Install (or the one-click .cmd) after authorization."
    return
}
$id=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Install requires an IT-approved Administrator PowerShell session"
}
$when=(Get-Date).ToString("yyyyMMdd-HHmmss")
$staged=Join-Path $Root ("Staging\Install-" + $when)
New-Item -Path $staged -ItemType Directory -Force | Out-Null
Push-Location $repo
try {
    ExecChecked $python @("-m","deploy.site_registry","--manifest",$manifestFile,"--root",$Root,"--output",$staged,"--write")
} finally { Pop-Location }
$servicesDir=Join-Path $Root "Services"
$backupDir=Join-Path $Root "Backups"
New-Item -ItemType Directory -Force $servicesDir,$backupDir | Out-Null

try {
    # Every Zigbee2MQTT network backup occurs before any new service is installed.
    foreach ($gw in $site.gateways) {
        $gid=$gw.id
        $source=Join-Path $Root ("Config\zigbee2mqtt." + $gid)
        $backup=Join-Path $backupDir ("Zigbee2MQTT-" + $gid + "-" + $when + ".zip")
        Compress-Archive -LiteralPath $source -DestinationPath $backup -CompressionLevel Optimal -ErrorAction Stop
        if (-not (Test-Path -LiteralPath $backup -PathType Leaf)) { throw "Backup not created for $gid" }
        Write-Host "Network backup created: $backup. Protect this archive as it contains Zigbee secrets."
    }
    foreach ($gw in $site.gateways) {
        $gid=$gw.id
        foreach ($basename in @("bridge." + $gid + ".json","recovery." + $gid + ".json")) {
            $target=Join-Path $Root ("Config\" + $basename)
            if (Test-Path $target) { throw "Refusing to overwrite existing config: $target" }
            Copy-Item -LiteralPath (Join-Path $staged $basename) -Destination $target -ErrorAction Stop
        }
        foreach ($kind in @("Zigbee2MQTT","Bridge")) {
            $logPath=Join-Path $Root ("Logs\" + $gid + "\" + $kind)
            New-Item -ItemType Directory -Force -Path $logPath | Out-Null
            & icacls.exe $logPath /grant '*S-1-5-19:(OI)(CI)M' | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Unable to grant LocalService log write access: $logPath" }
        }
        foreach ($service in @("SanderZ2M" + $gid,"SanderBridge" + $gid)) {
            $xml=Join-Path $servicesDir ($service+".xml")
            $exe=Join-Path $servicesDir ($service+".exe")
            if ((Test-Path $xml) -or (Test-Path $exe)) { throw "Service wrapper files already exist: $service" }
            Copy-Item -LiteralPath (Join-Path $staged ($service+".xml")) -Destination $xml -ErrorAction Stop
            Copy-Item -LiteralPath $winsw -Destination $exe -ErrorAction Stop
            ExecChecked $exe @("install")
            $registered.Add($service)
            ExecChecked $exe @("start")
            Start-Sleep -Seconds 2
            $actual=Get-Service -Name $service -ErrorAction Stop
            if ($actual.Status -ne "Running") { throw "Windows service failed to stay running: $service" }
            Write-Host "Installed and started service $service"
        }
        $task="Sander-Zigbee-Recovery-" + $gid
        $cfg=Join-Path $Root ("Config\recovery." + $gid + ".json")
        $tasks.Add($task)
        & (Join-Path $repo "deploy\Install-SanderWatchdogTask.ps1") -Root $Root -ConfigPath $cfg -TaskName $task -Apply
        if (-not (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue)) { throw "Recovery task not registered: $task" }
    }
    Write-Host "SERVER INSTALL COMPLETED. Sensor pairing/EMS import is NOT performed automatically."
    Write-Host "Review generated EMS registration CSV: $(Join-Path $staged 'ems-device-registration-review.csv')"
    Write-Host "Next: Valen validates actual EMS staging database, history, alarms and physical recoveries."
} catch {
    Write-Warning ("INSTALL FAILED: " + $_.Exception.Message)
    foreach ($task in $tasks) {
        try { Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    }
    for ($i=$registered.Count-1; $i -ge 0; $i--) {
        $name=$registered[$i]
        $exe=Join-Path $servicesDir ($name+".exe")
        try { & $exe stop | Out-Null; & $exe uninstall | Out-Null } catch {}
    }
    Write-Warning "Only services installed by this run were rolled back. Saved Zigbee data, backups and audit files were NOT deleted. Review the server before retrying."
    throw
}
