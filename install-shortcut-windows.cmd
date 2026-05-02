@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-shortcut-windows.ps1"
if errorlevel 1 (
  echo.
  echo Shortcut creation failed. Press any key to close.
  pause >nul
  exit /b 1
)
echo.
echo Shortcut created. Press any key to close.
pause >nul
