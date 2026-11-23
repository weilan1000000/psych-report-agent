param(
    [int]$Port = 8765,
    [switch]$SkipAutoStart
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OpenCommand = Join-Path $ProjectRoot "OPEN_REPORT_CONSOLE.cmd"
$Shell = New-Object -ComObject WScript.Shell

$Desktop = [Environment]::GetFolderPath("Desktop")
$DesktopLink = Join-Path $Desktop "Psych Report Console.lnk"
$DesktopShortcut = $Shell.CreateShortcut($DesktopLink)
$DesktopShortcut.TargetPath = $OpenCommand
$DesktopShortcut.WorkingDirectory = $ProjectRoot
$DesktopShortcut.Description = "Open the local psychological report console"
$DesktopShortcut.Save()

if (-not $SkipAutoStart) {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $python = if (Test-Path -LiteralPath $venvPython) {
        $venvPython
    }
    else {
        (Get-Command python -ErrorAction Stop).Source
    }
    $pythonw = Join-Path (Split-Path $python -Parent) "pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonw)) {
        $pythonw = $python
    }
    $Startup = [Environment]::GetFolderPath("Startup")
    $StartupLink = Join-Path $Startup "Psych Report Console Service.lnk"
    $StartupShortcut = $Shell.CreateShortcut($StartupLink)
    $StartupShortcut.TargetPath = $pythonw
    $StartupShortcut.Arguments = "-m report_app.launcher --port $Port --no-browser"
    $StartupShortcut.WorkingDirectory = $ProjectRoot
    $StartupShortcut.Description = "Start the local report service after Windows login"
    $StartupShortcut.Save()
}

$launcherPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $launcherPython)) {
    $launcherPython = (Get-Command python -ErrorAction Stop).Source
}
& $launcherPython -m report_app.launcher --port $Port --no-browser
if ($LASTEXITCODE -ne 0) {
    throw "Report console launcher failed."
}
Write-Host "Installed. Bookmark and open: http://127.0.0.1:$Port" -ForegroundColor Green
