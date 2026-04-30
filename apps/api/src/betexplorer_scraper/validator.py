from __future__ import annotations

from .models import BookmakerOdds, SnapshotQuality
from .utils import normalize_bookmaker_name


def classify_snapshot_quality(odds: list[BookmakerOdds], required_bookmakers: list[str]) -> SnapshotQuality:
    available = {item.normalized_bookmaker for item in odds if item.is_available}
    required = {normalize_bookmaker_name(item) for item in required_bookmakers}
    found = available.intersection(required)
    if required and found == required:
        return SnapshotQuality.COMPLETE
    if found:
        return SnapshotQuality.PARTIAL
    return SnapshotQuality.FAILED


def required_bookmaker_presence(odds: list[BookmakerOdds], required_bookmakers: list[str]) -> dict[str, bool]:
    available = {item.normalized_bookmaker for item in odds if item.is_available}
    return {name: normalize_bookmaker_name(name) in available for name in required_bookmakers}
