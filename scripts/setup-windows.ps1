$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Require-Command($Name, $Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is not installed. $Hint"
    }
}

function Run-Step($Title, $Command) {
    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Title"
    }
}

Write-Host "BetExplorer Monitor setup" -ForegroundColor Green
Write-Host "Project folder: $Root"

Require-Command python "Install Python 3.11 or newer from https://www.python.org/downloads/ and enable 'Add python.exe to PATH'."
Require-Command npm "Install Node.js LTS from https://nodejs.org/."

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Run-Step "Installing uv" "python -m pip install --user uv"
    $UserBase = (& python -m site --user-base).Trim()
    $UserScripts = Join-Path $UserBase "Scripts"
    if (Test-Path $UserScripts) {
        $env:PATH = "$UserScripts;$env:PATH"
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item "config\settings.example.env" ".env"
    Write-Host "Created .env from config\settings.example.env"
}

Run-Step "Creating Python environment" "uv venv .venv"
Run-Step "Installing Python dependencies" 'uv pip install -e "."'
Run-Step "Installing UI dependencies" "npm --prefix apps/desktop/web install"

Write-Host ""
Write-Host "Setup completed. Use start-windows.cmd or the desktop shortcut to run the app." -ForegroundColor Green
