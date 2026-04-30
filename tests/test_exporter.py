from __future__ import annotations

from datetime import datetime

from betexplorer_scraper.exporter import final_odds_rows
from betexplorer_scraper.models import BookmakerOdds, DiscoveredMatch, OddsSnapshot, SnapshotQuality, TimingStatus


def test_final_odds_export_contains_required_flattened_columns_and_all_bookmakers() -> None:
    match = DiscoveredMatch(
        event_id="abc123",
        source_url="https://www.betexplorer.com/football/test/abc123/",
        league="Test League",
        home_team="Home",
        away_team="Away",
        kickoff_time=datetime(2026, 4, 28, 20, 0),
        timing_status=TimingStatus.UPCOMING_SOON,
    )
    snapshot = OddsSnapshot(
        event_id="abc123",
        market="1x2",
        captured_at=datetime(2026, 4, 28, 16, 0),
        quality_status=SnapshotQuality.COMPLETE,
        required_bookmakers=["Bwin", "Unibet"],
        bookmaker_odds=[
            BookmakerOdds("bwin", "bwin", 2.2, 3.1, 2.87),
            BookmakerOdds("Unibet", "unibet", 2.55, 3.1, 2.38),
            BookmakerOdds("Betway", "betway", 2.4, 3.2, 2.7),
        ],
    )

    rows = final_odds_rows([(match, snapshot)])

    assert rows[0]["bwin_home"] == 2.2
    assert rows[0]["unibet_away"] == 2.38
    assert rows[0]["bookmaker_count"] == 3
    assert rows[0]["all_bookmakers_json"].startswith("[")
