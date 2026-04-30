from __future__ import annotations

from datetime import datetime, timedelta

from .models import TimingStatus


def classify_timing(
    kickoff_time: datetime | None,
    now: datetime,
    upcoming_window_minutes: int,
    recently_started_window_minutes: int,
    is_live: bool = False,
    is_finished: bool = False,
) -> TimingStatus:
    if is_finished:
        return TimingStatus.FINISHED
    if is_live:
        return TimingStatus.LIVE
    if kickoff_time is None:
        return TimingStatus.UNKNOWN

    delta = kickoff_time - now
    if timedelta(0) <= delta <= timedelta(minutes=upcoming_window_minutes):
        return TimingStatus.UPCOMING_SOON
    if timedelta(minutes=-1) <= delta < timedelta(0):
        return TimingStatus.JUST_STARTED
    if timedelta(minutes=-recently_started_window_minutes) <= delta < timedelta(minutes=-1):
        return TimingStatus.RECENTLY_STARTED
    return TimingStatus.UNKNOWN
