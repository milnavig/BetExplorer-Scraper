# BetExplorer Final Odds Monitor

Local API-first system for tracking BetExplorer football matches, capturing final 1X2 pre-match odds, storing all bookmaker rows, and monitoring capture state from a Next.js/Tauri UI.

## What It Does

- Discovers football matches from BetExplorer.
- Tracks kickoff timing with a scheduler:
  - `WAITING`: match is too far from kickoff.
  - `MONITORING`: match is inside the pre-kickoff capture window.
  - `FINALIZING`: match has started but is still inside the post-kickoff capture window.
  - `FINALIZED`: capture window is over.
- Captures all available 1X2 bookmaker rows from BetExplorer direct HTTP endpoints.
- Uses Bwin and Unibet as required bookmaker quality checks by default.
- Saves matches, snapshots, bookmaker odds, attempts, logs, and scheduler state to DuckDB.
- Exports CSV/XLSX.
- Provides a local monitoring UI.

## Requirements

- Python 3.11+
- uv
- Node.js 22.22+ recommended
- npm
- Rust + Cargo only if you want to run/build the Tauri desktop shell

This machine currently uses nvm-windows. To update Node:

```powershell
nvm list available
nvm install 22.22.0
nvm use 22.22.0
node -v
npm -v
```

Open a new terminal after `nvm use` if old Node is still picked up.

## First Setup

From the repo root:

```powershell
python -m pip install uv
uv venv .venv --python 3.11
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[test]"
npm install --prefix apps/desktop/web
npm install --prefix apps/desktop
Copy-Item config/settings.example.env .env
```

After this, keep using the activated `.venv` terminal for backend commands. If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Adjust `.env` if needed. Useful defaults:

```env
TARGET_BOOKMAKERS=Bwin,Unibet
BETEXPLORER_TIMEZONE_OFFSET=+3
UPCOMING_WINDOW_MINUTES=30
MAX_MATCH_AGE_AFTER_KICKOFF_MINUTES=10
FINAL_CAPTURE_POLL_INTERVAL_SECONDS=2
DISCOVERY_DAYS_AHEAD=1
SCHEDULER_TICK_SECONDS=1
MAX_CONCURRENT_CAPTURES=6
RETRY_DELAY_SECONDS=1
DATABASE_PATH=data/betexplorer.duckdb
```

`BETEXPLORER_TIMEZONE_OFFSET` is important: BetExplorer changes the visible "today" schedule based on the `my_timezone` cookie. For Kyiv time keep `+3`, otherwise the scraper can see the previous UTC day and `Next capture` may look empty or stale.

## Run The API

Terminal 1:

```powershell
uv run uvicorn betexplorer_scraper.api:app --host 127.0.0.1 --port 8000
```

Check:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/status -UseBasicParsing
```

API URL:

```text
http://127.0.0.1:8000
```

## Run The Monitoring UI

Terminal 2:

```powershell
npm --prefix apps/desktop/web run dev
```

Open:

```text
http://127.0.0.1:3000
```

The UI expects the API at `http://127.0.0.1:8000`.

## Run A Capture

One pass:

```powershell
uv run python scripts/run_live_capture.py --once
```

Continuous scheduler loop:

```powershell
uv run python scripts/run_live_capture.py
```

The continuous loop does discovery repeatedly, updates scheduler state, and only captures odds for matches that are due. With the default fast-capture settings, the loop wakes every 1 second, checks due matches concurrently, and polls final-window odds every 2 seconds.

## Export Results

CSV:

```powershell
uv run python scripts/export_results.py --date 2026-04-28 --format csv
```

Excel:

```powershell
uv run python scripts/export_results.py --date 2026-04-28 --format xlsx
```

Exports are written to:

```text
data/exports/
```

## Run Tauri Desktop Shell

The Tauri shell loads the same Next UI.

```powershell
npm --prefix apps/desktop run dev
```

Build desktop app:

```powershell
npm --prefix apps/desktop run build
```

If Cargo complains about missing platform tooling, install the normal Tauri Windows prerequisites.

## Useful Checks

Backend tests:

```powershell
uv run python -m pytest tests -q -p no:cacheprovider
```

Next build:

```powershell
npm --prefix apps/desktop/web run build
```

Tauri Rust check:

```powershell
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
```

Dependency audit:

```powershell
npm --prefix apps/desktop/web audit
npm --prefix apps/desktop audit
```

## Data Locations

- DuckDB database: `data/betexplorer.duckdb`
- Raw BetExplorer payloads: `data/raw_snapshots/`
- Exports: `data/exports/`
- Local logs: `data/logs/`
- HAR references: `har/`

## API Endpoints

- `GET /api/status`
- `GET /api/matches`
- `GET /api/matches/{id}`
- `GET /api/snapshots`
- `GET /api/logs`
- `POST /api/capture/run-once`
- `POST /api/exports/final-odds`

## Notes

- The scraper is HTTP-first. Browser automation is intentionally left as a fallback interface, not the default.
- “All bookmakers” currently means all available bookmaker rows for the 1X2 market.
- Matching against the client historical database is not implemented yet.
