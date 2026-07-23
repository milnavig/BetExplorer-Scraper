# DOCX Import Resilience Implementation Plan

**Goal:** Prevent Microsoft Word lock files and isolated corrupt DOCX files from aborting a historical database import.

**Architecture:** Reject `~$*.docx` entries at ZIP extraction and ignore them again during filesystem discovery. Parse each remaining DOCX independently so one unreadable package becomes a warning and skipped-file count while valid files still form the active import batch.

**Tech Stack:** FastAPI, Python `zipfile`, `python-docx`, DuckDB, pytest.

## Constraints

- Do not use TDD; add regression coverage after implementing the behavior.
- Preserve existing API fields and add `files_skipped` without changing matching rules.
- Never activate an empty replacement batch when every candidate file is invalid.

## Task 1: Filter Word lock files

**Files:**
- Modify: `apps/api/src/betexplorer_scraper/api.py`
- Modify: `apps/api/src/betexplorer_scraper/historical.py`

- [ ] Add a shared filename predicate for names beginning with `~$`.
- [ ] Skip these entries before ZIP extraction.
- [ ] Skip these paths during direct folder discovery as defense in depth.

## Task 2: Isolate corrupt DOCX packages

**Files:**
- Modify: `apps/api/src/betexplorer_scraper/historical.py`

- [ ] Catch parser exceptions per discovered DOCX.
- [ ] Count unreadable documents in `files_skipped`.
- [ ] Return their errors through the existing warning mechanism.
- [ ] Activate the batch when at least one valid DOCX was parsed.
- [ ] Keep the current active batch unchanged when no valid DOCX remains.

## Task 3: Regression coverage and verification

**Files:**
- Modify: `tests/test_api_historical.py`
- Modify: `tests/test_historical_signals.py`

- [ ] Verify ZIP extraction ignores a `~$` entry.
- [ ] Verify folder import ignores Word lock files.
- [ ] Verify one malformed DOCX does not block valid historical records.
- [ ] Run focused import tests.
- [ ] Run the complete backend test suite.
