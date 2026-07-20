# BetExplorer Ingestion Reliability Rebuild Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild historical DOCX ingestion, final-odds composition, historical-date backfill, and signal matching so the eight client cases produce deterministic and explainable results.

**Architecture:** Treat imported client history, automatically collected played matches, raw bookmaker observations, and derived signals as separate data layers. Imports and backfills become versioned, idempotent jobs; matching reads only validated complete historical blocks and composed per-bookmaker final odds.

**Tech Stack:** Python 3.12+, FastAPI, DuckDB, python-docx, httpx, Next.js/React, pytest, TypeScript.

## Global Constraints

- Do not use TDD. Implement each task from the agreed contract, then add and run focused regression tests.
- An imported ZIP replaces the active client historical database atomically; it never appends another logical copy.
- DOCX contains no bookmaker labels. Apply the client contract: first odds row in each pair is Bwin, second is Unibet.
- Every DOCX table has an even number of odds-bearing rows in the audited 385-file sample; parse consecutive odds rows as complete pairs.
- Scores found on either row of a pair and subsequent score-only rows are outcomes attached to that complete pair.
- The default matching search order is exactly `Odds`, then `Usable Odds`. `Played archive` must not silently participate.
- Exact means all six odds are identical. One Draw means all four home/away odds are identical and exactly one of the two draw odds differs.
- One Draw with one historical outcome is visible with low strength; sample size is not a visibility gate.
- No legacy database migration is required; initialize the rebuilt schema from a clean database.
- Long-running import, backfill, repair, and recompute work must not block `/api/status`.

---

## Confirmed DOCX Contract

The available sample contains 385 DOCX files and 2,243 tables:

- 1,878 tables have exactly two odds-bearing rows.
- Every remaining odds table has 4, 6, 8, or another even number of odds-bearing rows.
- No table has an odd number of odds-bearing rows.
- No DOCX contains the text `Bwin` or `Unibet`.
- The dominant shape is `odds-only row -> odds+score row`.
- Some pairs contain scores on both rows, often different; both scores must be preserved as separate outcomes for the complete six-odds pair.
- Some pairs are followed by score-only rows; those are additional outcomes for the preceding pair.

Bookmaker identity therefore comes from Tolga's specification, while row pairing is strongly supported by the file structure.

**Required acceptance decision before Task 1:** In 170 adjacent scored-row cases, the two rows contain different full-time scores. The proposed rule is to attach both as separate outcomes to the paired six-odds block. Confirm this interpretation with Tolga; the files themselves cannot prove whether one of those scores should be ignored.

## Confirmed Runtime Bottlenecks

- All database methods share one DuckDB connection and one process-wide `RLock`; slow reads and writes block each other.
- `/api/matches-page` builds the complete match aggregate, converts every row to Python, then filters, sorts, and paginates in memory.
- `match_detail()` also builds the complete match list before selecting one match and returns every snapshot and attempt for it.
- `/api/status` performs many aggregate scans and joins over snapshot, odds, attempt, and match tables every five seconds.
- The dashboard launches nine API requests together every 30 seconds; the backend serializes them behind the same database lock.
- One odds payload is persisted through a snapshot insert followed by individual bookmaker-row inserts without one explicit batch transaction.
- Raw payload files are written synchronously from the async capture loop.
- Discovery date pages and near-kickoff page enrichment are fetched sequentially before capture planning completes.
- Normal monitor capture, result recovery, Force Recapture, and historical backfill share execution state and compete without explicit priority or backpressure.
- Any successful scheduler cycle can trigger a full archive scan and full signal recompute; observed pauses were commonly 80-92 seconds before indexing improvements.

The target ingest design must separate network fetch, parsing, durable writes, derived-data updates, and UI reads instead of running them as one request/cycle.

---

### Task 1: Introduce a Complete Historical Block Parser

**Files:**
- Create: `apps/api/src/betexplorer_scraper/historical_parser.py`
- Modify: `apps/api/src/betexplorer_scraper/historical.py`
- Test: `tests/test_historical_parser.py`

**Interfaces:**
- Produce `HistoricalBlock(dataset, logical_source_file, table_index, block_index, bwin_odds, unibet_odds, outcomes, warnings)`.
- Produce `HistoricalOutcome(full_time_score, half_time_score, source_row_index)`.
- Consume one DOCX path plus its logical path relative to the uploaded ZIP root.

- [ ] Add immutable dataclasses for `HistoricalBlock` and `HistoricalOutcome`.
- [ ] Parse each table by collecting odds-bearing rows in document order and pairing indices `(0,1)`, `(2,3)`, and so on.
- [ ] Assign the first row of every pair to Bwin and the second to Unibet.
- [ ] Attach valid FT/HT scores from either paired row to the block.
- [ ] Attach score-only rows after a completed pair to that pair until the next odds-bearing row starts a new pair.
- [ ] Preserve duplicate outcomes when they originate from distinct document rows; they represent distinct historical samples.
- [ ] Quarantine a table instead of guessing if it has an odd odds-row count, an incomplete odds triplet, or a score before the first complete pair.
- [ ] Return structured warning codes including file, table, row, and reason.
- [ ] Replace the stateful `query_odds` parser in `historical.py` with the complete-block parser.
- [ ] Add regression coverage for `O-OS`, `OS-OS`, `O-OS-S`, multiple pairs per table, malformed odd rows, and the structures from client Cases 1-6.
- [ ] Verify all 385 sample files parse and publish totals for blocks, outcomes, and quarantined rows.

**Acceptance:** No score-bearing row is silently removed merely because it lacks odds, and every matching record always has six odds.

### Task 2: Make Historical ZIP Import Versioned and Atomic

**Files:**
- Create: `apps/api/src/betexplorer_scraper/historical_import.py`
- Modify: `apps/api/src/betexplorer_scraper/api.py`
- Modify: `apps/api/src/betexplorer_scraper/database.py`
- Modify: `apps/desktop/web/app/page.tsx`
- Test: `tests/test_api_historical.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Produce `HistoricalImportReport(batch_id, status, files, blocks, outcomes, warnings, content_sha256)`.
- Add `POST /api/historical/import-zip` returning an accepted job identifier.
- Add `GET /api/historical/import-jobs/{job_id}` returning durable progress and the validation report.

- [ ] Add `historical_import_batches`, `historical_blocks`, and `historical_outcomes` tables.
- [ ] Store logical relative paths from the ZIP, never machine-specific absolute paths.
- [ ] Hash ZIP bytes and normalized file contents; do not include extraction path or modification time in identity.
- [ ] Parse into a staging batch and leave the current active batch untouched on any validation failure.
- [ ] Activate the staging batch in one transaction after parsing and validation succeeds.
- [ ] Deactivate the previous client batch so matching sees exactly one imported database version.
- [ ] Treat re-import of the same content hash as an idempotent no-op with a clear UI result.
- [ ] Stop auto-merging the bundled `SAMPLE_DATABASE` with a user-imported ZIP.
- [ ] Keep the bundled sample only as an explicit demo database when no client batch has ever been activated.
- [ ] Show imported file, block, outcome, warning, and rejected-row counts in the import result.
- [ ] Verify importing the same 385-file ZIP three times still leaves one active set, not 1,155 files.

**Acceptance:** Importing Tolga's database replaces the sample database and cannot inflate sample sizes through path changes or repeated uploads.

### Task 3: Rebuild Matching Around Active Complete Blocks

**Files:**
- Create: `apps/api/src/betexplorer_scraper/matching.py`
- Modify: `apps/api/src/betexplorer_scraper/database.py`
- Modify: `apps/api/src/betexplorer_scraper/historical.py`
- Test: `tests/test_historical_signals.py`

**Interfaces:**
- Consume `CurrentOddsBlock` containing complete Bwin and Unibet 1X2 odds.
- Consume active `HistoricalBlock` rows and their one-to-many outcomes.
- Produce separate `ExactSignal` and `OneDrawSignal` aggregates with source dataset and block/outcome provenance.

- [ ] Move exact and One Draw predicates from `database.py` into pure matching functions.
- [ ] Search all Exact and One Draw blocks in `Odds` first.
- [ ] Search Exact in `Usable Odds` only when `Odds` has no Exact; always collect valid Usable One Draw blocks.
- [ ] Merge One Draw outcomes from `Odds` and `Usable Odds` without merging Exact into them.
- [ ] Remove `ONE_DRAW_MIN_SAMPLE` as an emission gate.
- [ ] Keep `n=1` visible and classify it as low strength in presentation logic.
- [ ] Exclude `Played archive` from this default workflow.
- [ ] Keep Played archive accessible as a separate source/filter for future explicit client approval.
- [ ] Calculate percentages and common scores only from outcomes attached to the selected matched blocks.
- [ ] Store matched block IDs and outcome IDs with every generated signal for auditability.
- [ ] Verify Case 3 emits both Exact and One Draw as separate results.

**Acceptance:** Signal source, six compared odds, matched blocks, sample size, scores, and statistics can all be traced to the active imported ZIP.

### Task 4: Compose Final Odds Per Bookmaker

**Files:**
- Create: `apps/api/src/betexplorer_scraper/final_odds.py`
- Modify: `apps/api/src/betexplorer_scraper/database.py`
- Modify: `apps/api/src/betexplorer_scraper/capture.py`
- Modify: `apps/api/src/betexplorer_scraper/models.py`
- Test: `tests/test_database.py`
- Test: `tests/test_capture_scheduler.py`

**Interfaces:**
- Preserve every raw `OddsSnapshot`.
- Produce one `FinalBookmakerObservation` per match, market, and required bookmaker.
- Produce `ComposedFinalOdds` only when valid Bwin and Unibet observations are available.

- [ ] Add a durable final-bookmaker selection table or equivalent materialized relation.
- [ ] Select the latest valid Bwin observation independently from the latest valid Unibet observation.
- [ ] Accept observations captured shortly after kickoff when the endpoint still returns the pre-match market, as required by the client.
- [ ] Record capture timestamp, distance to kickoff, raw snapshot ID, and quality for each bookmaker.
- [ ] Never let a later missing bookmaker erase an earlier valid bookmaker value.
- [ ] Let a later valid Bwin update Bwin even when the same payload is missing Unibet, and vice versa.
- [ ] Build signal candidates from composed bookmaker finals rather than one whole-snapshot `is_final` flag.
- [ ] Mark the composed pair stale or incomplete when either bookmaker is older than the configured capture policy.
- [ ] Extend the repair operation to rebuild composed finals from existing raw snapshots.
- [ ] Verify Case 7 selects Bwin `1.70 / 3.80 / 3.70` instead of retaining the 30-minute-old row.

**Acceptance:** The displayed final Bwin and Unibet odds are independently the latest valid pre-match observations with visible provenance.

### Task 5: Build a Priority and Backpressured Ingest Pipeline

**Files:**
- Create: `apps/api/src/betexplorer_scraper/ingest.py`
- Create: `apps/api/src/betexplorer_scraper/database_writer.py`
- Modify: `apps/api/src/betexplorer_scraper/capture.py`
- Modify: `apps/api/src/betexplorer_scraper/transport.py`
- Modify: `apps/api/src/betexplorer_scraper/database.py`
- Modify: `apps/api/src/betexplorer_scraper/config.py`
- Test: `tests/test_ingest_pipeline.py`
- Test: `tests/test_capture_scheduler.py`

**Interfaces:**
- Produce `CaptureRequest(event_id, match_id, market, source_url, priority, reason, deadline)`.
- Produce `CaptureEnvelope(request, captured_at, raw_payload, parsed_odds, quality, required_presence, error)`.
- `IngestCoordinator.submit()` accepts bounded work without touching DuckDB.
- `DatabaseWriter.persist_batch()` writes complete envelopes in one transaction and emits affected match IDs.

- [ ] Define priority lanes in this order: kickoff/final live capture, normal upcoming monitoring, result recovery, manual recapture, historical backfill.
- [ ] Give requests deadlines and deduplicate queued work by `(event_id, market, reason window)` so scheduler ticks cannot enqueue the same capture repeatedly.
- [ ] Add a bounded fetch queue and explicit backpressure instead of creating an unbounded `asyncio.gather` for every due job.
- [ ] Add a host-level concurrency limiter and request-rate limiter shared by every BetExplorer transport call.
- [ ] Make concurrency adaptive: reduce backfill workers after timeouts/429/5xx responses and restore them gradually after healthy responses.
- [ ] Reserve at least one fetch slot for kickoff-priority work so a large backfill cannot delay live final odds.
- [ ] Fetch independent discovery date pages concurrently with a small fixed limit, then deduplicate event IDs before planning.
- [ ] Avoid match-page enrichment when stored kickoff/result data is already sufficient.
- [ ] Keep HTTP fetch and HTML/JSON parsing outside the database writer and outside any database lock.
- [ ] Move raw-payload persistence to an asynchronous file writer using `asyncio.to_thread`, bounded queueing, compression, and a retention policy.
- [ ] Persist one snapshot, all bookmaker rows, the attempt, and the match schedule update in one DuckDB transaction.
- [ ] Batch multiple completed envelopes into short writer transactions capped by item count and elapsed milliseconds.
- [ ] Emit affected match IDs after commit so final-odds composition and signal updates are incremental.
- [ ] Persist queue depth, oldest-item age, active workers, throughput, retry rate, and last successful commit as lightweight runtime metrics.
- [ ] Verify normal monitoring preempts a running backfill and captures a kickoff-priority request within its configured polling deadline.
- [ ] Verify queue memory remains bounded during a 315-match historical-date import.

**Acceptance:** Backfill may take time, but it cannot monopolize fetch slots, grow an unbounded task set, or delay live final-odds capture.

### Task 6: Implement Durable Historical-Date Backfill Jobs

**Files:**
- Create: `apps/api/src/betexplorer_scraper/jobs.py`
- Create: `apps/api/src/betexplorer_scraper/archive_jobs.py`
- Modify: `apps/api/src/betexplorer_scraper/api.py`
- Modify: `apps/api/src/betexplorer_scraper/capture.py`
- Modify: `apps/api/src/betexplorer_scraper/database.py`
- Test: `tests/test_capture_scheduler.py`
- Test: `tests/test_api_historical.py`

**Interfaces:**
- `POST /api/archive/date` creates or resumes a durable job and returns immediately.
- `GET /api/archive/jobs/{job_id}` reports stable totals and per-stage progress.
- Each event item has `discovered`, `odds_pending`, `odds_complete`, `score_complete`, `archived`, or `failed` state.

- [ ] Add `archive_jobs` and `archive_job_items` tables with unique `(target_date, event_id)` identity.
- [ ] Deduplicate discovery by event ID before persisting the job total.
- [ ] Store the discovery total once so the denominator cannot switch to another capture queue.
- [ ] Resume unfinished items after application restart.
- [ ] Use bounded concurrency for event processing while retaining per-event retries and error messages.
- [ ] Submit odds work to the Task 5 ingest coordinator at backfill priority instead of fetching and writing inline.
- [ ] Persist successful odds and score stages independently so one failed step does not discard the other.
- [ ] Compose final bookmaker odds and archive each completed match immediately.
- [ ] Recompute or upsert signals for each completed event instead of waiting for the whole date.
- [ ] Allow retry of only failed or incomplete items.
- [ ] Keep normal live monitoring and historical backfill in separate queues and progress objects.
- [ ] Verify the current BetExplorer result page for `2026-07-17` records 315 unique events and never displays an unrelated queue size.

**Acceptance:** Closing the page or restarting the application does not lose backfill progress, and partial job completion already produces visible archived matches and signals.

### Task 7: Separate the Read API From Heavy Writes

**Files:**
- Modify: `apps/api/src/betexplorer_scraper/api.py`
- Modify: `apps/api/src/betexplorer_scraper/database.py`
- Modify: `apps/api/src/betexplorer_scraper/jobs.py`
- Create: `apps/api/src/betexplorer_scraper/read_models.py`
- Test: `tests/test_api_historical.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Status reads use lightweight materialized counters and a read connection that does not share the writer lock.
- Heavy jobs run through the durable worker and expose heartbeat timestamps.

- [ ] Remove synchronous DOCX parsing and full recompute from async request handlers.
- [ ] Replace the process-wide database `RLock` with a single short-transaction writer and separate read connections.
- [ ] Add incrementally maintained `system_metrics`, `match_summary`, and bookmaker-coverage read models.
- [ ] Make `/api/status` read one compact metrics row plus in-memory worker heartbeat instead of scanning the 1.3 GB database.
- [ ] Push match filtering, date selection, sorting, `LIMIT`, and `OFFSET` into SQL; never call `list_matches()` from `/api/matches-page`.
- [ ] Query one match directly by ID in `match_detail()` and paginate its snapshots and attempts independently.
- [ ] Add database indexes or DuckDB ordering/materialization appropriate to match date, event ID, snapshot match ID, attempt match ID, and job state lookups.
- [ ] Do not run full historical recompute after every capture cycle.
- [ ] Update only signals affected by newly composed or changed match odds.
- [ ] Move full rebuild into an explicit durable maintenance job.
- [ ] Keep startup limited to migrations and worker recovery; defer import/recompute work until the API is accepting requests.
- [ ] Add worker heartbeat, current operation, started time, and last error to `/api/status`.
- [ ] Ensure `/api/status` remains responsive while import, backfill, and full rebuild are running.
- [ ] Add shutdown handling that marks in-progress items resumable rather than failed.
- [ ] Add a performance verification harness that runs concurrent status, selected-match, capture-write, and backfill workloads.
- [ ] Require `/api/status` p95 below 250 ms and selected-match reads p95 below 500 ms during the local backfill workload.

**Acceptance:** The frontend distinguishes `API online, worker busy` from a genuinely stopped API, including during a full database import.

### Task 8: Repair Progress, Polling, and Diagnostic UI

**Files:**
- Modify: `apps/desktop/web/app/page.tsx`
- Modify: `apps/desktop/web/app/signals/page.tsx`
- Modify: `apps/desktop/web/app/match/page.tsx`
- Modify: `apps/desktop/web/app/globals.css`
- Test: `tests/test_dashboard_ui.py`
- Test: `tests/test_match_page_market_tabs.py`

- [ ] Bind archive progress to its archive job ID, not global capture progress.
- [ ] Replace the nine-request 30-second dashboard refresh burst with one compact dashboard-summary request plus lazy section requests.
- [ ] Fetch snapshots, attempts, logs, and bookmaker diagnostics only while their technical sections are expanded.
- [ ] Add a monotonically increasing data revision to summary responses and refresh match lists only when the relevant revision changes.
- [ ] Prevent overlapping polling calls when the previous request has not completed.
- [ ] Prefer server-sent events for job progress; retain low-frequency polling as a reconnect fallback.
- [ ] Display stable `discovered`, `odds complete`, `scores`, `archived`, `failed`, and `remaining` counters.
- [ ] Show the current event and latest failure without resizing the progress layout.
- [ ] Add import validation results and active database batch metadata.
- [ ] Display Bwin and Unibet final capture timestamps separately on the match page.
- [ ] Show `Odds`, `Usable Odds`, and `Played archive` as unambiguous source labels.
- [ ] Keep `Played archive` signals out of the default client signal list.
- [ ] Show `n=1` signals with low-strength messaging rather than hiding them.
- [ ] Add retry controls for failed archive items and a resumable-job state after restart.

**Acceptance:** A user can determine whether data is waiting, captured, matched, rejected, or failed without reading server logs.

### Task 9: Migrate and Repair Existing Installations

**Files:**
- Create: `scripts/repair-ingestion.ps1`
- Create: `apps/api/src/betexplorer_scraper/repair.py`
- Modify: `apps/api/src/betexplorer_scraper/database.py`
- Test: `tests/test_database.py`

- [ ] Create a timestamped DuckDB backup before migration.
- [ ] Inventory historical records by relative-path, absolute-path, and ZIP-derived source sets.
- [ ] Select one supplied client ZIP as the new active batch and reparse it with complete-block semantics.
- [ ] Deactivate legacy `historical_records` data without deleting the backup.
- [ ] Rebuild per-bookmaker final odds from existing raw snapshots.
- [ ] Recreate the played-match archive from composed finals plus captured scores.
- [ ] Recompute client signals from the active `Odds` and `Usable Odds` batch only.
- [ ] Emit before/after counts for files, blocks, outcomes, candidates, signals, stale finals, and repaired finals.
- [ ] Make the repair idempotent so rerunning it does not alter already repaired counts.

**Acceptance:** Existing client data is preserved, duplicate imports are removed, and the repaired installation produces the same result as a clean install with the same ZIP and raw snapshots.

### Task 10: Validate All Eight Client Cases and Release

**Files:**
- Create: `tests/test_upwork_acceptance_cases.py`
- Modify: `README.md`

- [ ] Encode sanitized fixtures for every odds block, outcome list, and expected source from Cases 1-7.
- [ ] Verify Cases 1 and 2 emit One Draw with `n=1` and low strength.
- [ ] Verify Case 3 emits Exact and One Draw separately.
- [ ] Verify Case 4 has one sample after one active import, regardless of repeated ZIP uploads.
- [ ] Verify Case 5 preserves both `3-4` and `2-4` outcomes and does not substitute Played archive.
- [ ] Verify Case 6 emits the DOCX One Draw and does not substitute Played archive.
- [ ] Verify Case 7 selects the latest valid Bwin and Unibet closing observations independently.
- [ ] Verify Case 8 keeps `/api/status` responsive throughout import and recompute.
- [ ] Verify interrupted backfill resumes and already completed events remain visible.
- [ ] Verify dashboard polling does not trigger full-table scans or overlap requests during capture.
- [ ] Verify a 315-match backfill runs concurrently with synthetic kickoff-priority captures without missing their deadlines.
- [ ] Verify status and selected-match latency meet the Task 7 p95 thresholds throughout the soak test.
- [ ] Run the complete Python test suite, frontend build, Windows launcher smoke test, and a multi-hour scheduler/backfill soak test.
- [ ] Document import replacement semantics, source priority, final-odds provenance, backfill recovery, and repair procedure.

**Acceptance:** The release is accepted only when every client case has a deterministic expected output and all provenance can be inspected in the UI.

---

## Recommended Execution Order

1. Tasks 1-3: repair the meaning of the client database and matching results.
2. Task 4: repair final Bwin/Unibet candidate odds.
3. Tasks 5-7: introduce prioritized ingest, durable retrieval, and responsive read models.
4. Task 8: expose the new job, performance, and provenance model in the UI.
5. Tasks 9-10: migrate existing installations and run client acceptance.

Do not run the destructive part of Task 9 until Tasks 1-8 pass their focused verification and a database backup has been validated.
