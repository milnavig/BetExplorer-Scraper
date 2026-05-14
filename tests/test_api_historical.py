from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from betexplorer_scraper import api
from betexplorer_scraper.database import Database
from betexplorer_scraper.models import BookmakerOdds, DiscoveredMatch, OddsSnapshot, SnapshotQuality, TimingStatus


def test_historical_signal_api_exposes_status_recompute_and_match_signals(monkeypatch, tmp_path: Path) -> None:
    db = Database(tmp_path / "api_signals.duckdb")
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="api123",
            source_url="https://www.betexplorer.com/football/test/api123/",
            league="API League",
            home_team="Home",
            away_team="Away",
            kickoff_time=datetime(2026, 5, 14, 20, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="api123",
            market="1x2",
            captured_at=datetime(2026, 5, 14, 19, 55),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin"],
            bookmaker_odds=[BookmakerOdds("Bwin", "bwin", 2.0, 3.4, 3.0)],
        ),
    )
    db.replace_historical_records(
        "api.docx",
        [
            {
                "dataset": "Odds",
                "source_file": "api.docx",
                "source_home_bucket": 3.0,
                "source_away_file": 3.0,
                "query_home_odds": 2.0,
                "query_draw_odds": 3.4,
                "query_away_odds": 3.0,
                "historical_home_odds": 2.0,
                "historical_draw_odds": 3.4,
                "historical_away_odds": 3.0,
                "full_time_score": "1-0",
                "half_time_score": "0-0",
                "parse_status": "parsed",
                "parse_warning": None,
            }
        ],
    )
    monkeypatch.setattr(api, "database", db)
    client = TestClient(api.app)

    status = client.get("/api/historical/import-status")
    recompute = client.post("/api/signals/recompute", json={"archive_played": False})
    signals = client.get("/api/signals")
    match_signals = client.get(f"/api/signals/{match_id}")

    assert status.status_code == 200
    assert status.json()["records"] == 1
    assert recompute.status_code == 200
    assert recompute.json()["signals"] == 1
    assert signals.status_code == 200
    assert signals.json()[0]["signal_type"] == "exact_odds"
    assert signals.json()[0]["historical_scores"] == ["1-0"]
    assert match_signals.status_code == 200
    assert match_signals.json()[0]["match_id"] == match_id
