# BetExplorer Final Odds Monitor

Local monitoring system for tracking BetExplorer football matches, capturing final pre-match odds markets, storing all bookmaker rows, saving finished results, and monitoring capture state from a Next.js/Tauri UI.

## What It Does

- Discovers football matches from BetExplorer.
- Tracks kickoff timing with a scheduler:
  - `WAITING`: match is too far from kickoff.
  - `MONITORING`: match is inside the pre-kickoff capture window.
  - `FINALIZING`: match has started but is still inside the post-kickoff capture window.
  - `FINALIZED`: capture window is over.
- Captures all available bookmaker rows from BetExplorer direct HTTP endpoints for every market tab exposed on the match page.
- Starts odds monitoring for matches up to `ODDS_CAPTURE_LOOKAHEAD_HOURS` ahead, default 6 hours.
- Captures finished match results once for matches discovered within `RESULT_CAPTURE_LOOKBACK_HOURS`, default 24 hours.
- Uses Bwin and Unibet as required bookmaker quality checks by default.
- Saves matches, snapshots, bookmaker odds, attempts, logs, and scheduler state to DuckDB.
- Imports the client file-based DOCX historical odds database and shows Bwin/Unibet historical signals.
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
CAPTURE_MARKET=all
BETEXPLORER_TIMEZONE_OFFSET=+3
UPCOMING_WINDOW_MINUTES=30
ODDS_CAPTURE_LOOKAHEAD_HOURS=6
RESULT_CAPTURE_LOOKBACK_HOURS=24
RESULT_FINISH_GRACE_MINUTES=120
RESULT_CHECK_RETRY_SECONDS=3600
RESULT_BACKFILL_BATCH_SIZE=200
FINALIZE_AFTER_KICKOFF_MINUTES=5
MONITORING_CAPTURE_POLL_INTERVAL_SECONDS=120
FINAL_CAPTURE_POLL_INTERVAL_SECONDS=20
FINAL_CAPTURE_FAST_WINDOW_MINUTES=3
DISCOVERY_DAYS_AHEAD=1
SCHEDULER_TICK_SECONDS=10
MAX_CONCURRENT_CAPTURES=6
RETRY_DELAY_SECONDS=1
DATABASE_PATH=data/betexplorer.duckdb
HISTORICAL_DATABASE_ROOT=SAMPLE_DATABASE
```

`BETEXPLORER_TIMEZONE_OFFSET` is important: BetExplorer changes the visible "today" schedule based on the `my_timezone` cookie. For Kyiv time keep `+3`, otherwise the scraper can see the previous UTC day and `Next capture` may look empty or stale.

## Run The API

Terminal 1:

```powershell
uv run uvicorn betexplorer_scraper.api:app --host 127.0.0.1 --port 8000
```

By default the FastAPI process also starts the continuous scheduler heartbeat (`ENABLE_API_SCHEDULER=true`). The UI `Run once` button is only a manual extra cycle; it is not required for normal monitoring while the API is running.

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

Use this external loop only when `ENABLE_API_SCHEDULER=false` or when the API is not running. Do not run both schedulers against the same DuckDB file unless you intentionally want duplicate capture pressure.

The continuous loop checks due matches every `SCHEDULER_TICK_SECONDS`, but full BetExplorer discovery is throttled by `DISCOVERY_POLL_INTERVAL_SECONDS`. Odds polling is adaptive: matches enter monitoring up to `ODDS_CAPTURE_LOOKAHEAD_HOURS` before kickoff, normal polling uses `MONITORING_CAPTURE_POLL_INTERVAL_SECONDS`, then switches to `FINAL_CAPTURE_POLL_INTERVAL_SECONDS` during the last `FINAL_CAPTURE_FAST_WINDOW_MINUTES` before kickoff and shortly after kickoff. Current defaults are intentionally moderate for `CAPTURE_MARKET=all`: every 120 seconds in the early window, every 20 seconds in the last 3 minutes, and up to 5 minutes after kickoff. Results are captured separately once per finished match in the configured 24-hour lookback.

Performance notes:
- `MAX_CONCURRENT_CAPTURES` controls how many due matches run in parallel.
- `MAX_CONCURRENT_MARKETS_PER_MATCH` controls how many market endpoints run in parallel inside a single match.
- `MARKET_DISCOVERY_CACHE_SECONDS` caches the match-page market tab list so repeated final-window captures do not reload the match page every time.
- A market payload with bookmaker rows is saved once per cycle even when Bwin/Unibet are missing; retries are reserved for errors or empty payloads.

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

## Historical Odds Signals

Milestone 2 adds a local historical matching layer for the client DOCX database. Configure:

```env
HISTORICAL_DATABASE_ROOT=SAMPLE_DATABASE
```

The importer scans dataset folders named like `Odds`, `Gebruikbare odds`, `*ODDS`, or `*Usable Odds`, reads DOCX tables, and stores normalized historical odds/results in DuckDB. It does not modify the original DOCX files.

From the dashboard:

- Click `Import DOCX` in `Historical signals` to import changed DOCX files and recompute signals.
- Click `Recompute` after new final Bwin/Unibet odds are captured.
- Filter signals by dataset, bookmaker, signal type, and minimum sample size.

API endpoints:

- `GET /api/historical/import-status`
- `POST /api/historical/import`
- `GET /api/signals`
- `GET /api/signals/{match_id}`
- `POST /api/signals/recompute`

Export status fields:

- `status`: practical export status, using `capture_phase` first, then finalized/live timing, and never `UNKNOWN` for captured rows.
- `timing_status`: raw timing classifier stored by the scraper; this can still be `UNKNOWN` for diagnostics.
- `match_status`: raw discovered/live status.
- `capture_phase`: scheduler phase such as `MONITORING`, `FINALIZING`, or `FINALIZED`.

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
- `CAPTURE_MARKET=all` discovers BetExplorer market tabs from the match page, for example `1x2`, `ou`, `ah`, `dc`, and `bts`. Set it to a single market id like `1x2` to restrict capture.
- Odds rows use generic `Odd 1`, `Odd 2`, `Odd 3` columns because markets can be two-outcome or three-outcome.
- Matching against the client historical database is not implemented yet.
