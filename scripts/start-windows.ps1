$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$ApiUrl = "http://127.0.0.1:8000/api/status"
$UiUrl = "http://127.0.0.1:3000"
$ApiCommandLabel = "uvicorn betexplorer_scraper.api:app"
$WebCommandLabel = "npm --prefix apps/desktop/web run dev"
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Require-Command($Name, $Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is not installed. $Hint"
    }
}

function Wait-ForUrl($Url, $Name, $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 3 | Out-Null
            Write-Host "$Name is ready: $Url" -ForegroundColor Green
            return
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "$Name did not start in $TimeoutSeconds seconds. Check logs in data\logs."
}

function Start-ServiceProcess($Name, $FilePath, [string[]] $Arguments, $OutLog, $ErrLog) {
    Write-Host "Starting $Name..." -ForegroundColor Cyan
    return Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden `
        -PassThru
}

Require-Command uv "Run setup-windows.cmd first. If it still fails, install uv with: python -m pip install --user uv"
Require-Command npm "Install Node.js LTS from https://nodejs.org/ and run setup-windows.cmd again."

if (-not (Test-Path ".env")) {
    Copy-Item "config\settings.example.env" ".env"
}

$uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    $uvCommand = Get-Command uv
}
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    $npmCommand = Get-Command npm
}
$uv = $uvCommand.Source
$npm = $npmCommand.Source
$apiOut = Join-Path $LogDir "api-launch.out.log"
$apiErr = Join-Path $LogDir "api-launch.err.log"
$webOut = Join-Path $LogDir "web-launch.out.log"
$webErr = Join-Path $LogDir "web-launch.err.log"

$api = $null
$web = $null

try {
    $api = Start-ServiceProcess "API" $uv @("run", "uvicorn", "betexplorer_scraper.api:app", "--host", "127.0.0.1", "--port", "8000") $apiOut $apiErr
    Wait-ForUrl $ApiUrl "API" 90

    $web = Start-ServiceProcess "UI" $npm @("--prefix", "apps/desktop/web", "run", "dev") $webOut $webErr
    Wait-ForUrl $UiUrl "UI" 90

    Start-Process $UiUrl

    Write-Host ""
    Write-Host "BetExplorer Monitor is running." -ForegroundColor Green
    Write-Host "Browser: $UiUrl"
    Write-Host "Logs: $LogDir"
    Write-Host "Keep this window open. Press Ctrl+C to stop."

    while (($api -and -not $api.HasExited) -and ($web -and -not $web.HasExited)) {
        Start-Sleep -Seconds 2
    }

    throw "One of the app processes stopped. Check logs in data\logs."
} finally {
    foreach ($process in @($api, $web)) {
        if ($process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
