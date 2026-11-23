param(
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DestinationRoot = Join-Path $ProjectRoot $OutputDirectory
$DateStamp = Get-Date -Format "yyyyMMdd-HHmm"
$ArchivePath = Join-Path $DestinationRoot "PsychReportAgent-$DateStamp.zip"

New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null

$excluded = @(
    ".git",
    ".venv",
    "node_modules",
    "output",
    "tmp",
    ".scratch",
    "pdf_inspection",
    "dist",
    "__pycache__",
    ".env",
    ".env.*",
    "*.env",
    "*.key",
    "*.pem",
    "*.doc",
    "*.docx",
    "*.xls",
    "*.xlsx",
    "./docs/reference_notes",
    "./samples/sample_junior_high_liu_x_tong.json"
)
$arguments = @("-a", "-c", "-f", $ArchivePath)
foreach ($name in $excluded) {
    $arguments += "--exclude=$name"
}
$arguments += @("-C", $ProjectRoot, ".")

& tar.exe @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the colleague package."
}

Write-Host "Package created:" -ForegroundColor Green
Write-Host $ArchivePath
Write-Host "The package excludes API settings, generated reports, caches, Git history, and local dependencies."
