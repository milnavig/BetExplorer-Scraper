# BetExplorer Monitor: Client Start Guide

This folder contains the full BetExplorer Monitor app. The client does not need to type the API or UI commands manually.

## Windows

### First launch on a new computer

1. Install Python 3.11 or newer from https://www.python.org/downloads/.
2. Install Node.js LTS from https://nodejs.org/.
3. Open this project folder.
4. Double-click `setup-windows.cmd`.
5. Double-click `install-shortcut-windows.cmd`.

The shortcut creates `BetExplorer Monitor.lnk` on the Desktop. It uses the app icon from `apps\desktop\src-tauri\icons\icon.ico`.

### Normal daily launch

1. Double-click the `BetExplorer Monitor` shortcut on the Desktop.
2. Wait until the browser opens.
3. Use the app at http://127.0.0.1:3000.
4. Keep the launcher window open while using the app.
5. To stop the app, press `Ctrl+C` in the launcher window or close it.

If the shortcut is not installed, double-click `start-windows.cmd` in the project folder.

## macOS / Linux

### First launch on a new computer

1. Install Python 3.11 or newer.
2. Install Node.js LTS from https://nodejs.org/.
3. Open Terminal in this project folder.
4. Run:

```bash
bash setup-unix.sh
bash install-shortcut-unix.sh
```

On macOS this creates `BetExplorer Monitor.command` on the Desktop. On Linux this creates `BetExplorer Monitor.desktop` on the Desktop.

### Normal daily launch

1. Open the Desktop launcher, or run:

```bash
bash start-unix.sh
```

2. Wait until the browser opens.
3. Use the app at http://127.0.0.1:3000.
4. Keep the terminal open while using the app.
5. To stop the app, press `Ctrl+C` in the terminal.

## Export Files

Exports are saved in `data/exports`.

The UI has buttons for:

- `CSV`: compact wide table.
- `Long CSV`: one row per bookmaker market line.
- `XLSX`: compact Excel table.
- `Long XLSX`: detailed Excel table.

## Logs

If something does not start, check:

- `data/logs/api-launch.err.log`
- `data/logs/api-launch.out.log`
- `data/logs/web-launch.err.log`
- `data/logs/web-launch.out.log`

## Packaging For Windows

To prepare a clean folder and ZIP for the client, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\package-windows.ps1
```

The package is created at:

```text
dist\BetExplorer-Monitor-Client.zip
```

The client can unzip it, run `setup-windows.cmd` once, install the shortcut, and then use the Desktop shortcut.
