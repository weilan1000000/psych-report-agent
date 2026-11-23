$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PidPath = Join-Path $ProjectRoot "output\report_app\service\server.pid"

if (-not (Test-Path -LiteralPath $PidPath)) {
    Write-Host "No report console process record was found."
    exit 0
}

$serverPid = [int](Get-Content -LiteralPath $PidPath -Raw)
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid" -ErrorAction SilentlyContinue
if ($null -ne $processInfo -and $processInfo.CommandLine -match "report_app\.server") {
    Stop-Process -Id $serverPid -Force
    Write-Host "Report console stopped."
}
else {
    Write-Host "The process record was stale; no unrelated process was stopped."
}
Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
