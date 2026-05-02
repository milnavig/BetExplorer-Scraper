$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Dist = Join-Path $Root "dist"
$PackageDir = Join-Path $Dist "BetExplorer-Monitor-Client"
$ZipPath = Join-Path $Dist "BetExplorer-Monitor-Client.zip"

Set-Location $Root
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
if (Test-Path $PackageDir) {
    Remove-Item $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null

$ExcludeDirs = @(".git", ".venv", ".pytest_cache", "node_modules", ".next", "dist", "target", "data", "har", "out", "__pycache__")
$ExcludeFiles = @("*.pyc", "*.pyo", ".env")
$robocopyArgs = @($Root, $PackageDir, "/E", "/XD") + $ExcludeDirs + @("/XF") + $ExcludeFiles
& robocopy @robocopyArgs | Out-Host
if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}

New-Item -ItemType Directory -Force -Path (Join-Path $PackageDir "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PackageDir "data\exports") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PackageDir "data\logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PackageDir "data\raw_snapshots") | Out-Null

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -Force

Write-Host "Created package: $ZipPath" -ForegroundColor Green
