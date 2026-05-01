from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import DiscoveredMatch, TimingStatus


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    upcoming_window_minutes: int
    recently_started_window_minutes: int
    max_match_age_after_kickoff_minutes: int
    monitoring_capture_poll_interval_seconds: int
    final_capture_poll_interval_seconds: int
    final_capture_fast_window_minutes: int
    discovery_poll_interval_seconds: int


@dataclass(frozen=True, slots=True)
class CaptureDecision:
    phase: str
    should_capture: bool
    next_capture_at: datetime | None
    finalized_at: datetime | None = None


class Scheduler:
    def __init__(self, config: SchedulerConfig) -> None:
        self.config = config

    def plan(
        self,
        match: DiscoveredMatch,
        now: datetime,
        next_capture_at: datetime | None = None,
        finalized_at: datetime | None = None,
        last_capture_at: datetime | None = None,
    ) -> CaptureDecision:
        if finalized_at is not None:
            return CaptureDecision("FINALIZED", False, None, finalized_at)
        if match.timing_status == TimingStatus.FINISHED:
            return CaptureDecision("FINALIZED", False, None, now)
        if match.kickoff_time is None:
            return CaptureDecision(
                "DISCOVERY_ONLY",
                False,
                now + timedelta(seconds=self.config.discovery_poll_interval_seconds),
            )

        upcoming_start = match.kickoff_time - timedelta(minutes=self.config.upcoming_window_minutes)
        final_end = match.kickoff_time + timedelta(minutes=self.config.max_match_age_after_kickoff_minutes)
        interval = self._capture_interval(match.kickoff_time, now)

        if now < upcoming_start:
            return CaptureDecision("WAITING", False, upcoming_start)
        if now > final_end:
            if last_capture_at is None:
                return CaptureDecision("FINALIZING", True, None, now)
            return CaptureDecision("FINALIZED", False, None, now)

        phase = "FINALIZING" if now > match.kickoff_time or match.timing_status == TimingStatus.LIVE else "MONITORING"
        due = next_capture_at is None or next_capture_at <= now
        return CaptureDecision(phase, due, now + interval if due else next_capture_at)

    def _capture_interval(self, kickoff_time: datetime, now: datetime) -> timedelta:
        fast_window_start = kickoff_time - timedelta(minutes=self.config.final_capture_fast_window_minutes)
        if now < fast_window_start:
            return timedelta(seconds=self.config.monitoring_capture_poll_interval_seconds)
        return timedelta(seconds=self.config.final_capture_poll_interval_seconds)
