# BetExplorer Monitor: Client Start Guide

This folder contains the full BetExplorer Monitor app. The client does not need to type the API or UI commands manually.

## Windows

### First launch on a new computer

1. Install Python 3.14 or newer from https://www.python.org/downloads/.
2. Install Node.js LTS from https://nodejs.org/.
3. Open this project folder.
4. Double-click `setup-windows.cmd`.
   4A. If the `setup-windows.cmd` fails, head to the Fixes section below.
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

## Fixes

### Add Python to Windows PATH manually.

After installation, find where Python was installed. Common folders look like:

```text
C:\Users\<WindowsUser>\AppData\Local\Programs\Python\Python314\
C:\Users\<WindowsUser>\AppData\Local\Programs\Python\Python314\
С:\Python314\
```

Also find the `Scripts` folder inside it:

```text
C:\Users\<WindowsUser>\AppData\Local\Programs\Python\Python314\Scripts\
C:\Users\<WindowsUser>\AppData\Local\Programs\Python\Python314\Scripts\
С:\Python314\
```

Add both folders to Windows PATH:

1. Open Start menu.
2. Search for `Environment Variables`.
3. Open `Edit the system environment variables`.
4. Click `Environment Variables...`.
5. In `User variables`, select `Path`.
6. Click `Edit`.
7. Click `New`.
8. Add the Python folder, for example:

```text
C:\Users\<WindowsUser>\AppData\Local\Programs\Python\Python312\
```

9. Click `New` again.
10. Add the Python Scripts folder, for example:

```text
C:\Users\<WindowsUser>\AppData\Local\Programs\Python\Python312\Scripts\
```

11. Click `OK` on all windows.
12. Close and reopen `Command Prompt`.

Check that Windows can find Python:

Open `Command Prompt` from the Start menu and run:

```cmd
python --version
```

It should print something like:

```text
Python 3.14...
```

If Windows says that `python` is not recognized, the Python folders were not added to PATH correctly. Recheck both paths and reopen `Command Prompt`.
