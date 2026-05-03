$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Require-Command($Name, $Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is not installed. $Hint"
    }
}

function Run-Step($Title, [scriptblock] $Action) {
    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Title"
    }
}

function Resolve-UvLauncher {
    $uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    if (-not $uvCommand) {
        $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    }
    if ($uvCommand) {
        return @{
            FilePath = $uvCommand.Source
            PrefixArgs = @()
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source -m uv --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return @{
                FilePath = $pythonCommand.Source
                PrefixArgs = @("-m", "uv")
            }
        }
    }

    throw "uv is not available. Install it with: python -m pip install --user uv"
}

function Invoke-Uv([string[]] $Arguments) {
    $allArguments = $script:UvPrefixArgs + $Arguments
    & $script:UvFilePath @allArguments
}

Write-Host "BetExplorer Monitor setup" -ForegroundColor Green
Write-Host "Project folder: $Root"

Require-Command python "Install Python 3.11 or newer from https://www.python.org/downloads/ and add Python to Windows PATH."
Require-Command npm "Install Node.js LTS from https://nodejs.org/."

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Run-Step "Installing uv" { python -m pip install --user uv }
    $UserBase = (& python -m site --user-base).Trim()
    $UserScripts = Join-Path $UserBase "Scripts"
    if (Test-Path $UserScripts) {
        $env:PATH = "$UserScripts;$env:PATH"
    }
}

$uvLauncher = Resolve-UvLauncher
$script:UvFilePath = $uvLauncher.FilePath
$script:UvPrefixArgs = $uvLauncher.PrefixArgs
$uvLabel = @($script:UvFilePath) + $script:UvPrefixArgs -join " "
Write-Host "Using uv launcher: $uvLabel"

if (-not (Test-Path ".env")) {
    Copy-Item "config\settings.example.env" ".env"
    Write-Host "Created .env from config\settings.example.env"
}

Run-Step "Creating Python environment" { Invoke-Uv @("venv", ".venv") }
Run-Step "Installing Python dependencies" { Invoke-Uv @("pip", "install", "-e", ".") }
Run-Step "Installing UI dependencies" { npm --prefix apps/desktop/web install }

Write-Host ""
Write-Host "Setup completed. Use start-windows.cmd or the desktop shortcut to run the app." -ForegroundColor Green
