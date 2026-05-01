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
            max_match_age_after_kickoff_minutes=5,
            monitoring_capture_poll_interval_seconds=120,
            final_capture_poll_interval_seconds=20,
            final_capture_fast_window_minutes=3,
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
    decision = _scheduler().plan(_match(now + timedelta(minutes=2)), now)

    assert decision.phase == "MONITORING"
    assert decision.should_capture is True
    assert decision.next_capture_at == now + timedelta(seconds=20)


def test_early_capture_window_uses_slower_monitoring_interval() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now + timedelta(minutes=20)), now)

    assert decision.phase == "MONITORING"
    assert decision.should_capture is True
    assert decision.next_capture_at == now + timedelta(seconds=120)


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


def test_stale_next_capture_after_corrected_kickoff_is_due_now() -> None:
    now = datetime(2026, 4, 28, 21, 40)
    kickoff = datetime(2026, 4, 28, 22, 0)
    decision = _scheduler().plan(
        _match(kickoff),
        now,
        next_capture_at=datetime(2026, 4, 28, 22, 30),
    )

    assert decision.phase == "MONITORING"
    assert decision.should_capture is True
    assert decision.next_capture_at == now + timedelta(seconds=120)


def test_planned_next_capture_is_clamped_to_post_kickoff_window() -> None:
    now = datetime(2026, 4, 28, 22, 4, 50)
    kickoff = datetime(2026, 4, 28, 22, 0)
    decision = _scheduler().plan(_match(kickoff), now)

    assert decision.phase == "FINALIZING"
    assert decision.should_capture is True
    assert decision.next_capture_at == datetime(2026, 4, 28, 22, 5)


def test_recently_started_match_enters_finalizing_phase() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now - timedelta(minutes=4)), now)

    assert decision.phase == "FINALIZING"
    assert decision.should_capture is True
    assert decision.next_capture_at == now + timedelta(seconds=20)


def test_match_is_finalized_after_post_kickoff_capture_window() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now - timedelta(minutes=6)), now, last_capture_at=now - timedelta(minutes=3))

    assert decision.phase == "FINALIZED"
    assert decision.should_capture is False
    assert decision.finalized_at == now


def test_late_match_without_previous_capture_gets_one_recovery_capture() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now - timedelta(minutes=40)), now, last_capture_at=None)

    assert decision.phase == "FINALIZING"
    assert decision.should_capture is True
    assert decision.next_capture_at is None
    assert decision.finalized_at == now


def test_late_match_with_previous_capture_is_finalized() -> None:
    now = datetime(2026, 4, 28, 16, 0)
    decision = _scheduler().plan(_match(now - timedelta(minutes=40)), now, last_capture_at=now - timedelta(minutes=35))

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
