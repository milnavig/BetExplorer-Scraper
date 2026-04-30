from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from betexplorer_scraper.capture import CaptureService
from betexplorer_scraper.config import Settings
from betexplorer_scraper.database import Database
from betexplorer_scraper.transport import BetExplorerTransport, RawResponse


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


def _settings(db_path: Path) -> Settings:
    return Settings(
        database_path=db_path,
        raw_snapshot_dir=db_path.parent / "raw",
        export_dir=db_path.parent / "exports",
        log_dir=db_path.parent / "logs",
        upcoming_window_minutes=30,
        recently_started_window_minutes=10,
        max_match_age_after_kickoff_minutes=10,
        final_capture_poll_interval_seconds=10,
        discovery_poll_interval_seconds=60,
        max_retries_per_match=1,
    )


@pytest.mark.asyncio
async def test_run_once_discovers_far_future_match_without_fetching_odds() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    db_path = Path("data/test_tmp/capture_far.duckdb")
    if db_path.exists():
        db_path.unlink()
    transport = FakeTransport(now + timedelta(hours=2))
    service = CaptureService(_settings(db_path), Database(db_path), transport)

    result = await service.run_once(now=now)
    row = service.database.list_matches()[0]

    assert result == {"discovered": 1, "due": 0, "captured": 0, "failed": 0, "skipped": 1, "finalized": 0, "waiting": 1}
    assert transport.match_odds_calls == 0
    assert row["capture_phase"] == "WAITING"
    assert row["next_capture_at"] == (now + timedelta(hours=2) - timedelta(minutes=30)).isoformat()


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

    assert result == {"discovered": 1, "due": 1, "captured": 1, "failed": 0, "skipped": 0, "finalized": 0, "waiting": 0}
    assert transport.match_odds_calls == 1
    assert row["capture_phase"] == "MONITORING"
    assert row["last_capture_at"] is not None
    assert row["next_capture_at"] is not None


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
    status = service.database.status()

    assert result == {"discovered": 1, "due": 0, "captured": 0, "failed": 0, "skipped": 1, "finalized": 0, "waiting": 1}
    assert transport.match_odds_calls == 0
    assert row["league"] == "Test Country: Test League"
    assert row["capture_phase"] == "WAITING"
    assert row["next_capture_at"] == "2026-04-29T22:30:00"
    assert status["next_capture"] == "2026-04-29T22:30:00"


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
    assert row["next_capture_at"] == "2026-04-29T22:30:00"
