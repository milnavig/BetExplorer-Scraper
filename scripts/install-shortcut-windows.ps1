$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "BetExplorer Monitor.lnk"
$TargetPath = Join-Path $Root "start-windows.cmd"
$IconPath = Join-Path $Root "apps\desktop\src-tauri\icons\icon.ico"

if (-not (Test-Path $TargetPath)) {
    throw "Cannot find launcher: $TargetPath"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = "Start BetExplorer Monitor"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Save()

Write-Host "Created desktop shortcut: $ShortcutPath" -ForegroundColor Green
