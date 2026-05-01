from __future__ import annotations

import re
from datetime import datetime, timedelta


def final_snapshot_age_to_kickoff_seconds(
    kickoff_time: datetime | None,
    captured_at: datetime | None,
    timezone_offset: str = "+0",
) -> int | None:
    if kickoff_time is None or captured_at is None:
        return None
    captured_local = captured_at + timedelta(seconds=parse_timezone_offset_seconds(timezone_offset))
    return round((kickoff_time - captured_local).total_seconds())


def parse_timezone_offset_seconds(value: str) -> int:
    match = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", value.strip())
    if not match:
        return 0
    sign = -1 if match.group(1) == "-" else 1
    hours = int(match.group(2))
    minutes = int(match.group(3) or "0")
    return sign * ((hours * 60 + minutes) * 60)
