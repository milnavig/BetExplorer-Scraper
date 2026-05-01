from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class TimingStatus(StrEnum):
    UPCOMING_SOON = "UPCOMING_SOON"
    JUST_STARTED = "JUST_STARTED"
    RECENTLY_STARTED = "RECENTLY_STARTED"
    LIVE = "LIVE"
    FINISHED = "FINISHED"
    UNKNOWN = "UNKNOWN"


class SnapshotQuality(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class CaptureType(StrEnum):
    PRE_MATCH = "PRE_MATCH"
    LIVE_PREMATCH_TAB = "LIVE_PREMATCH_TAB"


@dataclass(slots=True)
class DiscoveredMatch:
    event_id: str
    source_url: str
    league: str | None
    home_team: str
    away_team: str
    kickoff_time: datetime | None
    timing_status: TimingStatus = TimingStatus.UNKNOWN
    status: str = "scheduled"
    live_score: str | None = None
    capture_phase: str | None = None
    finalized_at: datetime | None = None


@dataclass(slots=True)
class BookmakerOdds:
    bookmaker: str
    normalized_bookmaker: str
    home_odds: float | None
    draw_odds: float | None
    away_odds: float | None
    bookmaker_id: str | None = None
    betexplorer_bookmaker_id: str | None = None
    raw_row_text: str = ""
    raw_attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.home_odds is not None and self.draw_odds is not None


@dataclass(slots=True)
class OddsSnapshot:
    event_id: str
    market: str
    captured_at: datetime
    quality_status: SnapshotQuality
    bookmaker_odds: list[BookmakerOdds]
    required_bookmakers: list[str]
    source_page_type: str = "MATCH_ODDS"
    capture_type: CaptureType = CaptureType.PRE_MATCH
    raw_payload_path: str | None = None


@dataclass(slots=True)
class CaptureAttempt:
    event_id: str
    source_url: str
    attempt_number: int
    status: str
    started_at: datetime
    finished_at: datetime
    error_message: str | None
    required_found: dict[str, bool]
