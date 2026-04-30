from __future__ import annotations

from datetime import datetime, timedelta

from betexplorer_scraper.models import TimingStatus
from betexplorer_scraper.timing import classify_timing


def test_classifies_upcoming_soon_inside_window() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    assert classify_timing(now + timedelta(minutes=20), now, 30, 10) == TimingStatus.UPCOMING_SOON


def test_classifies_recently_started_after_kickoff() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    assert classify_timing(now - timedelta(minutes=7), now, 30, 10) == TimingStatus.RECENTLY_STARTED


def test_live_flag_takes_precedence_over_time_window() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    assert classify_timing(now + timedelta(minutes=20), now, 30, 10, is_live=True) == TimingStatus.LIVE
