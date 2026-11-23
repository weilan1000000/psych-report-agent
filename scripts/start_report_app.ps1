param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
$arguments = @("-m", "report_app.launcher", "--port", $Port)
if ($NoBrowser) {
    $arguments += "--no-browser"
}
& $PythonExe @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Report console launcher failed."
}
