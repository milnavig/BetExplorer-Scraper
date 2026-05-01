from __future__ import annotations

import json
from pathlib import Path

from betexplorer_scraper.parsers import OddsParser


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
