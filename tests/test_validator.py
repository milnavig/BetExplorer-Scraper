from __future__ import annotations

from betexplorer_scraper.models import BookmakerOdds, SnapshotQuality
from betexplorer_scraper.validator import classify_snapshot_quality, required_bookmaker_presence


def _row(name: str) -> BookmakerOdds:
    return BookmakerOdds(
        bookmaker=name,
        normalized_bookmaker=name.lower(),
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
    )


def test_classifies_complete_when_all_required_bookmakers_exist() -> None:
    assert classify_snapshot_quality([_row("Bwin"), _row("Unibet"), _row("Betway")], ["Bwin", "Unibet"]) == SnapshotQuality.COMPLETE


def test_classifies_partial_when_only_one_required_bookmaker_exists() -> None:
    assert classify_snapshot_quality([_row("Unibet"), _row("Betway")], ["Bwin", "Unibet"]) == SnapshotQuality.PARTIAL


def test_classifies_failed_when_only_non_required_bookmakers_exist() -> None:
    assert classify_snapshot_quality([_row("Betway")], ["Bwin", "Unibet"]) == SnapshotQuality.FAILED


def test_required_presence_is_reported_by_configured_display_names() -> None:
    assert required_bookmaker_presence([_row("Unibet")], ["Bwin", "Unibet"]) == {"Bwin": False, "Unibet": True}
