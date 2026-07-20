from __future__ import annotations

import json
import gzip
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from betexplorer_scraper.capture import CaptureService
from betexplorer_scraper.config import Settings
from betexplorer_scraper.database import Database
from betexplorer_scraper.models import DiscoveredMatch, TimingStatus
from betexplorer_scraper.transport import BetExplorerTransport, HttpBetExplorerTransport, RawResponse


def test_raw_payloads_are_gzip_compressed(tmp_path: Path) -> None:
    db_path = tmp_path / "raw_payload.duckdb"
    settings = _settings(db_path)
    settings.raw_snapshot_dir = tmp_path / "raw"
    service = CaptureService(settings, Database(db_path), FakeTransport(datetime(2026, 7, 18, 20, 0)))

    path = service._save_raw_payload("raw123", 1, "1x2", '{"odds":"payload"}')

    assert path.suffixes[-2:] == [".json", ".gz"]
    with gzip.open(path, "rt", encoding="utf-8") as source:
        assert source.read() == '{"odds":"payload"}'


class FakeTransport(BetExplorerTransport):
    def __init__(self, kickoff: datetime) -> None:
        self.kickoff = kickoff
        self.match_odds_calls = 0

    async def fetch_homepage(self) -> RawResponse:
        return self._schedule_response("https://www.betexplorer.com/")

    async def fetch_football_date(self, target_date: date) -> RawResponse:
        return self._schedule_response(
            f"https://www.betexplorer.com/football/?year={target_date.year}&month={target_date.month:02d}&day={target_date.day:02d}"
        )

    def _schedule_response(self, url: str) -> RawResponse:
        dt = f"{self.kickoff.day},{self.kickoff.month},{self.kickoff.year},{self.kickoff.hour},{self.kickoff.minute:02d}"
        html = f"""
        <p class="table-main__truncate table-main__leaguesNames leaguesNames">Test League</p>
        <li data-event-id="abc12345">
          <ul data-dt="{dt}">
            <a href="/football/test-league/home-away/abc12345/">
              <span class="table-main__participantHome">Home</span>
              <span class="table-main__participantAway">Away</span>
            </a>
          </ul>
        </li>
        """
        return RawResponse(url, html, 200)

    async def fetch_live_results(self) -> RawResponse:
        return RawResponse("https://www.betexplorer.com/gres/ajax/live-results.php?lang=en", '{"events":{}}', 200)

    async def fetch_match_page(self, match_url: str) -> RawResponse:
        return RawResponse(match_url, '<a data-tab="1x2">1X2</a><a data-tab="bts">BTS</a>', 200)

    async def fetch_match_odds(self, event_id: str, referer_url: str, market: str = "1x2") -> RawResponse:
        self.match_odds_calls += 1
        html = """
        <table><tbody>
          <tr data-bid="2" data-bookie-id="261">
            <td><a class="in-bookmaker-logo-link">bwin</a></td>
            <td data-odd="2.20" data-bookie="bwin"></td>
            <td data-odd="3.10" data-bookie="bwin"></td>
            <td data-odd="2.87" data-bookie="bwin"></td>
          </tr>
          <tr data-bid="5" data-bookie-id="43">
            <td><a class="in-bookmaker-logo-link">Unibet</a></td>
            <td data-odd="2.55" data-bookie="Unibet"></td>
            <td data-odd="3.10" data-bookie="Unibet"></td>
            <td data-odd="2.38" data-bookie="Unibet"></td>
          </tr>
        </tbody></table>
        """
        return RawResponse("https://www.betexplorer.com/match-odds/abc12345/0/1x2/bestOdds/?lang=en", json.dumps({"odds": html}), 200)


class NoDiscoveryTransport(FakeTransport):
    async def fetch_homepage(self) -> RawResponse:
        return RawResponse("https://www.betexplorer.com/", "<html></html>", 200)

    async def fetch_football_date(self, target_date: date) -> RawResponse:
        return RawResponse("https://www.betexplorer.com/football/", "<html></html>", 200)


class RediscoveryTransport(FakeTransport):
    pass


class PartialOddsTransport(FakeTransport):
    async def fetch_match_odds(self, event_id: str, referer_url: str, market: str = "1x2") -> RawResponse:
        self.match_odds_calls += 1
        html = """
        <table><tbody>
          <tr data-bid="8" data-bookie-id="99">
            <td><a class="in-bookmaker-logo-link">Betway</a></td>
            <td data-odd="2.40" data-bookie="Betway"></td>
            <td data-odd="3.20" data-bookie="Betway"></td>
            <td data-odd="2.70" data-bookie="Betway"></td>
          </tr>
        </tbody></table>
        """
        return RawResponse("https://www.betexplorer.com/match-odds/abc12345/0/1x2/bestOdds/?lang=en", json.dumps({"odds": html}), 200)


class PartialThenCompleteOddsTransport(FakeTransport):
    async def fetch_match_odds(self, event_id: str, referer_url: str, market: str = "1x2") -> RawResponse:
        self.match_odds_calls += 1
        if self.match_odds_calls == 1:
            html = """
            <table><tbody>
              <tr data-bid="2" data-bookie-id="261">
                <td><a class="in-bookmaker-logo-link">bwin</a></td>
                <td data-odd="2.20" data-bookie="bwin"></td>
                <td data-odd="3.10" data-bookie="bwin"></td>
                <td data-odd="2.87" data-bookie="bwin"></td>
              </tr>
            </tbody></table>
            """
        else:
            html = """
            <table><tbody>
              <tr data-bid="2" data-bookie-id="261">
                <td><a class="in-bookmaker-logo-link">bwin</a></td>
                <td data-odd="2.20" data-bookie="bwin"></td>
                <td data-odd="3.10" data-bookie="bwin"></td>
                <td data-odd="2.87" data-bookie="bwin"></td>
              </tr>
              <tr data-bid="5" data-bookie-id="43">
                <td><a class="in-bookmaker-logo-link">Unibet</a></td>
                <td data-odd="2.55" data-bookie="Unibet"></td>
                <td data-odd="3.10" data-bookie="Unibet"></td>
                <td data-odd="2.38" data-bookie="Unibet"></td>
              </tr>
            </tbody></table>
            """
        return RawResponse("https://www.betexplorer.com/match-odds/abc12345/0/1x2/bestOdds/?lang=en", json.dumps({"odds": html}), 200)


class FinishedResultTransport(FakeTransport):
    async def fetch_homepage(self) -> RawResponse:
        return RawResponse("https://www.betexplorer.com/", "<html></html>", 200)

    async def fetch_football_date(self, target_date: date) -> RawResponse:
        dt = f"{self.kickoff.day},{self.kickoff.month},{self.kickoff.year},{self.kickoff.hour},{self.kickoff.minute:02d}"
        html = f"""
        <table>
          <tr class="js-tournament">
            <th colspan="2"><a class="table-main__tournament" href="/football/test/">Test Country: Test League</a></th>
          </tr>
          <tr data-dt="{dt}">
            <td>
              <span class="table-main__time">{self.kickoff.hour:02d}:{self.kickoff.minute:02d}</span>
              <a href="/football/test-league/home-away/abc12345/">Home - Away</a>
              <span class="table-main__result">2:1</span>
            </td>
          </tr>
        </table>
        """
        return RawResponse("https://www.betexplorer.com/football/", html, 200)


class NoOddsArchiveTransport(FinishedResultTransport):
    async def fetch_match_odds(self, event_id: str, referer_url: str, market: str = "1x2") -> RawResponse:
        self.match_odds_calls += 1
        html = "<div>There isn't any bookmaker offering odds for this match.</div>"
        return RawResponse(
            "https://www.betexplorer.com/match-odds/abc12345/0/1x2/bestOdds/?lang=en",
            json.dumps({"odds": html}),
            200,
        )


class MatchPageResultTransport(NoDiscoveryTransport):
    async def fetch_match_page(self, match_url: str) -> RawResponse:
        html = """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"SportsEvent","eventStatus":"Finished"}
        </script>
        <div class="list-details">
          <p class="list-details__item__score">5:2</p>
        </div>
        """
        return RawResponse(match_url, html, 200)


class ArchivedScoreWithoutFinishedMarkerTransport(FinishedResultTransport):
    async def fetch_football_date(self, target_date: date) -> RawResponse:
        dt = f"{self.kickoff.day},{self.kickoff.month},{self.kickoff.year},{self.kickoff.hour},{self.kickoff.minute:02d}"
        html = f"""
        <table>
          <tr class="js-tournament">
            <th colspan="2"><a class="table-main__tournament" href="/football/test/">Test Country: Test League</a></th>
          </tr>
          <tr data-dt="{dt}">
            <td>
              <span class="table-main__time">{self.kickoff.hour:02d}:{self.kickoff.minute:02d}</span>
              <a href="/football/test-league/home-away/abc12345/">Home - Away</a>
            </td>
          </tr>
        </table>
        """
        return RawResponse("https://www.betexplorer.com/football/", html, 200)

    async def fetch_match_page(self, match_url: str) -> RawResponse:
        html = """
        <div class="list-details">
          <p class="list-details__item__score">2:1</p>
        </div>
        """
        return RawResponse(match_url, html, 200)


class MixedDateArchiveTransport(FinishedResultTransport):
    async def fetch_football_date(self, target_date: date) -> RawResponse:
        def row(event_id: str, day: int, home: str, score: str) -> str:
            dt = f"{day},5,2026,20,00"
            return f"""
            <tr data-dt="{dt}">
              <td>
                <span class="table-main__time">20:00</span>
                <a href="/football/test-league/{home.lower()}-away/{event_id}/">{home} - Away</a>
                <span class="table-main__result">{score}</span>
              </td>
            </tr>
            """

        html = f"""
        <table>
          <tr class="js-tournament">
            <th colspan="2"><a class="table-main__tournament" href="/football/test/">Test Country: Test League</a></th>
          </tr>
          {row("prev1234", 13, "Previous", "1:0")}
          {row("abc12345", 14, "Home", "2:1")}
          {row("next1234", 15, "Next", "3:0")}
        </table>
        """
        return RawResponse("https://www.betexplorer.com/football/results/", html, 200)


def _settings(db_path: Path) -> Settings:
    return Settings(
        database_path=db_path,
        raw_snapshot_dir=db_path.parent / "raw",
        export_dir=db_path.parent / "exports",
        log_dir=db_path.parent / "logs",
        upcoming_window_minutes=30,
        recently_started_window_minutes=10,
        max_match_age_after_kickoff_minutes=10,
        monitoring_capture_poll_interval_seconds=60,
        final_capture_poll_interval_seconds=10,
        final_capture_fast_window_minutes=5,
        discovery_poll_interval_seconds=60,
        max_retries_per_match=1,
        capture_market="1x2",
        result_capture_lookback_hours=120,
        result_backfill_batch_size=50,
    )


def _all_market_settings(db_path: Path) -> Settings:
    settings = _settings(db_path)
    return settings.model_copy(update={"capture_market": "all"})


@pytest.mark.asyncio
async def test_run_once_discovers_far_future_match_without_fetching_odds() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    db_path = Path("data/test_tmp/capture_far.duckdb")
    if db_path.exists():
        db_path.unlink()
    transport = FakeTransport(now + timedelta(hours=7))
    service = CaptureService(_settings(db_path), Database(db_path), transport)

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert result == {
        "discovered": 1,
        "due": 0,
        "captured": 0,
        "failed": 0,
        "skipped": 1,
        "finalized": 0,
        "waiting": 1,
        "results_captured": 0,
        "results_checked": 0,
    }
    assert transport.match_odds_calls == 0
    assert row["capture_phase"] == "WAITING"
    assert row["next_capture_at"] == (now + timedelta(hours=7) - timedelta(hours=6)).isoformat()


@pytest.mark.asyncio
async def test_run_once_fetches_odds_when_match_is_due() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    db_path = Path("data/test_tmp/capture_due.duckdb")
    if db_path.exists():
        db_path.unlink()
    transport = FakeTransport(now + timedelta(minutes=5))
    service = CaptureService(_settings(db_path), Database(db_path), transport)

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert result == {
        "discovered": 1,
        "due": 1,
        "captured": 1,
        "failed": 0,
        "skipped": 0,
        "finalized": 0,
        "waiting": 0,
        "results_captured": 0,
        "results_checked": 0,
    }
    assert transport.match_odds_calls == 1
    assert row["capture_phase"] == "MONITORING"
    assert row["last_capture_at"] is not None
    assert row["next_capture_at"] is not None


@pytest.mark.asyncio
async def test_run_once_uses_betexplorer_timezone_for_scheduler_now(monkeypatch) -> None:
    betexplorer_now = datetime(2026, 4, 28, 16, 0)
    db_path = Path("data/test_tmp/capture_betexplorer_timezone_now.duckdb")
    if db_path.exists():
        db_path.unlink()
    settings = _settings(db_path).model_copy(update={"betexplorer_timezone_offset": "+3"})
    transport = FakeTransport(betexplorer_now + timedelta(minutes=5))
    service = CaptureService(settings, Database(db_path), transport)
    monkeypatch.setattr(
        "betexplorer_scraper.capture.now_for_timezone_offset",
        lambda offset: betexplorer_now if offset == "+3" else datetime(2026, 4, 28, 13, 0),
    )

    result = await service.run_once()
    row = service.database.list_matches()[0]

    assert result["captured"] == 1
    assert transport.match_odds_calls == 1
    assert row["capture_phase"] == "MONITORING"


@pytest.mark.asyncio
async def test_run_once_discovers_future_date_table_rows() -> None:
    now = datetime(2026, 4, 29, 0, 48)
    kickoff = datetime(2026, 4, 29, 23, 0)
    db_path = Path("data/test_tmp/capture_date_table.duckdb")
    if db_path.exists():
        db_path.unlink()

    class DateTableTransport(FakeTransport):
        async def fetch_homepage(self) -> RawResponse:
            return RawResponse("https://www.betexplorer.com/", "<html></html>", 200)

        async def fetch_football_date(self, target_date: date) -> RawResponse:
            dt = f"{kickoff.day},{kickoff.month},{kickoff.year},21,00"
            html = f"""
            <table>
              <tr class="js-tournament">
                <th colspan="2"><a class="table-main__tournament" href="/football/test/">Test Country: Test League</a></th>
              </tr>
              <tr data-dt="{dt}">
                <td><span class="table-main__time">23:00</span><a href="/football/test-league/home-away/abc12345/">Home - Away</a></td>
              </tr>
            </table>
            """
            return RawResponse("https://www.betexplorer.com/football/?year=2026&month=04&day=29", html, 200)

    transport = DateTableTransport(kickoff)
    service = CaptureService(_settings(db_path), Database(db_path), transport)

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]
    status = service.database.status(now=now)

    assert result == {
        "discovered": 1,
        "due": 0,
        "captured": 0,
        "failed": 0,
        "skipped": 1,
        "finalized": 0,
        "waiting": 1,
        "results_captured": 0,
        "results_checked": 0,
    }
    assert transport.match_odds_calls == 0
    assert row["league"] == "Test Country: Test League"
    assert row["capture_phase"] == "WAITING"
    assert row["next_capture_at"] == "2026-04-29T17:00:00"
    assert status["next_capture"] == "2026-04-29T17:00:00"


@pytest.mark.asyncio
async def test_run_once_uses_homepage_visible_local_time() -> None:
    now = datetime(2026, 4, 29, 0, 48)
    db_path = Path("data/test_tmp/capture_homepage_local_time.duckdb")
    if db_path.exists():
        db_path.unlink()

    class HomepageLocalTimeTransport(FakeTransport):
        async def fetch_homepage(self) -> RawResponse:
            html = """
            <p class="table-main__truncate table-main__leaguesNames leaguesNames">Europe: Champions League</p>
            <li data-event-id="abc12345">
              <ul data-dt="29,4,2026,21,00">
                <li><span class="table-main__matchHour">23:00</span></li>
                <a href="/football/europe/champions-league/home-away/abc12345/">
                  <span class="table-main__participantHome">Home</span>
                  <span class="table-main__participantAway">Away</span>
                </a>
              </ul>
            </li>
            """
            return RawResponse("https://www.betexplorer.com/", html, 200)

        async def fetch_football_date(self, target_date: date) -> RawResponse:
            return RawResponse("https://www.betexplorer.com/football/", "<html></html>", 200)

    transport = HomepageLocalTimeTransport(datetime(2026, 4, 29, 23, 0))
    service = CaptureService(_settings(db_path), Database(db_path), transport)

    await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert row["kickoff_time"] == "2026-04-29T23:00:00"
    assert row["next_capture_at"] == "2026-04-29T17:00:00"


@pytest.mark.asyncio
async def test_run_once_captures_all_available_markets() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    db_path = Path("data/test_tmp/capture_all_markets.duckdb")
    if db_path.exists():
        db_path.unlink()
    transport = FakeTransport(now + timedelta(minutes=5))
    service = CaptureService(_all_market_settings(db_path), Database(db_path), transport)

    result = await service.run_once(now=now)
    snapshots = service.database.list_snapshots()

    assert result["captured"] == 1
    assert transport.match_odds_calls == 2
    assert {snapshot["market"] for snapshot in snapshots} == {"1x2", "bts"}


@pytest.mark.asyncio
async def test_partial_required_bookmaker_payload_is_retried_until_complete() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    db_path = Path("data/test_tmp/capture_partial_retries_until_complete.duckdb")
    if db_path.exists():
        db_path.unlink()
    settings = _settings(db_path).model_copy(update={"max_retries_per_match": 3, "retry_delay_seconds": 0})
    transport = PartialThenCompleteOddsTransport(now + timedelta(minutes=5))
    service = CaptureService(settings, Database(db_path), transport)

    result = await service.run_once(now=now)

    assert result["captured"] == 1
    assert transport.match_odds_calls == 2
    snapshots = service.database.list_snapshots()
    assert [snapshot["quality_status"] for snapshot in snapshots] == ["COMPLETE", "PARTIAL"]
    assert service.database.list_matches()[0]["quality_status"] == "COMPLETE"


@pytest.mark.asyncio
async def test_partial_required_bookmaker_payload_retries_until_exhausted() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    db_path = Path("data/test_tmp/capture_partial_retries_exhausted.duckdb")
    if db_path.exists():
        db_path.unlink()
    settings = _settings(db_path).model_copy(update={"max_retries_per_match": 3, "retry_delay_seconds": 0})
    transport = PartialOddsTransport(now + timedelta(minutes=5))
    service = CaptureService(settings, Database(db_path), transport)

    result = await service.run_once(now=now)

    assert result["captured"] == 1
    assert transport.match_odds_calls == 3
    assert {snapshot["quality_status"] for snapshot in service.database.list_snapshots()} == {"FAILED"}


@pytest.mark.asyncio
async def test_archive_football_date_captures_played_matches_and_updates_archive(tmp_path: Path) -> None:
    target_day = date(2026, 5, 14)
    kickoff = datetime(2026, 5, 14, 20, 0)
    db_path = tmp_path / "archive_football_date.duckdb"
    db = Database(db_path)
    service = CaptureService(_settings(db_path), db, FinishedResultTransport(kickoff))

    result = await service.archive_football_date(target_day)
    archive_rows = db.list_played_match_archive()

    assert result["date"] == "2026-05-14"
    assert result["discovered"] == 1
    assert result["captured"] == 1
    assert result["complete"] == 1
    assert result["archived"] == 1
    assert archive_rows[0]["event_id"] == "abc12345"
    assert archive_rows[0]["full_time_score"] == "2-1"
    assert archive_rows[0]["bwin_home_odds"] == 2.2
    assert archive_rows[0]["unibet_away_odds"] == 2.38


@pytest.mark.asyncio
async def test_durable_archive_job_persists_real_event_progress(tmp_path: Path) -> None:
    target_day = date(2026, 5, 14)
    kickoff = datetime(2026, 5, 14, 20, 0)
    db_path = tmp_path / "durable_archive_job.duckdb"
    db = Database(db_path)
    service = CaptureService(_settings(db_path), db, FinishedResultTransport(kickoff))
    job = db.create_archive_job(target_day)

    await service.run_archive_job(str(job["id"]), target_day)

    saved = db.get_archive_job(str(job["id"]))
    assert saved is not None
    assert saved["status"] == "completed"
    assert saved["total_items"] == 1
    assert saved["discovered"] == 1
    assert saved["completed"] == 1
    assert saved["captured"] == 1
    assert saved["scores"] == 1
    assert saved["archived"] == 1
    assert db.resumable_archive_jobs() == []


@pytest.mark.asyncio
async def test_archive_job_reports_explicit_no_odds_as_unavailable_not_failed(tmp_path: Path) -> None:
    target_day = date(2026, 5, 14)
    kickoff = datetime(2026, 5, 14, 20, 0)
    db_path = tmp_path / "archive_no_odds.duckdb"
    db = Database(db_path)
    settings = _settings(db_path).model_copy(update={"max_retries_per_match": 2, "retry_delay_seconds": 0})
    service = CaptureService(settings, db, NoOddsArchiveTransport(kickoff))
    job = db.create_archive_job(target_day)

    result = await service.run_archive_job(str(job["id"]), target_day)
    saved = db.get_archive_job(str(job["id"]))
    items = db.list_archive_job_items(str(job["id"]))

    assert result["unavailable"] == 1
    assert result["failed"] == 0
    assert saved is not None
    assert saved["status"] == "completed_with_gaps"
    assert saved["unavailable"] == 1
    assert saved["failed"] == 0
    assert items[0]["odds_status"] == "unavailable"
    assert items[0]["error_message"] == "BetExplorer reports no bookmaker odds for this match"


@pytest.mark.asyncio
async def test_archive_football_date_accepts_archived_score_without_finished_marker(tmp_path: Path) -> None:
    target_day = date(2026, 5, 14)
    kickoff = datetime(2026, 5, 14, 20, 0)
    db_path = tmp_path / "archive_football_date_score_without_finished.duckdb"
    db = Database(db_path)
    service = CaptureService(_settings(db_path), db, ArchivedScoreWithoutFinishedMarkerTransport(kickoff))

    result = await service.archive_football_date(target_day)
    archive_rows = db.list_played_match_archive()

    assert result["results_captured"] == 1
    assert result["archived"] == 1
    assert archive_rows[0]["full_time_score"] == "2-1"


@pytest.mark.asyncio
async def test_archive_football_date_filters_matches_to_requested_day(tmp_path: Path) -> None:
    target_day = date(2026, 5, 14)
    kickoff = datetime(2026, 5, 14, 20, 0)
    db_path = tmp_path / "archive_football_date_filters_day.duckdb"
    db = Database(db_path)
    service = CaptureService(_settings(db_path), db, MixedDateArchiveTransport(kickoff))

    result = await service.archive_football_date(target_day)
    rows = db.list_matches()

    assert result["discovered"] == 1
    assert result["results_captured"] == 1
    assert [row["event_id"] for row in rows] == ["abc12345"]


@pytest.mark.asyncio
async def test_http_transport_uses_betexplorer_results_page_for_historical_date() -> None:
    captured: dict[str, str] = {}
    transport = HttpBetExplorerTransport("https://www.betexplorer.com")

    async def fake_get(url: str, headers: dict[str, str]) -> RawResponse:
        captured["url"] = url
        return RawResponse(url, "<html></html>", 200)

    transport._get = fake_get  # type: ignore[method-assign]

    await transport.fetch_football_date(date(2026, 6, 20))

    assert captured["url"] == "https://www.betexplorer.com/football/results/?year=2026&month=06&day=20"


@pytest.mark.asyncio
async def test_run_once_captures_stored_due_match_missing_from_discovery() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    kickoff = now + timedelta(minutes=5)
    db_path = Path("data/test_tmp/capture_stored_due.duckdb")
    if db_path.exists():
        db_path.unlink()
    database = Database(db_path)
    transport = NoDiscoveryTransport(kickoff)
    service = CaptureService(_settings(db_path), database, transport)
    match_id = database.upsert_match(
        DiscoveredMatch(
            event_id="abc12345",
            source_url="https://www.betexplorer.com/football/test-league/home-away/abc12345/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=kickoff,
            timing_status=TimingStatus.UNKNOWN,
        )
    )
    database.update_match_schedule(match_id, "WAITING", now - timedelta(seconds=1))

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert result == {
        "discovered": 0,
        "due": 1,
        "captured": 1,
        "failed": 0,
        "skipped": 0,
        "finalized": 0,
        "waiting": 0,
        "results_captured": 0,
        "results_checked": 0,
    }
    assert transport.match_odds_calls == 1
    assert row["capture_phase"] == "MONITORING"
    assert row["bookmaker_count"] == 2
    assert row["next_capture_at"] is not None


@pytest.mark.asyncio
async def test_run_once_finalizes_stored_match_after_capture_window_when_missing_from_discovery() -> None:
    kickoff = datetime(2026, 4, 28, 16, 0)
    now = kickoff + timedelta(minutes=20)
    db_path = Path("data/test_tmp/capture_stored_finalized.duckdb")
    if db_path.exists():
        db_path.unlink()
    database = Database(db_path)
    transport = NoDiscoveryTransport(kickoff)
    service = CaptureService(_settings(db_path), database, transport)
    match_id = database.upsert_match(
        DiscoveredMatch(
            event_id="abc12345",
            source_url="https://www.betexplorer.com/football/test-league/home-away/abc12345/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=kickoff,
            timing_status=TimingStatus.UNKNOWN,
        )
    )
    database.update_match_schedule(match_id, "MONITORING", kickoff - timedelta(minutes=5))

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert result["due"] == 1
    assert result["captured"] == 1
    assert transport.match_odds_calls == 1
    assert row["capture_phase"] == "FINALIZED"
    assert row["next_capture_at"] is None
    assert row["finalized_at"] == now.isoformat()
    assert row["bookmaker_count"] == 2


@pytest.mark.asyncio
async def test_run_once_backfills_empty_finalized_match_with_available_odds() -> None:
    now = datetime(2026, 5, 1, 18, 0)
    kickoff = now - timedelta(hours=2)
    db_path = Path("data/test_tmp/capture_empty_finalized_odds_backfill.duckdb")
    if db_path.exists():
        db_path.unlink()
    database = Database(db_path)
    transport = NoDiscoveryTransport(kickoff)
    service = CaptureService(_settings(db_path), database, transport)
    match_id = database.upsert_match(
        DiscoveredMatch(
            event_id="abc12345",
            source_url="https://www.betexplorer.com/football/test-league/home-away/abc12345/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=kickoff,
            timing_status=TimingStatus.UNKNOWN,
        )
    )
    database.update_match_schedule(match_id, "FINALIZED", None, now - timedelta(minutes=30))

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert result["due"] == 1
    assert result["captured"] == 1
    assert transport.match_odds_calls == 1
    assert row["bookmaker_count"] == 2
    assert row["last_capture_at"] is not None


@pytest.mark.asyncio
async def test_run_once_backfills_empty_finalized_match_even_when_rediscovered() -> None:
    now = datetime(2026, 5, 1, 18, 0)
    kickoff = now - timedelta(hours=2)
    db_path = Path("data/test_tmp/capture_empty_finalized_rediscovered.duckdb")
    if db_path.exists():
        db_path.unlink()
    database = Database(db_path)
    transport = RediscoveryTransport(kickoff)
    service = CaptureService(_settings(db_path), database, transport)
    match_id = database.upsert_match(
        DiscoveredMatch(
            event_id="abc12345",
            source_url="https://www.betexplorer.com/football/test-league/home-away/abc12345/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=kickoff,
            timing_status=TimingStatus.UNKNOWN,
        )
    )
    database.update_match_schedule(match_id, "FINALIZED", None, now - timedelta(minutes=30))

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert result["due"] == 1
    assert result["captured"] == 1
    assert transport.match_odds_calls == 1
    assert row["bookmaker_count"] == 2


@pytest.mark.asyncio
async def test_run_once_captures_finished_result_once() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    kickoff = now - timedelta(hours=3)
    db_path = Path("data/test_tmp/capture_result_once.duckdb")
    if db_path.exists():
        db_path.unlink()
    transport = FinishedResultTransport(kickoff)
    service = CaptureService(_settings(db_path), Database(db_path), transport)

    first = await service.run_once(now=now)
    second = await service.run_once(now=now + timedelta(minutes=1))
    row = service.database.list_matches()[0]
    status = service.database.status(now=now)

    assert first["results_captured"] == 1
    assert second["results_captured"] == 0
    assert row["status"] == "finished"
    assert row["timing_status"] == "FINISHED"
    assert row["live_score"] == "2:1"
    assert row["result_captured_at"] is not None
    assert status["result_captured_matches"] == 1


@pytest.mark.asyncio
async def test_run_once_backfills_result_from_match_page_for_stored_match() -> None:
    now = datetime(2026, 5, 1, 18, 0)
    kickoff = now - timedelta(days=2)
    db_path = Path("data/test_tmp/capture_result_backfill.duckdb")
    if db_path.exists():
        db_path.unlink()
    database = Database(db_path)
    transport = MatchPageResultTransport(kickoff)
    service = CaptureService(_settings(db_path), database, transport)
    match_id = database.upsert_match(
        DiscoveredMatch(
            event_id="abc12345",
            source_url="https://www.betexplorer.com/football/test-league/home-away/abc12345/",
            league="Test League",
            home_team="Home",
            away_team="Away",
            kickoff_time=kickoff,
            timing_status=TimingStatus.UNKNOWN,
            status="scheduled",
        )
    )
    database.update_match_schedule(match_id, "FINALIZED", None, now - timedelta(days=1))

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert result["results_checked"] == 1
    assert result["results_captured"] == 1
    assert row["status"] == "finished"
    assert row["timing_status"] == "FINISHED"
    assert row["live_score"] == "5:2"
    assert row["result_captured_at"] is not None
