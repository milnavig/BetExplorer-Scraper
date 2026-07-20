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


def test_database_rehydrates_bookmaker_raw_attributes_for_exports() -> None:
    db_path = Path("data/test_tmp/test_export_raw_attributes.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="attrs123",
            source_url="https://www.betexplorer.com/football/test/attrs123/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=datetime(2026, 4, 28, 20, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="attrs123",
            market="ou",
            captured_at=datetime(2026, 4, 28, 19, 59),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin"],
            bookmaker_odds=[
                BookmakerOdds(
                    "Bwin",
                    "bwin",
                    1.91,
                    1.89,
                    None,
                    raw_row_text="Bwin 2.5 1.91 1.89",
                    raw_attributes={"market_line": "2.5"},
                )
            ],
        ),
    )

    items = db.final_snapshot_items()

    assert items[0][1].bookmaker_odds[0].raw_attributes["market_line"] == "2.5"


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

    assert row["capture_phase"] == "FINALIZED"
    assert row["next_capture_at"] == next_capture_at.isoformat()
    assert row["last_capture_at"] == "2026-04-28T16:31:00"
    assert row["finalized_at"] == finalized_at.isoformat()
    assert schedule["next_capture_at"] == next_capture_at
    assert schedule["finalized_at"] == finalized_at


def test_database_normalizes_stale_finalizing_phase_when_match_is_finalized() -> None:
    db_path = Path("data/test_tmp/test_stale_finalizing_normalized.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    finalized_at = datetime(2026, 4, 28, 16, 40)
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="stalephase123",
            source_url="https://www.betexplorer.com/football/test/stalephase123/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=datetime(2026, 4, 28, 16, 35),
            timing_status=TimingStatus.FINISHED,
        )
    )
    db.update_match_schedule(match_id, "FINALIZING", None, finalized_at)
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="stalephase123",
            market="1x2",
            captured_at=datetime(2026, 4, 28, 16, 50),
            quality_status=SnapshotQuality.PARTIAL,
            required_bookmakers=["Bwin"],
            bookmaker_odds=[BookmakerOdds("Bet365", "bet365", 2.2, 3.1, 2.87)],
        ),
    )

    row = db.list_matches()[0]
    detail = db.match_detail(match_id)
    items = db.final_snapshot_items()

    assert row["capture_phase"] == "FINALIZED"
    assert detail is not None
    assert detail["match"]["capture_phase"] == "FINALIZED"
    assert items[0][0].capture_phase == "FINALIZED"


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


def test_late_incomplete_snapshot_does_not_replace_better_required_bookmaker_final_snapshot() -> None:
    db_path = Path("data/test_tmp/test_final_snapshot_quality_guard.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="guard123",
            source_url="https://www.betexplorer.com/football/test/guard123/",
            league="Guard League",
            home_team="Guard Home",
            away_team="Guard Away",
            kickoff_time=datetime(2026, 7, 8, 20, 0),
            timing_status=TimingStatus.FINISHED,
        )
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="guard123",
            market="1x2",
            captured_at=datetime(2026, 7, 8, 19, 59),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[
                BookmakerOdds("Bwin", "bwin", 2.0, 3.2, 3.4),
                BookmakerOdds("Unibet", "unibet", 1.98, 3.25, 3.5),
            ],
        ),
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="guard123",
            market="1x2",
            captured_at=datetime(2026, 7, 8, 20, 4),
            quality_status=SnapshotQuality.FAILED,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Bet365", "bet365", 2.1, 3.1, 3.2)],
        ),
    )

    row = db.list_matches()[0]
    detail = db.match_detail(match_id)

    assert row["quality_status"] == "COMPLETE"
    assert row["has_bwin"] is True
    assert row["has_unibet"] is True
    assert detail is not None
    assert detail["match"]["quality_status"] == "COMPLETE"
    assert {row["normalized_bookmaker"] for row in detail["bookmaker_odds"]} == {"bwin", "unibet"}
    assert detail["snapshots"][0]["quality_status"] == "FAILED"
    assert detail["snapshots"][0]["is_final"] is False
    assert detail["snapshots"][1]["quality_status"] == "COMPLETE"
    assert detail["snapshots"][1]["is_final"] is True


def test_final_required_odds_are_composed_from_latest_valid_bookmaker_observations(tmp_path: Path) -> None:
    db = Database(tmp_path / "composed_final.duckdb")
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="composed123",
            source_url="https://www.betexplorer.com/football/test/composed123/",
            league="Composed League",
            home_team="Composed Home",
            away_team="Composed Away",
            kickoff_time=datetime(2026, 7, 8, 20, 0),
            timing_status=TimingStatus.RECENTLY_STARTED,
        )
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="composed123",
            market="1x2",
            captured_at=datetime(2026, 7, 8, 19, 30),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[
                BookmakerOdds("Bwin", "bwin", 1.80, 3.70, 3.90),
                BookmakerOdds("Unibet", "unibet", 1.85, 3.65, 3.85),
            ],
        ),
    )
    bwin_snapshot_id = db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="composed123",
            market="1x2",
            captured_at=datetime(2026, 7, 8, 19, 59),
            quality_status=SnapshotQuality.PARTIAL,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Bwin", "bwin", 1.70, 3.80, 3.70)],
        ),
    )
    unibet_snapshot_id = db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="composed123",
            market="1x2",
            captured_at=datetime(2026, 7, 8, 20, 2),
            quality_status=SnapshotQuality.PARTIAL,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Unibet", "unibet", 1.75, 3.75, 3.80)],
        ),
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="composed123",
            market="1x2",
            captured_at=datetime(2026, 7, 8, 20, 5),
            quality_status=SnapshotQuality.FAILED,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Bet365", "bet365", 1.72, 3.72, 3.82)],
        ),
    )

    detail = db.match_detail(match_id)
    assert detail is not None
    assert detail["match"]["quality_status"] == "COMPLETE"
    assert detail["match"]["has_bwin"] is True
    assert detail["match"]["has_unibet"] is True
    final = {row["normalized_bookmaker"]: row for row in detail["final_required_odds"]}
    assert final["bwin"]["snapshot_id"] == bwin_snapshot_id
    assert final["bwin"]["home_odds"] == 1.70
    assert final["unibet"]["snapshot_id"] == unibet_snapshot_id
    assert final["unibet"]["home_odds"] == 1.75


def test_match_summary_quality_uses_primary_1x2_market_not_latest_auxiliary_market() -> None:
    db_path = Path("data/test_tmp/test_match_summary_uses_1x2.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="markets123",
            source_url="https://www.betexplorer.com/football/test/markets123/",
            league="Market League",
            home_team="Market Home",
            away_team="Market Away",
            kickoff_time=datetime(2026, 7, 10, 18, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="markets123",
            market="1x2",
            captured_at=datetime(2026, 7, 10, 16, 0),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[
                BookmakerOdds("Bwin", "bwin", 2.0, 3.2, 3.4),
                BookmakerOdds("Unibet", "unibet", 2.1, 3.1, 3.2),
            ],
        ),
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="markets123",
            market="bts",
            captured_at=datetime(2026, 7, 10, 16, 5),
            quality_status=SnapshotQuality.PARTIAL,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Bwin", "bwin", 1.9, 1.8, None)],
        ),
    )

    row = db.list_matches()[0]
    detail = db.match_detail(match_id)

    assert row["quality_status"] == "COMPLETE"
    assert row["bookmaker_count"] == 2
    assert row["has_bwin"] is True
    assert row["has_unibet"] is True
    assert detail is not None
    assert detail["match"]["quality_status"] == "COMPLETE"


def test_repair_final_snapshots_restores_best_required_bookmaker_snapshot() -> None:
    db_path = Path("data/test_tmp/test_repair_final_snapshots.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="repair123",
            source_url="https://www.betexplorer.com/football/test/repair123/",
            league="Repair League",
            home_team="Repair Home",
            away_team="Repair Away",
            kickoff_time=datetime(2026, 7, 10, 18, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    good_id = db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="repair123",
            market="1x2",
            captured_at=datetime(2026, 7, 10, 16, 0),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[
                BookmakerOdds("Bwin", "bwin", 2.0, 3.2, 3.4),
                BookmakerOdds("Unibet", "unibet", 2.1, 3.1, 3.2),
            ],
        ),
    )
    bad_id = db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="repair123",
            market="1x2",
            captured_at=datetime(2026, 7, 10, 16, 5),
            quality_status=SnapshotQuality.FAILED,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[BookmakerOdds("Bet365", "bet365", 2.2, 3.0, 3.1)],
        ),
    )
    db.connection.execute("UPDATE odds_snapshots SET is_final = FALSE WHERE id = ?", [good_id])
    db.connection.execute("UPDATE odds_snapshots SET is_final = TRUE WHERE id = ?", [bad_id])

    result = db.repair_final_snapshots()
    detail = db.match_detail(match_id)

    assert result["groups_repaired"] == 1
    assert detail is not None
    assert detail["match"]["quality_status"] == "COMPLETE"
    final_snapshots = [snapshot for snapshot in detail["snapshots"] if snapshot["is_final"]]
    assert len(final_snapshots) == 1
    assert final_snapshots[0]["quality_status"] == "COMPLETE"


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


def test_database_exposes_historical_import_status_before_import() -> None:
    db_path = Path("data/test_tmp/test_historical_status.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)

    status = db.historical_import_status()

    assert status["records"] == 0
    assert status["files"] == 0
    assert status["warnings"] == 0
    assert status["datasets"] == []


def test_archive_retry_resets_only_incomplete_items(tmp_path: Path) -> None:
    db = Database(tmp_path / "archive_retry.duckdb")
    job = db.create_archive_job(datetime(2026, 7, 17).date())
    job_id = str(job["id"])
    db.set_archive_job_items(
        job_id,
        [
            {"event_id": "complete", "source_url": "https://example.test/complete"},
            {"event_id": "failed", "source_url": "https://example.test/failed"},
        ],
    )
    db.update_archive_job_item(
        job_id,
        "complete",
        state="archived",
        odds_status="complete",
        score_status="complete",
        archive_status="complete",
    )
    db.update_archive_job_item(
        job_id,
        "failed",
        state="incomplete",
        odds_status="complete",
        score_status="failed",
        archive_status="pending",
        error_message="Final score missing",
    )
    db.finish_archive_job(job_id)

    retried = db.retry_archive_job(job_id)
    items = {item["event_id"]: item for item in db.list_archive_job_items(job_id)}

    assert retried is not None
    assert retried["status"] == "pending"
    assert items["complete"]["state"] == "archived"
    assert items["complete"]["archive_status"] == "complete"
    assert items["failed"]["state"] == "discovered"
    assert items["failed"]["odds_status"] == "complete"
    assert items["failed"]["score_status"] == "pending"
    assert items["failed"]["error_message"] is None


def test_maintenance_job_persists_progress_and_result(tmp_path: Path) -> None:
    db = Database(tmp_path / "maintenance_job.duckdb")
    job = db.create_maintenance_job("recompute_signals", {"archive_played": True})
    job_id = str(job["id"])

    db.update_maintenance_job(job_id, status="running", phase="recomputing_signals", current=1, total=2)
    db.update_maintenance_job(
        job_id,
        status="completed",
        phase="complete",
        current=2,
        total=2,
        result={"signals": 7},
    )
    saved = db.get_maintenance_job(job_id)

    assert saved is not None
    assert saved["status"] == "completed"
    assert saved["payload"] == {"archive_played": True}
    assert saved["result"] == {"signals": 7}
    assert db.resumable_maintenance_jobs() == []
