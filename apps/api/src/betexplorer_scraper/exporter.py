from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .models import DiscoveredMatch, OddsSnapshot
from .snapshot_metrics import final_snapshot_age_to_kickoff_seconds


def final_odds_rows(items: list[tuple[DiscoveredMatch, OddsSnapshot]], timezone_offset: str = "+0") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for match, snapshot in items:
        row: dict[str, object] = {
            "captured_at": snapshot.captured_at.isoformat(),
            "kickoff_time": match.kickoff_time.isoformat() if match.kickoff_time else None,
            "final_snapshot_age_to_kickoff_seconds": final_snapshot_age_to_kickoff_seconds(
                match.kickoff_time,
                snapshot.captured_at,
                timezone_offset,
            ),
            "status": export_status(match),
            "match_status": match.status,
            "timing_status": match.timing_status.value,
            "capture_phase": match.capture_phase,
            "finalized_at": match.finalized_at.isoformat() if match.finalized_at else None,
            "league": match.league,
            "home_team": match.home_team,
            "away_team": match.away_team,
            "source_url": match.source_url,
            "quality_status": snapshot.quality_status.value,
            "is_final": True,
            "source_page_type": snapshot.source_page_type,
            "market": snapshot.market,
            "bookmaker_count": len(snapshot.bookmaker_odds),
            "all_bookmakers_json": json.dumps(
                [
                    {
                        "bookmaker": odds.bookmaker,
                        "home": odds.home_odds,
                        "draw": odds.draw_odds,
                        "away": odds.away_odds,
                    }
                    for odds in snapshot.bookmaker_odds
                ],
                ensure_ascii=False,
            ),
        }
        for required in snapshot.required_bookmakers:
            normalized = required.strip().lower()
            odds = next((item for item in snapshot.bookmaker_odds if item.normalized_bookmaker == normalized), None)
            key = normalized.replace(" ", "_")
            row[f"{key}_home"] = odds.home_odds if odds else None
            row[f"{key}_draw"] = odds.draw_odds if odds else None
            row[f"{key}_away"] = odds.away_odds if odds else None
        rows.append(row)
    return rows


def export_status(match: DiscoveredMatch) -> str:
    if match.capture_phase:
        return match.capture_phase
    if match.finalized_at:
        return "FINALIZED"
    if match.timing_status.value != "UNKNOWN":
        return match.timing_status.value
    if match.status and match.status != "scheduled":
        return match.status.upper()
    return "CAPTURED"


def export_final_odds(
    items: list[tuple[DiscoveredMatch, OddsSnapshot]],
    export_dir: Path,
    date_slug: str,
    fmt: str,
    timezone_offset: str = "+0",
) -> Path:
    export_dir.mkdir(parents=True, exist_ok=True)
    rows = final_odds_rows(items, timezone_offset)
    path = export_dir / f"final_odds_{date_slug}.{fmt}"
    frame = pd.DataFrame(rows)
    if fmt == "csv":
        frame.to_csv(path, index=False)
    elif fmt == "xlsx":
        frame.to_excel(path, index=False)
    else:
        raise ValueError("format must be csv or xlsx")
    return path
