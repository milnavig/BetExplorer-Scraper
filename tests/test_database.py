from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from betexplorer_scraper.database import Database
from betexplorer_scraper.exporter import final_odds_rows
from betexplorer_scraper.models import BookmakerOdds, DiscoveredMatch, OddsSnapshot, SnapshotQuality, TimingStatus


def test_database_persists_match_snapshot_and_rehydrates_final_export_items() -> None:
    db_path = Path("data/test_tmp/test.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    match = DiscoveredMatch(
        event_id="abc12345",
        source_url="https://www.betexplorer.com/football/test/abc12345/",
        league="Test League",
        home_team="Home",
        away_team="Away",
        kickoff_time=datetime(2026, 4, 28, 20, 0),
        timing_status=TimingStatus.UPCOMING_SOON,
    )
    match_id = db.upsert_match(match)
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="abc12345",
            market="1x2",
            captured_at=datetime(2026, 4, 28, 16, 0),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[
                BookmakerOdds("bwin", "bwin", 2.2, 3.1, 2.87),
                BookmakerOdds("Unibet", "unibet", 2.55, 3.1, 2.38),
            ],
        ),
    )

    status = db.status()
    items = db.final_snapshot_items()

    assert status["matches"] == 1
    assert status["complete_snapshots"] == 1
    assert len(items) == 1
    assert items[0][0].timing_status == TimingStatus.UPCOMING_SOON
    assert {row.normalized_bookmaker for row in items[0][1].bookmaker_odds} == {"bwin", "unibet"}
    assert final_odds_rows(items)[0]["quality_status"] == "COMPLETE"


def test_database_stores_capture_schedule_fields() -> None:
    db_path = Path("data/test_tmp/test_scheduler.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    next_capture_at = datetime(2026, 4, 28, 16, 30)
    finalized_at = datetime(2026, 4, 28, 16, 40)
    match = DiscoveredMatch(
        event_id="sched123",
        source_url="https://www.betexplorer.com/football/test/sched123/",
        league="Test League",
        home_team="Home",
        away_team="Away",
        kickoff_time=datetime(2026, 4, 28, 16, 35),
        timing_status=TimingStatus.UPCOMING_SOON,
    )
    match_id = db.upsert_match(match)

    db.update_match_schedule(match_id, "FINALIZING", next_capture_at, finalized_at)
    db.mark_match_captured(match_id, datetime(2026, 4, 28, 16, 31), next_capture_at, "FINALIZING", finalized_at)
    row = db.list_matches()[0]
    schedule = db.get_match_schedule(match_id)

    assert row["capture_phase"] == "FINALIZING"
    assert row["next_capture_at"] == next_capture_at.isoformat()
    assert row["last_capture_at"] == "2026-04-28T16:31:00"
    assert row["finalized_at"] == finalized_at.isoformat()
    assert schedule["next_capture_at"] == next_capture_at
    assert schedule["finalized_at"] == finalized_at


def test_database_lists_captured_matches_first_and_match_detail_uses_final_snapshot_only() -> None:
    db_path = Path("data/test_tmp/test_final_detail.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    empty_id = db.upsert_match(
        DiscoveredMatch(
            event_id="empty123",
            source_url="https://www.betexplorer.com/football/test/empty123/",
            league="Test League",
            home_team="Empty",
            away_team="Away",
            kickoff_time=datetime(2026, 4, 28, 15, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    captured_id = db.upsert_match(
        DiscoveredMatch(
            event_id="captured123",
            source_url="https://www.betexplorer.com/football/test/captured123/",
            league="Test League",
            home_team="Captured",
            away_team="Away",
            kickoff_time=datetime(2026, 4, 28, 16, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    assert empty_id
    db.save_snapshot(
        captured_id,
        OddsSnapshot(
            event_id="captured123",
            market="1x2",
            captured_at=datetime(2026, 4, 28, 15, 30),
            quality_status=SnapshotQuality.PARTIAL,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Bwin", "bwin", 2.2, 3.1, 2.87)],
        ),
    )
    db.save_snapshot(
        captured_id,
        OddsSnapshot(
            event_id="captured123",
            market="1x2",
            captured_at=datetime(2026, 4, 28, 15, 40),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[
                BookmakerOdds("Bwin", "bwin", 2.25, 3.2, 2.8),
                BookmakerOdds("Unibet", "unibet", 2.3, 3.1, 2.75),
            ],
        ),
    )
    db.save_attempt(
        captured_id,
        "captured123",
        "https://www.betexplorer.com/football/test/captured123/",
        1,
        "COMPLETE",
        None,
        {"Bwin": True, "Unibet": True},
        datetime(2026, 4, 28, 15, 39),
        datetime(2026, 4, 28, 15, 40),
    )

    rows = db.list_matches()
    detail = db.match_detail(captured_id)
    attempts = db.list_attempts()
    coverage = db.bookmaker_coverage()

    assert rows[0]["id"] == captured_id
    assert rows[0]["bookmaker_count"] == 2
    assert rows[0]["has_bwin"] is True
    assert rows[0]["has_unibet"] is True
    assert rows[0]["attempt_count"] == 1
    assert detail is not None
    assert detail["match"]["quality_status"] == "COMPLETE"
    assert detail["match"]["bookmaker_count"] == 2
    assert detail["match"]["has_bwin"] is True
    assert detail["match"]["has_unibet"] is True
    assert len(detail["snapshots"]) == 2
    assert detail["snapshots"][0]["bookmaker_count"] == 2
    assert detail["snapshots"][1]["bookmaker_count"] == 1
    assert len(detail["bookmaker_odds"]) == 2
    assert len(detail["attempts"]) == 1
    assert {row["normalized_bookmaker"] for row in detail["bookmaker_odds"]} == {"bwin", "unibet"}
    assert attempts[0]["home_team"] == "Captured"
    assert {row["normalized_bookmaker"] for row in coverage} == {"bwin", "unibet"}


def test_database_status_reports_final_snapshots_separately_from_attempts() -> None:
    db_path = Path("data/test_tmp/test_status_final.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    captured_id = db.upsert_match(
        DiscoveredMatch(
            event_id="status123",
            source_url="https://www.betexplorer.com/football/test/status123/",
            league="Test League",
            home_team="Captured",
            away_team="Away",
            kickoff_time=datetime(2026, 4, 28, 16, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    missed_id = db.upsert_match(
        DiscoveredMatch(
            event_id="missed123",
            source_url="https://www.betexplorer.com/football/test/missed123/",
            league="Test League",
            home_team="Missed",
            away_team="Away",
            kickoff_time=datetime(2026, 4, 28, 15, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    db.update_match_schedule(missed_id, "FINALIZED", None, datetime(2026, 4, 28, 16, 0))
    db.save_snapshot(
        captured_id,
        OddsSnapshot(
            event_id="status123",
            market="1x2",
            captured_at=datetime(2026, 4, 28, 15, 30),
            quality_status=SnapshotQuality.PARTIAL,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Bwin", "bwin", 2.2, 3.1, 2.87)],
        ),
    )
    db.save_snapshot(
        captured_id,
        OddsSnapshot(
            event_id="status123",
            market="1x2",
            captured_at=datetime(2026, 4, 28, 15, 40),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[
                BookmakerOdds("Bwin", "bwin", 2.25, 3.2, 2.8),
                BookmakerOdds("Unibet", "unibet", 2.3, 3.1, 2.75),
            ],
        ),
    )
    db.log("info", "capture", "run_once_completed", details={"discovered": 2})

    status = db.status()

    assert status["snapshots"] == 1
    assert status["snapshot_attempts"] == 2
    assert status["bookmaker_rows"] == 2
    assert status["bookmaker_row_attempts"] == 3
    assert status["complete_snapshots"] == 1
    assert status["partial_snapshots"] == 0
    assert status["captured_matches"] == 1
    assert status["missed_finalized_matches"] == 1
    assert status["capture_missed_matches"] == 0
    assert status["skipped_out_of_window_matches"] == 1
    assert status["last_run"] is not None
    assert "next_capture" in status


def test_database_status_ignores_prior_day_stale_next_capture() -> None:
    db_path = Path("data/test_tmp/test_status_next_capture.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    now = datetime.now()
    stale_id = db.upsert_match(
        DiscoveredMatch(
            event_id="stale123",
            source_url="https://www.betexplorer.com/football/test/stale123/",
            league="Test League",
            home_team="Stale",
            away_team="Away",
            kickoff_time=now - timedelta(days=1),
            timing_status=TimingStatus.UNKNOWN,
        )
    )
    fresh_id = db.upsert_match(
        DiscoveredMatch(
            event_id="fresh123",
            source_url="https://www.betexplorer.com/football/test/fresh123/",
            league="Test League",
            home_team="Fresh",
            away_team="Away",
            kickoff_time=now + timedelta(hours=2),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    fresh_next_capture = now + timedelta(hours=1)
    db.update_match_schedule(stale_id, "MONITORING", now - timedelta(days=1))
    db.update_match_schedule(fresh_id, "WAITING", fresh_next_capture)

    status = db.status()

    assert status["next_capture"] == fresh_next_capture.isoformat()


def test_database_migrates_old_matches_table_without_positional_insert_breakage() -> None:
    db_path = Path("data/test_tmp/test_old_schema.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    old = Database(db_path)
    old.connection.execute("DROP TABLE matches")
    old.connection.execute(
        """
        CREATE TABLE matches (
            id VARCHAR PRIMARY KEY,
            betexplorer_match_id VARCHAR UNIQUE,
            sport VARCHAR,
            league VARCHAR,
            home_team VARCHAR,
            away_team VARCHAR,
            kickoff_time TIMESTAMP,
            status VARCHAR,
            timing_status VARCHAR,
            source_url VARCHAR,
            live_score VARCHAR,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """
    )
    old.connection.close()

    db = Database(db_path)
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="old12345",
            source_url="https://www.betexplorer.com/football/test/old12345/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=datetime(2026, 4, 28, 16, 35),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )

    row = db.list_matches()[0]
    assert match_id
    assert row["capture_phase"] == "DISCOVERED"


def test_database_read_methods_are_safe_for_fastapi_threadpool_concurrency() -> None:
    db_path = Path("data/test_tmp/test_threadpool.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="thread123",
            source_url="https://www.betexplorer.com/football/test/thread123/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=datetime(2026, 4, 28, 16, 35),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="thread123",
            market="1x2",
            captured_at=datetime(2026, 4, 28, 16, 0),
            quality_status=SnapshotQuality.PARTIAL,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Bwin", "bwin", 2.2, 3.1, 2.87)],
        ),
    )
    db.log("INFO", "test", "seeded")

    def read_endpoint_like_method(index: int) -> object:
        if index % 4 == 0:
            return db.status()
        if index % 4 == 1:
            return db.list_matches()
        if index % 4 == 2:
            return db.list_snapshots()
        return db.list_logs()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(read_endpoint_like_method, range(300)))

    assert len(results) == 300
    assert all(result is not None for result in results)
