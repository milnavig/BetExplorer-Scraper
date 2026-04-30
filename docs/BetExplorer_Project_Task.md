# BetExplorer Final Odds Capture & Matching System

## 1. Project Goal

We need to develop a modular system for collecting final pre-match odds from BetExplorer and then comparing these odds with the client's historical database.

Main focus of the first version:

- Sport: Football;
- Data source: BetExplorer;
- Bookmakers: Bwin and Unibet;
- Odds type: final pre-match odds;
- Target matches: Upcoming / Just Started / Recently Started;
- Result: Structured data in the database + export to CSV/Excel;
- Further logic: matching with the client's historical database.

The main problem that needs to be solved: the odds table on BetExplorer is loaded dynamically, which is why the client's current scraper sometimes misses bookmaker lines, especially Bwin and Unibet. This leads to incomplete data and reduces the number of matches with the historical database.

---

## 2. Business Logic

The client already has:

- a historical database of football matches from BetExplorer;
- custom match search rules;
- matching criteria, for example:
- exact odds match;
- one draw match.

The new system should:

1. Find football matches that are about to start or have recently started.
2. Get the latest available pre-match odds.
3. Check that the Bwin and Unibet lines are actually loaded.
4. Save a snapshot of the odds.
5. Compare the snapshot with the historical database.
6. Return only interesting matches.
7. Allow results to be exported to CSV/Excel.

Important: the client doesn't need early odds. What is needed is the latest odds before the start of the match or the latest pre-match odds that BetExplorer displays after the match has gone live. However, saving match odds immediately after the start is also necessary.

---

## 3. Main Workflow

```text
1. Launch BetExplorer football match monitoring.
2. Find matches by time:
- starting soon;
- just started;
- recently started.
3. Open the odds page for each relevant match.
4. Get pre-match odds.
5. Wait for the bookmaker table to fully load.
6. Check for Bwin and Unibet.
7. If rows are missing, try again.
8. Save a valid snapshot.
9. Run the match against the historical database.
10. Save and export interesting results.
```

---

## 4. Architectural Principle

The project should be built as a modular monolith.

This means:

- one main backend project;
- Clear separation of modules;
- No microservices at launch;
- Modules can be changed independently;
- Business logic is not mixed with the scraper;
- Matching rules are isolated;
- Export is isolated;
- Monitoring UI is separate from the core logic.

The goal is to make the project easily modifiable, as matching rules, data sources, bookmakers, and export formats can change.

---

## 5. Tech Stack

### Backend / Core

Recommended core stack:

- Python 3.11+
- Playwright for browser automation
- httpx/aiohttp for HTTP requests, if possible using internal endpoints
- asyncio for parallel match processing
- DuckDB for fast analytical work with historical data
- SQLite or PostgreSQL for operational state, if needed
- pandas/openpyxl for CSV/Excel exports
- pydantic for models and configuration
- structlog/loguru for logging

### Desktop Monitoring App

Basic monorepo:

- Tauri
- Next.js
- TypeScript
- React
- local API bridge or reading data from a local database/API

## The UI is not needed as the main product, but for monitoring the system and matches.

## 6. Monorepo structure

```text
betexplorer-final-odds/
│
├── apps/
│   ├── desktop/
│   │   ├── src-tauri/
│   │   └── web/
│   │       ├── app/
│   │       ├── components/
│   │       └── package.json
│   │
│   └── api/
│       └── optional_local_api/
│
├── packages/
│   ├── core/
│   │   ├── config/
│   │   ├── models/
│   │   ├── logging/
│   │   └── utils/
│   │
│   ├── scraper/
│   │   ├── discovery/
│   │   ├── browser/
│   │   ├── extractors/
│   │   ├── validators/
│   │   └── retries/
│   │
│   ├── scheduler/
│   │   ├── live_monitor.py
│   │   ├── capture_queue.py
│   │   └── timing.py
│   │
│   ├── database/
│   │   ├── migrations/
│   │   ├── repositories/
│   │   └── db.py
│   │
│   ├── matcher/
│   │   ├── rules/
│   │   ├── matcher.py
│   │   └── result_builder.py
│   │
│   ├── exporter/
│   │   ├── csv_exporter.py
│   │   ├── excel_exporter.py
│   │   └── schemas.py
│   │
│   └── archive/
│       ├── archive_day_loader.py
│       ├── archive_match_collector.py
│       └── archive_odds_extractor.py
│
├── scripts/
│   ├── run_live_capture.py
│   ├── run_archive_scrape.py
│   ├── run_matcher.py
│   ├── export_results.py
│   └── db_migrate.py
│
├── data/
│   ├── exports/
│   ├── logs/
│   ├── raw_snapshots/
│   └── cache/
│
├── config/
│   ├── settings.example.env
│   └── bookmakers.yaml
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── docs/
│   ├── PROJECT_TASK.md
│   ├── ARCHITECTURE.md
│   ├── MATCHING_RULES.md
│   └── RUNBOOK.md
│
└── README.md
```

---

## 7. Modules

### 7.1 Scraper module

Responsible for all BetExplorer data extraction.

Responsibilities:

- discover football matches;
- open match pages;
- access odds tables;
- extract Bwin and Unibet odds;
- handle dynamic loading;
- validate loaded bookmaker rows;
- retry incomplete captures;
- store raw HTML/JSON snapshots for debugging.

Important rule:

The scraper must not assume that the first loaded table is complete. It must explicitly validate the presence of required bookmaker rows before saving the snapshot as complete.

Suggested internal structure:

```text
scraper/
├── discovery/
│   ├── football_match_discovery.py
│   └── match_list_parser.py
│
├── browser/
│   ├── browser_session.py
│   ├── page_loader.py
│   └── waiters.py
│
├── extractors/
│   ├── odds_table_extractor.py
│   ├── bookmaker_row_extractor.py
│   └── match_metadata_extractor.py
│
├── validators/
│   ├── bookmaker_presence_validator.py
│   └── odds_snapshot_validator.py
│
└── retries/
    ├── retry_policy.py
    └── capture_retry_runner.py
```

---

### 7.2 Match discovery module

This module finds matches that are relevant by timing.

The client does not care about leagues in the first version. Only football and timing matter.

Timing categories:

- `UPCOMING_SOON`
- `JUST_STARTED`
- `RECENTLY_STARTED`
- `LIVE`
- `FINISHED`
- `UNKNOWN`

Configurable windows:

```env
UPCOMING_WINDOW_MINUTES=30
RECENTLY_STARTED_WINDOW_MINUTES=10
FINAL_CAPTURE_POLL_INTERVAL_SECONDS=10
MAX_MATCH_AGE_AFTER_KICKOFF_MINUTES=10
```

Expected behavior:

- matches far from kickoff can be checked less frequently;
- matches close to kickoff should be checked more frequently;
- matches that recently started should still be checked because BetExplorer may still show last pre-match odds.

---

### 7.3 Final odds capture module

This is the most important part of the system.

Responsibilities:

- capture the latest available pre-match odds;
- increase polling frequency close to kickoff;
- support capture from upcoming/pre-match pages;
- support capture from live pages if BetExplorer still displays pre-match odds there;
- detect incomplete bookmaker tables;
- retry missing Bwin/Unibet rows;
- mark the best available snapshot as final.

Suggested algorithm:

```text
For each relevant football match:

1. Load match metadata.
2. Determine timing status.
3. If match is close to kickoff or recently started:
   3.1 Open odds page.
   3.2 Wait for odds table.
   3.3 Wait/check target bookmaker rows.
   3.4 Extract Bwin odds if available.
   3.5 Extract Unibet odds if available.
   3.6 Validate snapshot.
   3.7 If incomplete, retry according to retry policy.
   3.8 Save snapshot.
4. If match became live:
   4.1 Try to access the pre-match odds section/tab from the live page.
   4.2 Extract the latest available pre-match odds.
5. Select final snapshot.
6. Send snapshot to matching queue.
```

Snapshot quality levels:

```text
COMPLETE:
    Bwin and Unibet are both present.

PARTIAL:
    only one target bookmaker is present.

FAILED:
    no target bookmaker odds were captured.
```

The system should keep partial and failed attempts for debugging, but only complete or explicitly accepted partial snapshots should be used for matching.

---

### 7.4 Matching module

Matching must be fully separated from scraping.

Initial rules from the client:

- exact odds match;
- one draw match.

Rules should be implemented as independent classes.

Suggested structure:

```text
matcher/
├── rules/
│   ├── base_rule.py
│   ├── exact_odds_match.py
│   └── one_draw_match.py
│
├── matcher.py
└── result_builder.py
```

Example interface:

```python
from abc import ABC, abstractmethod

class MatchingRule(ABC):
    name: str

    @abstractmethod
    def match(self, captured_match, historical_data):
        pass
```

Expected behavior:

```text
1. Receive captured odds snapshot.
2. Load relevant historical records.
3. Run enabled matching rules.
4. Score or classify matches.
5. Return only interesting matches.
6. Save match results.
```

The matching module must allow adding new rules without changing scraper code.

---

### 7.5 Database module

The project needs a fast local data layer.

Recommended first version:

- DuckDB for historical matching and analytical queries;
- SQLite for runtime state if needed;
- PostgreSQL only if client already uses it or if the historical database is large and shared.

Suggested tables:

#### matches

```text
id
betexplorer_match_id
sport
league
home_team
away_team
kickoff_time
status
source_url
created_at
updated_at
```

#### odds_snapshots

```text
id
match_id
captured_at
capture_type
quality_status
is_final_candidate
is_final
source_page_type
raw_payload_path
created_at
```

`capture_type` examples:

```text
PRE_MATCH
LIVE_PREMATCH_TAB
ARCHIVE
```

`quality_status` examples:

```text
COMPLETE
PARTIAL
FAILED
```

#### bookmaker_odds

```text
id
snapshot_id
bookmaker
home_odds
draw_odds
away_odds
is_available
raw_row_text
created_at
```

#### match_results

```text
id
match_id
snapshot_id
rule_name
matched_historical_match_id
match_score
details_json
created_at
```

#### scrape_attempts

```text
id
match_id
source_url
attempt_number
status
error_message
bwin_found
unibet_found
started_at
finished_at
created_at
```

---

### 7.6 Export module

The system must support exports to:

- CSV
- Excel `.xlsx`

Export folders:

```text
data/exports/
├── final_odds_YYYY-MM-DD.csv
├── final_odds_YYYY-MM-DD.xlsx
├── matched_results_YYYY-MM-DD.csv
└── matched_results_YYYY-MM-DD.xlsx
```

Final odds export columns:

```text
captured_at
kickoff_time
status
league
home_team
away_team
source_url
bwin_home
bwin_draw
bwin_away
unibet_home
unibet_draw
unibet_away
quality_status
is_final
source_page_type
```

Matching export columns:

```text
captured_at
league
home_team
away_team
bwin_home
bwin_draw
bwin_away
unibet_home
unibet_draw
unibet_away
matched_rule
matched_historical_match_id
match_score
details
source_url
```

---

## 8. Historical archive scraping

This is a secondary feature for later.

Goal:

Allow the user to select a historical date and scrape all football matches from BetExplorer archive for that day.

Workflow:

```text
1. User provides date.
2. System opens BetExplorer archive page for that date.
3. System collects all football matches.
4. System opens each match page.
5. System extracts Bwin and Unibet odds.
6. System saves structured data.
7. System exports CSV/Excel.
8. Optionally inserts data into historical database.
```

Important:

Archive scraping should reuse the same odds extraction and validation logic as live capture.

Do not duplicate bookmaker parsing logic.

---

## 9. Performance and parallelism

Speed is important.

The system should support:

- asynchronous match processing;
- parallel capture workers;
- configurable concurrency;
- retry queue;
- batch database writes;
- fast matching against historical data;
- fast CSV/Excel exports.

Suggested worker flow:

```text
Discovery Worker
    -> finds relevant football matches

Capture Queue
    -> receives matches that need odds capture

Capture Workers
    -> process multiple match pages in parallel

Validation Layer
    -> checks Bwin/Unibet presence

Database Writer
    -> saves snapshots in batches

Matcher Worker
    -> compares snapshots against historical data

Exporter
    -> creates CSV/Excel output
```

Configuration:

```env
MAX_CONCURRENT_MATCHES=5
MAX_RETRIES_PER_MATCH=3
BOOKMAKER_WAIT_TIMEOUT_SECONDS=20
PAGE_LOAD_TIMEOUT_SECONDS=30
RETRY_DELAY_SECONDS=3
BATCH_INSERT_SIZE=100
```

Important:

Use responsible request rates and avoid unnecessary repeated page loads.

---

## 10. Reliability requirements

The system must handle:

- dynamic odds table loading;
- delayed bookmaker row rendering;
- missing bookmaker rows;
- temporary page loading failures;
- live page vs pre-match page differences;
- duplicate matches;
- duplicate snapshots;
- timezone issues;
- partial odds data;
- network errors;
- site layout changes.

Validation rules:

```text
1. A snapshot is COMPLETE only if both Bwin and Unibet are found.
2. A snapshot is PARTIAL if only one target bookmaker is found.
3. A snapshot is FAILED if neither Bwin nor Unibet is found.
4. Failed attempts must be logged.
5. Partial snapshots must be stored but not silently treated as complete.
6. The system must preserve raw data for debugging.
```

---

## 11. Monitoring app: Tauri + Next.js

Build a simple local monitoring UI.

The UI is not the main priority. Backend correctness is more important.

Initial pages:

### Dashboard

Show:

- scraper status;
- running/stopped state;
- monitored matches count;
- captured snapshots count;
- complete snapshots count;
- partial snapshots count;
- failed attempts count;
- matched results count;
- last successful capture time.

### Matches

Show:

- league;
- home team;
- away team;
- kickoff time;
- timing status;
- capture status;
- Bwin availability;
- Unibet availability;
- source URL;
- last captured time.

### Results

Show:

- interesting matches;
- rule name;
- odds;
- historical match reference;
- match score;
- export button.

### Logs

Show:

- latest events;
- warnings;
- failed attempts;
- missing bookmaker rows;
- retry attempts.

---

## 12. CLI commands

The project should work without UI via CLI.

Suggested commands:

```bash
python scripts/run_live_capture.py
python scripts/run_live_capture.py --once
python scripts/run_live_capture.py --sport football
python scripts/run_archive_scrape.py --date 2026-04-28
python scripts/run_matcher.py
python scripts/export_results.py --date 2026-04-28 --format xlsx
```

Optional later:

```bash
python scripts/run_monitor_api.py
python scripts/import_historical_db.py --file historical.csv
```

---

## 13. Configuration

Use `.env` or config files.

Example:

```env
BETEXPLORER_BASE_URL=https://www.betexplorer.com
SPORT=football

TARGET_BOOKMAKERS=Bwin,Unibet

UPCOMING_WINDOW_MINUTES=30
RECENTLY_STARTED_WINDOW_MINUTES=10
FINAL_CAPTURE_POLL_INTERVAL_SECONDS=10
MAX_MATCH_AGE_AFTER_KICKOFF_MINUTES=10

MAX_CONCURRENT_MATCHES=5
MAX_RETRIES_PER_MATCH=3
BOOKMAKER_WAIT_TIMEOUT_SECONDS=20
PAGE_LOAD_TIMEOUT_SECONDS=30
RETRY_DELAY_SECONDS=3

DATABASE_URL=duckdb:///data/betexplorer.duckdb
EXPORT_DIR=./data/exports
LOG_DIR=./data/logs
RAW_SNAPSHOT_DIR=./data/raw_snapshots

ENABLE_BROWSER_AUTOMATION=true
SAVE_RAW_HTML=true
```

Bookmakers should also be configurable:

```yaml
target_bookmakers:
  - Bwin
  - Unibet
```

---

## 14. Logging

Use structured logs.

Every important step should be logged.

Events to log:

- match discovered;
- match selected for capture;
- page opened;
- odds table found;
- Bwin found;
- Bwin missing;
- Unibet found;
- Unibet missing;
- retry started;
- snapshot saved;
- snapshot marked as final;
- matching started;
- matching result found;
- export completed;
- error occurred.

Suggested log fields:

```text
timestamp
level
module
event
match_id
home_team
away_team
source_url
attempt_number
bwin_found
unibet_found
details
error
```

---

## 15. Testing requirements

The code must be testable.

### Unit tests

Required test coverage:

- bookmaker name normalization;
- odds row parser;
- match timing classification;
- snapshot quality validation;
- matching rules;
- export formatting.

### Integration tests

Required integration tests:

- extract odds from saved HTML fixture;
- validate Bwin/Unibet extraction;
- match captured odds against sample historical data;
- export CSV;
- export Excel.

### Manual tests

Manual checks:

- monitor a few upcoming matches;
- verify captured odds manually on BetExplorer;
- verify behavior when Bwin is missing;
- verify behavior when Unibet is missing;
- verify capture shortly after kickoff;
- verify final CSV/Excel output.

---

## 16. Milestones

### Milestone 1 — Scraper + final odds capture logic

Budget reference: $350.

Scope:

- BetExplorer football match discovery;
- final pre-match odds capture;
- Bwin and Unibet extraction;
- dynamic table loading handling;
- retry logic for missing bookmaker rows;
- local database persistence;
- CSV/Excel export;
- basic logs.

Acceptance criteria:

```text
1. System can find relevant football matches by timing.
2. System can capture Bwin and Unibet odds.
3. System validates bookmaker row presence.
4. System retries incomplete captures.
5. System stores complete/partial/failed attempts.
6. System exports structured CSV/Excel files.
7. Logs are sufficient to debug missing odds.
```

### Milestone 2 — Matching + testing + monitoring

Budget reference: $300.

Scope:

- integrate matching with historical database;
- implement first matching rules;
- return only interesting matches;
- improve tests and error handling;
- add basic Tauri + Next.js monitoring UI;
- prepare run instructions.

Acceptance criteria:

```text
1. Captured odds are matched against historical data.
2. Matching rules are modular.
3. Interesting matches are saved and exported.
4. Monitoring UI shows system status, matches, results, and logs.
5. Project can be run from CLI.
6. Documentation explains setup and usage.
```

---

## 17. Future features

Possible later improvements:

- archive scraping by date;
- more bookmakers;
- more sports;
- scheduled archive backfill;
- Telegram alerts;
- email alerts;
- advanced dashboard analytics;
- more matching rules;
- Parquet exports;
- deployment on VPS/cloud;
- automatic daily reports.

---

## 18. Important development rules

1. Do not hardcode Bwin and Unibet deeply into the code.
   They should be configurable.

2. Do not mix scraping and matching logic.
   Scraper captures data. Matcher compares data.

3. Do not treat partial data as complete.
   Missing Bwin/Unibet must be visible in logs and database.

4. Do not build microservices for the first version.
   Use modular monolith.

5. Prioritize correctness of final odds capture over UI design.

6. Preserve raw snapshots for debugging.

7. Make matching rules easy to modify.

8. Make exports stable and predictable.

9. Use responsible scraping behavior and reasonable request limits.

10. Build the first version so it can be extended later without rewriting the core.
