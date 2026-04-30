from __future__ import annotations

from datetime import datetime, timedelta

from betexplorer_scraper.models import DiscoveredMatch, TimingStatus
from betexplorer_scraper.scheduler import Scheduler, SchedulerConfig


def _match(kickoff: datetime | None, status: TimingStatus = TimingStatus.UNKNOWN) -> DiscoveredMatch:
    return DiscoveredMatch(
        event_id="abc12345",
        source_url="https://www.betexplorer.com/football/test/abc12345/",
        league="Test League",
        home_team="Home",
        away_team="Away",
        kickoff_time=kickoff,
        timing_status=status,
    )


def _scheduler() -> Scheduler:
    return Scheduler(
        SchedulerConfig(
            upcoming_window_minutes=30,
            recently_started_window_minutes=10,
            max_match_age_after_kickoff_minutes=10,
            final_capture_poll_interval_seconds=10,
            discovery_poll_interval_seconds=60,
        )
    )


def test_far_future_match_waits_until_upcoming_window() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now + timedelta(hours=2)), now)

    assert decision.phase == "WAITING"
    assert decision.should_capture is False
    assert decision.next_capture_at == now + timedelta(hours=2) - timedelta(minutes=30)


def test_upcoming_match_is_due_when_no_next_capture_exists() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now + timedelta(minutes=5)), now)

    assert decision.phase == "MONITORING"
    assert decision.should_capture is True
    assert decision.next_capture_at == now + timedelta(seconds=10)


def test_due_match_is_skipped_until_next_capture_time() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(
        _match(now + timedelta(minutes=5)),
        now,
        next_capture_at=now + timedelta(seconds=7),
    )

    assert decision.phase == "MONITORING"
    assert decision.should_capture is False
    assert decision.next_capture_at == now + timedelta(seconds=7)


def test_recently_started_match_enters_finalizing_phase() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now - timedelta(minutes=4)), now)

    assert decision.phase == "FINALIZING"
    assert decision.should_capture is True
    assert decision.next_capture_at == now + timedelta(seconds=10)


def test_match_is_finalized_after_post_kickoff_capture_window() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now - timedelta(minutes=11)), now)

    assert decision.phase == "FINALIZED"
    assert decision.should_capture is False
    assert decision.finalized_at == now


def test_already_finalized_match_is_never_due() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    finalized_at = now - timedelta(minutes=1)
    decision = _scheduler().plan(_match(now + timedelta(minutes=5)), now, finalized_at=finalized_at)

    assert decision.phase == "FINALIZED"
    assert decision.should_capture is False
    assert decision.finalized_at == finalized_at
