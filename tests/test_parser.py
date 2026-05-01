from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from betexplorer_scraper.models import TimingStatus
from betexplorer_scraper.parsers import DiscoveryParser, OddsParser


def _match_odds_payload(fragment: str) -> str:
    har_path = next(Path("har").glob(f"*{fragment}*.har"))
    har = json.loads(har_path.read_text(encoding="utf-8"))
    for entry in har["log"]["entries"]:
        if "/match-odds/" in entry["request"]["url"]:
            return entry["response"]["content"]["text"]
    raise AssertionError("HAR has no match-odds payload")


def test_parse_all_bookmaker_rows_from_match_odds_har() -> None:
    rows = OddsParser().parse_match_odds_payload(_match_odds_payload("16-49-18"))

    names = {row.normalized_bookmaker for row in rows}

    assert len(rows) >= 10
    assert "bwin" in names
    assert "unibet" in names
    bwin = next(row for row in rows if row.normalized_bookmaker == "bwin")
    assert (bwin.home_odds, bwin.draw_odds, bwin.away_odds) == (2.20, 3.10, 2.87)


def test_parse_unibet_when_bwin_missing() -> None:
    rows = OddsParser().parse_match_odds_payload(_match_odds_payload("16-50-40"))

    names = {row.normalized_bookmaker for row in rows}

    assert "unibet" in names
    assert "bwin" not in names


def test_parse_market_line_from_modified_market_rows() -> None:
    payload = json.dumps(
        {
            "odds": """
            <table><tbody>
              <tr data-bid="847" data-bookie-id="1082">
                <td><a class="in-bookmaker-logo-link">Duelbits</a></td>
                <td class="table-main__doubleparameter">2.5</td>
                <td data-odd="1.90" data-bookie="Duelbits"></td>
                <td data-odd="1.85" data-bookie="Duelbits"></td>
              </tr>
            </tbody></table>
            """
        }
    )

    rows = OddsParser().parse_match_odds_payload(payload)

    assert rows[0].raw_attributes["market_line"] == "2.5"


def test_discovery_parser_marks_old_scored_row_as_finished() -> None:
    html = """
    <table>
      <tr class="js-tournament">
        <th colspan="2"><a class="table-main__tournament" href="/football/test/">Country: League</a></th>
      </tr>
      <tr data-dt="1,5,2026,14,00">
        <td>
          <span class="table-main__time">14:00</span>
          <a href="/football/test-league/home-away/abc12345/">Home - Away</a>
          <span class="table-main__result">2:1</span>
        </td>
      </tr>
    </table>
    """

    rows = DiscoveryParser(finish_grace_minutes=120).parse_homepage(html, datetime(2026, 5, 1, 18, 0))

    assert rows[0].status == "finished"
    assert rows[0].timing_status == TimingStatus.FINISHED
    assert rows[0].live_score == "2:1"


def test_parse_finished_match_page_result() -> None:
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"SportsEvent","eventStatus":"Finished"}
    </script>
    <div class="list-details">
      <p class="list-details__item__score">5:2</p>
      <p class="list-details__item__partial">(2:0, 3:2)</p>
    </div>
    """

    finished, score = DiscoveryParser().parse_match_page_result(html)

    assert finished is True
    assert score == "5:2"


def test_parse_match_page_start_time_converts_to_configured_timezone() -> None:
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"SportsEvent","startDate":"2026-05-01T21:00:00+02:00"}
    </script>
    """

    kickoff = DiscoveryParser().parse_match_page_start_time(html, "+3")

    assert kickoff == datetime(2026, 5, 1, 22, 0)
