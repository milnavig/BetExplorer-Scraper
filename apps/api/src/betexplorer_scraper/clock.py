from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .snapshot_metrics import parse_timezone_offset_seconds


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def now_for_timezone_offset(timezone_offset: str) -> datetime:
    return utc_now() + timedelta(seconds=parse_timezone_offset_seconds(timezone_offset))
