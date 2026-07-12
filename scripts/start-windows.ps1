$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$ApiUrl = "http://127.0.0.1:8000/api/status"
$UiUrl = "http://127.0.0.1:3000"
$ApiCommandLabel = "uvicorn betexplorer_scraper.api:app"
$WebCommandLabel = "npm --prefix apps/desktop/web run dev"
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class Win32Job {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetInformationJobObject(IntPtr hJob, int infoClass, IntPtr info, uint length);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr hObject);

    public const int JobObjectExtendedLimitInformation = 9;
    public const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public long Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }
}
"@

function New-KillOnCloseJob {
    $job = [Win32Job]::CreateJobObject([IntPtr]::Zero, $null)
    if ($job -eq [IntPtr]::Zero) {
        throw "Cannot create Windows cleanup job."
    }

    $limits = New-Object Win32Job+JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    $limits.BasicLimitInformation.LimitFlags = [Win32Job]::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    $length = [Runtime.InteropServices.Marshal]::SizeOf($limits)
    $pointer = [Runtime.InteropServices.Marshal]::AllocHGlobal($length)
    try {
        [Runtime.InteropServices.Marshal]::StructureToPtr($limits, $pointer, $false)
        $ok = [Win32Job]::SetInformationJobObject(
            $job,
            [Win32Job]::JobObjectExtendedLimitInformation,
            $pointer,
            [uint32] $length
        )
        if (-not $ok) {
            throw "Cannot configure Windows cleanup job."
        }
        return $job
    } finally {
        [Runtime.InteropServices.Marshal]::FreeHGlobal($pointer)
    }
}

function Assign-ProcessToJob($process) {
    if (-not $process -or $process.HasExited) {
        return
    }

    $ok = [Win32Job]::AssignProcessToJobObject($script:ProcessJob, $process.Handle)
    if (-not $ok) {
        throw "Cannot attach process $($process.Id) to Windows cleanup job."
    }
}

function Stop-ProcessTree($ProcessId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree $child.ProcessId
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Require-Command($Name, $Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is not installed. $Hint"
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

    throw "uv is not available. Run setup-windows.cmd first. If it still fails, install uv with: python -m pip install --user uv"
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

function Test-UrlReady($Url) {
    try {
        Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-ServiceProcess($Name, $FilePath, [string[]] $Arguments, $OutLog, $ErrLog) {
    Write-Host "Starting $Name..." -ForegroundColor Cyan
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden `
        -PassThru
    Assign-ProcessToJob $process
    return $process
}

Require-Command npm "Install Node.js LTS from https://nodejs.org/ and run setup-windows.cmd again."

if (-not (Test-Path ".env")) {
    Copy-Item "config\settings.example.env" ".env"
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    $npmCommand = Get-Command npm
}
$uvLauncher = Resolve-UvLauncher
$UvFilePath = $uvLauncher.FilePath
$UvPrefixArgs = $uvLauncher.PrefixArgs
$npm = $npmCommand.Source
$apiOut = Join-Path $LogDir "api-launch.out.log"
$apiErr = Join-Path $LogDir "api-launch.err.log"
$webOut = Join-Path $LogDir "web-launch.out.log"
$webErr = Join-Path $LogDir "web-launch.err.log"

$api = $null
$web = $null
$script:ProcessJob = New-KillOnCloseJob

try {
    if (Test-UrlReady $ApiUrl) {
        Write-Host "API is already running: $ApiUrl" -ForegroundColor Green
    } else {
        $api = Start-ServiceProcess "API" $UvFilePath ($UvPrefixArgs + @("run", "uvicorn", "betexplorer_scraper.api:app", "--host", "127.0.0.1", "--port", "8000")) $apiOut $apiErr
        Wait-ForUrl $ApiUrl "API" 90
    }

    if (Test-UrlReady $UiUrl) {
        Write-Host "UI is already running: $UiUrl" -ForegroundColor Green
    } else {
        $web = Start-ServiceProcess "UI" $npm @("--prefix", "apps/desktop/web", "run", "dev") $webOut $webErr
        Wait-ForUrl $UiUrl "UI" 90
    }

    Start-Process $UiUrl

    Write-Host ""
    Write-Host "BetExplorer Monitor is running." -ForegroundColor Green
    Write-Host "Browser: $UiUrl"
    Write-Host "Logs: $LogDir"
    Write-Host "Keep this window open. Press Ctrl+C to stop."

    $managedProcesses = @($api, $web) | Where-Object { $_ -ne $null }
    while ($true) {
        foreach ($process in $managedProcesses) {
            if ($process.HasExited) {
                throw "One of the app processes stopped. Check logs in data\logs."
            }
        }
        Start-Sleep -Seconds 2
    }
} catch {
    Write-Host ""
    Write-Host "BetExplorer Monitor failed to stay running." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Logs: $LogDir"
    Read-Host "Press Enter to close"
    throw
} finally {
    foreach ($process in @($api, $web)) {
        if ($process -and -not $process.HasExited) {
            Stop-ProcessTree $process.Id
        }
    }
    if ($script:ProcessJob -and $script:ProcessJob -ne [IntPtr]::Zero) {
        [Win32Job]::CloseHandle($script:ProcessJob) | Out-Null
    }
}
