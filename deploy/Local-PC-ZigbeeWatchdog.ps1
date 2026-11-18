# Local PC only. Does not modify Windows services, Zigbee configuration, or EMS.
# The server uses deploy/recovery_supervisor.py + approved Windows services instead.
[CmdletBinding()]
param([switch]$Once, [ValidateRange(10,3600)][int]$IntervalSeconds=15)
Set-StrictMode -Version Latest
$ErrorActionPreference="Stop"

$root="C:\SanderTools"
$z2m=Join-Path $root "z2m-npm"
$data=Join-Path $z2m "sander-data"
$log=Join-Path $root "zigbee-watchdog.log"
$node="C:\Program Files\nodejs\node.exe"
$entry=Join-Path $z2m "node_modules\zigbee2mqtt\index.js"
$config=Join-Path $data "configuration.yaml"
$lastState=""
$lastLaunch=[DateTime]::MinValue

function Log([string]$message) {
    $line=("{0} {1}" -f (Get-Date).ToString("s"),$message)
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
    Write-Host $line
}
function PortOpen([string]$hostName,[int]$port) {
    $client=New-Object System.Net.Sockets.TcpClient
    try {
        $async=$client.BeginConnect($hostName,$port,$null,$null)
        if (-not $async.AsyncWaitHandle.WaitOne(1500)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch { return $false }
    finally { $client.Close() }
}

try {
    foreach ($file in @($node,$entry,$config)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Required file not found: $file"
        }
    }
    Log ("WATCHDOG START user={0} pid={1} Once={2}" -f $env:USERNAME,$PID,$Once.IsPresent)
    while ($true) {
        try {
            $broker=PortOpen "127.0.0.1" 1883
            $coordinator=PortOpen "192.168.50.20" 6638
            $frontend=PortOpen "127.0.0.1" 8080
            $proc=@(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction Stop | Where-Object { $_.CommandLine -like "*zigbee2mqtt*index.js*" })
            $state=("mqtt={0} coordinator={1} z2mWeb={2} process={3}" -f $broker,$coordinator,$frontend,$proc.Count)
            if ($state -ne $lastState) { Log "STATUS $state"; $lastState=$state }
            if ($broker -and $coordinator -and -not $frontend -and $proc.Count -eq 0) {
                if (((Get-Date)-$lastLaunch).TotalSeconds -ge 60) {
                    $env:ZIGBEE2MQTT_DATA=$data
                    $started=Start-Process -FilePath $node -ArgumentList ('"{0}"' -f $entry) -WorkingDirectory $z2m -PassThru -RedirectStandardOutput (Join-Path $root "zigbee2mqtt-watchdog-stdout.log") -RedirectStandardError (Join-Path $root "zigbee2mqtt-watchdog-stderr.log")
                    $lastLaunch=Get-Date
                    Log ("START Zigbee2MQTT pid={0}" -f $started.Id)
                }
            }
            elseif ($broker -and $coordinator -and -not $frontend -and $proc.Count -gt 0) {
                Log "WARNING Zigbee2MQTT process exists but dashboard is unavailable; not launching a duplicate"
            }
        } catch {
            Log ("ERROR " + $_.Exception.ToString())
        }
        if ($Once) { Log "WATCHDOG one-pass completed"; break }
        Start-Sleep -Seconds $IntervalSeconds
    }
} catch {
    try { Log ("FATAL " + $_.Exception.ToString()) } catch {}
    throw
}
