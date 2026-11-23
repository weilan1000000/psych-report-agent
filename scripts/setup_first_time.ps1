param(
    [switch]$CheckOnly,
    [switch]$SkipLaunch,
    [switch]$SkipShortcuts
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SetupDir = Join-Path $ProjectRoot "output\setup"
$LogPath = Join-Path $SetupDir "setup.log"
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $SetupDir | Out-Null
Start-Transcript -Path $LogPath -Append | Out-Null

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Get-PythonExecutable {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        try {
            $path = & $python.Source -c "import sys; assert sys.version_info >= (3, 11); print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $path) { return $path.Trim() }
        }
        catch {}
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        foreach ($version in @("-3.12", "-3.11")) {
            try {
                $path = & $py.Source $version -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $path) { return $path.Trim() }
            }
            catch {}
        }
    }
    return $null
}

function Get-NodeMajorVersion {
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($null -eq $node) { return 0 }
    try {
        return [int](& $node.Source -p "process.versions.node.split('.')[0]" 2>$null)
    }
    catch { return 0 }
}

function Test-VenvPython {
    if (-not (Test-Path -LiteralPath $VenvPython)) { return $false }
    try {
        & $VenvPython -c "import sys; print(sys.executable)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Remove-StaleVenv {
    $resolvedRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
    $resolvedVenv = [System.IO.Path]::GetFullPath($VenvDir)
    if (-not $resolvedVenv.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a virtual environment outside the project folder: $resolvedVenv"
    }
    Write-Host "The existing .venv belongs to another Python installation and will be rebuilt." -ForegroundColor Yellow
    Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
}

function Stop-ExistingReportConsole([int]$Port = 8765) {
    $connections = @(
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    )
    foreach ($connection in $connections) {
        $processInfo = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $($connection.OwningProcess)" `
            -ErrorAction SilentlyContinue
        if ($null -eq $processInfo) { continue }
        $commandLine = [string]$processInfo.CommandLine
        if ($commandLine -match "report_app\.(server|launcher)") {
            Write-Host (
                "Stopping an older Psych Report Console process on port {0} (PID {1})." `
                    -f $Port, $connection.OwningProcess
            ) -ForegroundColor Yellow
            Stop-Process -Id $connection.OwningProcess -Force
            Start-Sleep -Milliseconds 400
            continue
        }
        throw (
            "Port {0} is already used by another program (PID {1}). " `
                + "Close that program and run setup again." `
                -f $Port, $connection.OwningProcess
        )
    }
}

function Require-Winget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw "winget is unavailable. Install Python 3.11+ and Node.js 18+ manually, then run setup again."
    }
    return $winget.Source
}

try {
    if ($env:OS -ne "Windows_NT") {
        throw "This first-time installer currently supports Windows only."
    }

    if (-not $CheckOnly) {
        Write-Step "Checking for an older report console service"
        Stop-ExistingReportConsole
    }

    Write-Step "Checking Python 3.11 or newer"
    $PythonExe = Get-PythonExecutable
    if (-not $PythonExe -and -not $CheckOnly) {
        $winget = Require-Winget
        & $winget install --id Python.Python.3.12 -e --silent `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Python installation failed with exit code $LASTEXITCODE." }
        Refresh-ProcessPath
        $PythonExe = Get-PythonExecutable
    }
    if (-not $PythonExe) { throw "Python 3.11+ was not found." }
    Write-Host "Python: $PythonExe"

    Write-Step "Checking Node.js 18 or newer"
    $NodeMajor = Get-NodeMajorVersion
    if ($NodeMajor -lt 18 -and -not $CheckOnly) {
        $winget = Require-Winget
        & $winget install --id OpenJS.NodeJS.LTS -e --silent `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Node.js installation failed with exit code $LASTEXITCODE." }
        Refresh-ProcessPath
        $NodeMajor = Get-NodeMajorVersion
    }
    if ($NodeMajor -lt 18) { throw "Node.js 18+ was not found." }
    Write-Host "Node.js major version: $NodeMajor"

    if ($CheckOnly) {
        Write-Step "Environment check completed"
        Write-Host "Check-only mode made no changes."
        exit 0
    }

    Write-Step "Creating the isolated Python environment"
    if ((Test-Path -LiteralPath $VenvDir) -and -not (Test-VenvPython)) {
        Remove-StaleVenv
    }
    if (-not (Test-VenvPython)) {
        & $PythonExe -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { throw "Could not create .venv." }
    }
    if (-not (Test-VenvPython)) {
        throw "The newly created .venv could not start."
    }
    & $VenvPython -m pip install --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
    & $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

    Write-Step "Installing Node.js dependencies"
    Push-Location $ProjectRoot
    try {
        & npm.cmd ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm dependency installation failed." }

        Write-Step "Installing Playwright Chromium"
        & npx.cmd playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw "Playwright Chromium installation failed." }
    }
    finally {
        Pop-Location
    }

    Write-Step "Running offline verification"
    & $VenvPython (Join-Path $ProjectRoot "scripts\validate_report_pipeline.py")
    if ($LASTEXITCODE -ne 0) { throw "Pipeline validation failed." }
    & $VenvPython -m unittest tests.test_report_app
    if ($LASTEXITCODE -ne 0) { throw "Report console tests failed." }

    if (-not $SkipShortcuts) {
        Write-Step "Installing the desktop shortcut"
        & powershell -NoProfile -ExecutionPolicy Bypass -File `
            (Join-Path $ProjectRoot "scripts\install_report_console_shortcuts.ps1")
        if ($LASTEXITCODE -ne 0) { throw "Shortcut installation failed." }
    }

    if (-not $SkipLaunch) {
        Write-Step "Opening the report console"
        & $VenvPython -m report_app.launcher
        if ($LASTEXITCODE -ne 0) { throw "Report console launch failed." }
    }

    Write-Step "Setup completed successfully"
    Write-Host "Open http://127.0.0.1:8765 or use the desktop shortcut."
}
catch {
    Write-Host "`nSETUP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $LogPath" -ForegroundColor Yellow
    exit 1
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
