from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import datetime
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from betexplorer_scraper import api
from betexplorer_scraper.database import Database
from betexplorer_scraper.historical import HistoricalDocxImporter
from betexplorer_scraper.models import BookmakerOdds, DiscoveredMatch, OddsSnapshot, SnapshotQuality, TimingStatus


class _FakeCaptureService:
    async def run_once(self) -> dict[str, int]:
        return {"discovered": 0, "captured": 1, "failed": 0, "finalized": 0, "results_captured": 0}


class _FakeHistoricalAutoRefresh:
    def __init__(self) -> None:
        self.reasons: list[str] = []

    def refresh(self, reason: str) -> dict[str, int]:
        self.reasons.append(reason)
        return {
            "files_seen": 1,
            "files_imported": 0,
            "records_imported": 0,
            "warnings": 0,
            "recompute_matches_evaluated": 1,
            "recompute_signals": 2,
            "archived": 0,
        }


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
    assert signals.json()[0]["similarity_score"] == 100.0
    assert signals.json()[0]["match_explanation"] == "Exact 1X2 odds"
    assert signals.json()[0]["signal_rank"] == 1
    assert signals.json()[0]["matched_odds_home"] == 2.0
    assert signals.json()[0]["odds_distance_home"] == 0.0
    assert match_signals.status_code == 200
    assert match_signals.json()[0]["match_id"] == match_id


def test_historical_import_zip_extracts_docx_database_and_recomputes(monkeypatch, tmp_path: Path) -> None:
    db = Database(tmp_path / "zip_import.duckdb")
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="zip123",
            source_url="https://www.betexplorer.com/football/test/zip123/",
            league="ZIP League",
            home_team="Zip Home",
            away_team="Zip Away",
            kickoff_time=datetime(2026, 5, 14, 20, 0),
            timing_status=TimingStatus.UPCOMING_SOON,
        )
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="zip123",
            market="1x2",
            captured_at=datetime(2026, 5, 14, 19, 55),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin"],
            bookmaker_odds=[BookmakerOdds("Bwin", "bwin", 2.0, 3.4, 3.0)],
        ),
    )
    monkeypatch.setattr(api, "database", db)
    monkeypatch.setattr(api, "historical_importer", HistoricalDocxImporter(db))
    monkeypatch.setattr(api.settings, "historical_database_root", tmp_path / "SAMPLE_DATABASE", raising=False)
    client = TestClient(api.app)
    document = Document()
    table = document.add_table(rows=2, cols=5)
    table.rows[0].cells[0].text = "2.00"
    table.rows[0].cells[1].text = "3.40"
    table.rows[0].cells[2].text = "3.00"
    table.rows[1].cells[0].text = "2.00"
    table.rows[1].cells[1].text = "3.40"
    table.rows[1].cells[2].text = "3.00"
    table.rows[1].cells[3].text = "1-0"
    docx_buffer = io.BytesIO()
    document.save(docx_buffer)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("SAMPLE_DATABASE/Odds/2.00/ODDS.docx", docx_buffer.getvalue())

    response = client.post(
        "/api/historical/import-zip",
        content=zip_buffer.getvalue(),
        headers={"content-type": "application/zip", "x-filename": "sample-db.zip"},
    )
    signals = client.get("/api/signals")

    assert response.status_code == 200
    assert response.json()["files_seen"] == 1
    assert response.json()["records_imported"] == 1
    assert response.json()["recompute_signals"] == 1
    assert Path(response.json()["import_root"]).exists()
    assert signals.json()[0]["historical_scores"] == ["1-0"]


def test_matches_page_api_returns_chunked_filtered_results(monkeypatch, tmp_path: Path) -> None:
    db = Database(tmp_path / "matches_page.duckdb")
    for index in range(5):
        db.upsert_match(
            DiscoveredMatch(
                event_id=f"page{index}",
                source_url=f"https://www.betexplorer.com/football/test/page{index}/",
                league="Paged League",
                home_team=f"Home {index}",
                away_team="Away",
                kickoff_time=datetime(2026, 5, 14, 18 + index, 0),
                timing_status=TimingStatus.UPCOMING_SOON,
            )
        )
    monkeypatch.setattr(api, "database", db)
    client = TestClient(api.app)

    first_page = client.get("/api/matches-page", params={"limit": 2, "offset": 0, "q": "Home"})
    second_page = client.get("/api/matches-page", params={"limit": 2, "offset": 2, "q": "Home"})

    assert first_page.status_code == 200
    assert first_page.json()["total"] == 5
    assert first_page.json()["limit"] == 2
    assert len(first_page.json()["items"]) == 2
    assert second_page.json()["offset"] == 2
    assert len(second_page.json()["items"]) == 2


def test_capture_run_once_auto_refreshes_historical_signals_after_capture(monkeypatch) -> None:
    fake_refresh = _FakeHistoricalAutoRefresh()
    monkeypatch.setattr(api, "service", _FakeCaptureService())
    monkeypatch.setattr(api, "historical_auto_refresh", fake_refresh)
    monkeypatch.setattr(api.settings, "historical_auto_recompute", True, raising=False)

    result = asyncio.run(api.capture_run_once())

    assert fake_refresh.reasons == ["capture_run_once"]
    assert result["captured"] == 1
    assert result["historical_recompute_signals"] == 2


def test_played_archive_export_endpoint_writes_csv(monkeypatch, tmp_path: Path) -> None:
    db = Database(tmp_path / "archive_export.duckdb")
    match_id = db.upsert_match(
        DiscoveredMatch(
            event_id="archive123",
            source_url="https://www.betexplorer.com/football/test/archive123/",
            league="Archive League",
            home_team="Archive Home",
            away_team="Archive Away",
            kickoff_time=datetime(2026, 5, 14, 20, 0),
            timing_status=TimingStatus.FINISHED,
        )
    )
    db.save_snapshot(
        match_id,
        OddsSnapshot(
            event_id="archive123",
            market="1x2",
            captured_at=datetime(2026, 5, 14, 19, 59),
            quality_status=SnapshotQuality.COMPLETE,
            required_bookmakers=["Bwin", "Unibet"],
            bookmaker_odds=[
                BookmakerOdds("Bwin", "bwin", 2.1, 3.2, 3.4),
                BookmakerOdds("Unibet", "unibet", 2.0, 3.3, 3.5),
            ],
        ),
    )
    db.mark_result_captured(match_id, "2:1", datetime(2026, 5, 14, 22, 0))
    monkeypatch.setattr(api, "database", db)
    monkeypatch.setattr(api.settings, "export_dir", tmp_path / "exports")
    client = TestClient(api.app)

    response = client.post("/api/exports/played-archive", json={"format": "csv"})
    exports = client.get("/api/exports")

    assert response.status_code == 200
    filename = response.json()["filename"]
    assert filename.startswith("played_match_archive_")
    assert filename.endswith(".csv")
    assert (tmp_path / "exports" / filename).read_text(encoding="utf-8").splitlines()[0].startswith("event_id,")
    assert any(item["filename"] == filename for item in exports.json())
