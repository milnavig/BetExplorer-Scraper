# Milestone 2 UML / Workflow Diagrams

These diagrams describe the intended end-user workflow for the BetExplorer final odds monitor with historical DOCX matching.

## 1. End-User Use Case Diagram

```mermaid
flowchart LR
  User["End user / Tolga"] --> Run["Run monitor"]
  User --> Watch["Watch useful signals"]
  User --> OpenMatch["Open match explanation"]
  User --> Export["Export CSV/XLSX"]
  User --> Rescan["Rescan DOCX database when files change"]

  Run --> Discover["Discover football matches"]
  Run --> Capture["Capture final Bwin/Unibet odds"]
  Run --> Result["Capture final result"]

  Watch --> Signals["Historical signals feed"]
  OpenMatch --> Explain["Odds intelligence panel"]
  Export --> FinalOddsExport["Final odds export"]
  Export --> PlayedArchiveExport["Played match archive export"]
  Rescan --> ImportDocx["Import Odds / Usable Odds DOCX"]
```

## 2. System Component Diagram

```mermaid
flowchart TB
  UI["Next.js/Tauri monitoring UI"] --> API["FastAPI local API"]

  API --> Scheduler["API scheduler heartbeat"]
  API --> CaptureService["CaptureService"]
  API --> HistoricalImporter["HistoricalDocxImporter"]
  API --> SignalEngine["Historical signal engine"]
  API --> Exporter["CSV/XLSX exporter"]

  Scheduler --> CaptureService
  CaptureService --> BetExplorer["BetExplorer endpoints/pages"]
  HistoricalImporter --> DocxDb["Client DOCX folders<br/>Odds / Gebruikbare odds / Usable Odds"]

  CaptureService --> DuckDB["DuckDB local database"]
  HistoricalImporter --> DuckDB
  SignalEngine --> DuckDB
  Exporter --> DuckDB
  Exporter --> ExportFiles["data/exports"]

  DuckDB --> UI
```

## 3. End-User Activity Workflow

```mermaid
flowchart TD
  Start["User starts API + UI"] --> StartupImport{"HISTORICAL_AUTO_IMPORT enabled?"}
  StartupImport -->|Yes| Import["Scan DOCX folders and update historical index"]
  StartupImport -->|No| Dashboard["Open dashboard"]
  Import --> Dashboard

  Dashboard --> Monitor["Monitor upcoming/live football matches"]
  Monitor --> OddsReady{"Final Bwin/Unibet 1X2 odds captured?"}
  OddsReady -->|No| Waiting["Show waiting/missing bookmaker state"]
  OddsReady -->|Yes| Recompute["Recompute historical signals"]

  Recompute --> HasSignal{"Useful historical match found?"}
  HasSignal -->|No| Empty["Show no historical match state"]
  HasSignal -->|Yes| Feed["Show signal in dashboard feed"]

  Feed --> Detail["User opens match detail"]
  Detail --> Explain["Show odds, similarity, sample, stats, scores, why matched"]
  Explain --> Decision["User decides whether match is interesting"]

  Monitor --> Finished{"Match result captured?"}
  Finished -->|Yes| Archive["Archive played match locally"]
  Archive --> Export["User exports archive CSV/XLSX"]
```

## 4. Scheduler And Capture Sequence

```mermaid
sequenceDiagram
  participant UI as Dashboard UI
  participant API as FastAPI
  participant Scheduler as API Scheduler
  participant Capture as CaptureService
  participant BE as BetExplorer
  participant DB as DuckDB

  UI->>API: GET /api/status
  API->>DB: status()
  DB-->>API: scheduler/capture counts
  API-->>UI: status payload

  Scheduler->>Capture: run_once(trigger="api_scheduler")
  Capture->>BE: discover football matches
  BE-->>Capture: match schedule/live payload
  Capture->>DB: upsert matches
  Capture->>DB: list due scheduled matches

  loop due matches
    Capture->>BE: fetch match markets / odds payloads
    BE-->>Capture: bookmaker rows
    Capture->>DB: save scrape_attempt
    Capture->>DB: save odds_snapshot
    Capture->>DB: save bookmaker_odds
  end

  Capture-->>Scheduler: captured / failed / waiting counts
```

## 5. Historical DOCX Import Sequence

```mermaid
sequenceDiagram
  participant API as FastAPI Startup / Rescan
  participant Importer as HistoricalDocxImporter
  participant Files as DOCX folders
  participant DB as DuckDB

  API->>Importer: import_roots([HISTORICAL_DATABASE_ROOT])
  Importer->>Files: find folders matching Odds / Gebruikbare odds / Usable Odds

  loop each *.docx
    Importer->>DB: historical_file_is_current(path, fingerprint)
    alt unchanged
      DB-->>Importer: current
    else changed or new
      Importer->>Files: read DOCX tables
      Importer->>Importer: parse odds rows, score rows, inherited rows
      Importer->>DB: replace_historical_records(source_file, records)
      Importer->>DB: record_historical_import_file(...)
    end
  end

  API->>DB: recompute_historical_signals()
  API->>DB: archive_played_matches()
```

## 6. Historical Signal Matching Activity

```mermaid
flowchart TD
  Candidate["Final 1X2 odds row<br/>Bookmaker = Bwin or Unibet"] --> Normalize["Normalize odds to two decimals"]
  Normalize --> Exact["Find exact historical query odds<br/>home/draw/away equal"]
  Normalize --> Neighbor["Find nearby historical query odds<br/>each side within 0.05"]
  Normalize --> OneDraw["Find draw-side records<br/>draw within 0.05"]

  Exact --> ExactSignal{"Any records?"}
  ExactSignal -->|Yes| EmitExact["Emit exact_odds<br/>similarity 100<br/>rank 1"]

  Neighbor --> NeighborSignal{"Any records?"}
  NeighborSignal -->|Yes| EmitNeighbor["Emit neighbor_odds<br/>similarity by average distance<br/>rank 2"]

  OneDraw --> DrawSample{"sample >= 2?"}
  DrawSample -->|Yes| EmitDraw["Emit one_draw<br/>draw-only explanation<br/>rank 3"]

  EmitExact --> Stats["Calculate stats from historical FT scores"]
  EmitNeighbor --> Stats
  EmitDraw --> Stats

  Stats --> Store["Store historical_signals"]
```

## 7. Match Detail Explanation Sequence

```mermaid
sequenceDiagram
  participant User as User
  participant UI as Match page
  participant API as FastAPI
  participant DB as DuckDB

  User->>UI: Open /match?id={match_id}
  UI->>API: GET /api/matches/{match_id}
  UI->>API: GET /api/signals/{match_id}
  API->>DB: match_detail(match_id)
  API->>DB: list_signals(match_id)
  DB-->>API: match, snapshots, bookmaker odds, attempts
  DB-->>API: historical signal rows
  API-->>UI: detail + signals

  UI->>UI: show Bwin/Unibet odds
  UI->>UI: show best signal by rank/similarity/sample
  UI->>UI: show outcome stats and historical scores
  UI->>UI: show why matched: current odds vs matched historical odds vs difference
```

## 8. Archive And Export Sequence

```mermaid
sequenceDiagram
  participant Capture as CaptureService
  participant DB as DuckDB
  participant API as FastAPI
  participant UI as Dashboard UI
  participant Exporter as Exporter
  participant Files as data/exports

  Capture->>DB: update match result_captured_at + live_score
  API->>DB: archive_played_matches()
  DB->>DB: require final 1X2 snapshot + Bwin + Unibet + final score
  DB->>DB: upsert played_match_archive

  UI->>API: POST /api/exports/played-archive
  API->>DB: archive_played_matches()
  API->>DB: list_played_match_archive()
  API->>Exporter: export_played_match_archive(rows, csv/xlsx)
  Exporter->>Files: write played_match_archive_YYYY-MM-DD.csv/xlsx
  API-->>UI: filename + download_url
```

## 9. DuckDB Data Model Diagram

```mermaid
erDiagram
  matches ||--o{ odds_snapshots : has
  odds_snapshots ||--o{ bookmaker_odds : contains
  matches ||--o{ scrape_attempts : records
  matches ||--o{ historical_signals : produces
  historical_import_files ||--o{ historical_records : imports
  matches ||--o| played_match_archive : archives

  matches {
    string id PK
    string betexplorer_match_id
    string league
    string home_team
    string away_team
    timestamp kickoff_time
    string status
    string timing_status
    string capture_phase
    timestamp next_capture_at
    timestamp last_capture_at
    timestamp finalized_at
    timestamp result_captured_at
    string live_score
  }

  odds_snapshots {
    string id PK
    string match_id FK
    string event_id
    timestamp captured_at
    string market
    string capture_type
    string quality_status
    boolean is_final_candidate
    boolean is_final
    string required_bookmakers_json
  }

  bookmaker_odds {
    string id PK
    string snapshot_id FK
    string bookmaker
    string normalized_bookmaker
    double home_odds
    double draw_odds
    double away_odds
    boolean is_available
    string raw_row_text
  }

  historical_records {
    string id PK
    string dataset
    string source_file
    double query_home_odds
    double query_draw_odds
    double query_away_odds
    double historical_home_odds
    double historical_draw_odds
    double historical_away_odds
    string full_time_score
    string half_time_score
    string parse_status
    string parse_warning
  }

  historical_signals {
    string id PK
    string match_id FK
    string bookmaker
    string dataset
    string signal_type
    double current_home_odds
    double current_draw_odds
    double current_away_odds
    double matched_odds_home
    double matched_odds_draw
    double matched_odds_away
    double similarity_score
    int signal_rank
    int sample_size
    double home_win_pct
    double draw_pct
    double away_win_pct
    string historical_scores_json
  }

  played_match_archive {
    string match_id PK
    string event_id
    string league
    string home_team
    string away_team
    string full_time_score
    double bwin_home_odds
    double bwin_draw_odds
    double bwin_away_odds
    double unibet_home_odds
    double unibet_draw_odds
    double unibet_away_odds
    timestamp archived_at
  }
```

## 10. UI Information Architecture

```mermaid
flowchart TD
  App["BetExplorer Monitor UI"] --> Dashboard["Dashboard /"]
  App --> MatchPage["Match detail /match?id=..."]

  Dashboard --> Status["System status<br/>scheduler, next capture, DB import"]
  Dashboard --> Signals["Historical Signals feed"]
  Dashboard --> MatchList["Match list<br/>search/filter/sort/chunked loading"]
  Dashboard --> Selected["Selected match preview"]
  Dashboard --> Exports["Exports"]
  Dashboard --> Debug["Debug details<br/>raw bookmaker rows, attempts, snapshots, logs"]

  Signals --> SignalCard["Signal card/row<br/>match, kickoff, bookmaker odds, type, similarity, sample"]
  SignalCard --> MatchPage

  MatchPage --> OddsPanel["Odds intelligence panel"]
  OddsPanel --> OddsCards["Bwin / Unibet 1X2 odds"]
  OddsPanel --> Summary["Best signal summary<br/>type, similarity, sample, dataset"]
  OddsPanel --> Stats["Outcome stats<br/>H/D/A, Over, BTTS, Double Chance"]
  OddsPanel --> Why["Why matched<br/>current vs historical odds"]
  OddsPanel --> Scores["Historical score examples"]
  MatchPage --> Raw["Raw odds/snapshots/attempts"]
```

## UX Meaning For Figma

- Main screen should prioritize: useful signal, kickoff/time state, Bwin/Unibet availability, current odds, similarity, sample size.
- Match detail should answer: what current odds are being compared, what historical odds pattern matched, how strong the match is, and what happened historically.
- Technical data still exists but should be secondary: raw bookmaker rows, attempts, snapshots, logs, source files, parse warnings.
- DOCX files do not contain match IDs. Historical matching is odds-pattern based, not same-match-ID based.
