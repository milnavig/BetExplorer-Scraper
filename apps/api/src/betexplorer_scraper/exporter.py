from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

import pandas as pd

from .models import DiscoveredMatch, OddsSnapshot
from .snapshot_metrics import parse_timezone_offset_seconds


def final_odds_rows(items: list[tuple[DiscoveredMatch, OddsSnapshot]], timezone_offset: str = "+0") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for match, snapshot in items:
        row: dict[str, object] = {
            "captured_at": format_export_datetime(snapshot.captured_at, timezone_offset, stored_as_utc=True),
            "kickoff_time": format_export_datetime(match.kickoff_time, timezone_offset),
            "status": export_status(match),
            "match_status": match.status,
            "capture_phase": match.capture_phase,
            "finalized_at": format_export_datetime(match.finalized_at, timezone_offset),
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
                        "market_line": odds.raw_attributes.get("market_line"),
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


def final_odds_long_rows(items: list[tuple[DiscoveredMatch, OddsSnapshot]], timezone_offset: str = "+0") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for match, snapshot in items:
        required_bookmakers = {required.strip().lower() for required in snapshot.required_bookmakers}
        labels = selection_labels(match, snapshot.market)
        for odds in snapshot.bookmaker_odds:
            row: dict[str, object] = {
                "captured_at": format_export_datetime(snapshot.captured_at, timezone_offset, stored_as_utc=True),
                "kickoff_time": format_export_datetime(match.kickoff_time, timezone_offset),
                "status": export_status(match),
                "match_status": match.status,
                "capture_phase": match.capture_phase,
                "finalized_at": format_export_datetime(match.finalized_at, timezone_offset),
                "league": match.league,
                "home_team": match.home_team,
                "away_team": match.away_team,
                "source_url": match.source_url,
                "quality_status": snapshot.quality_status.value,
                "is_final": True,
                "source_page_type": snapshot.source_page_type,
                "market": snapshot.market,
                "market_line": odds.raw_attributes.get("market_line"),
                "bookmaker": odds.bookmaker,
                "normalized_bookmaker": odds.normalized_bookmaker,
                "bookmaker_id": odds.bookmaker_id,
                "betexplorer_bookmaker_id": odds.betexplorer_bookmaker_id,
                "is_required_bookmaker": odds.normalized_bookmaker in required_bookmakers,
                "selection_1": labels[0],
                "selection_1_odds": odds.home_odds,
                "selection_2": labels[1],
                "selection_2_odds": odds.draw_odds,
                "selection_3": labels[2],
                "selection_3_odds": odds.away_odds,
                "raw_row_text": odds.raw_row_text,
                "raw_attributes_json": json.dumps(odds.raw_attributes, ensure_ascii=False),
            }
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


def format_export_datetime(
    value: datetime | None,
    timezone_offset: str,
    stored_as_utc: bool = False,
) -> str | None:
    if value is None:
        return None
    offset_seconds = parse_timezone_offset_seconds(timezone_offset)
    local_value = value + timedelta(seconds=offset_seconds) if stored_as_utc else value
    return f"{local_value.isoformat()}{format_timezone_offset(timezone_offset)}"


def format_timezone_offset(timezone_offset: str) -> str:
    offset_seconds = parse_timezone_offset_seconds(timezone_offset)
    sign = "+" if offset_seconds >= 0 else "-"
    absolute = abs(offset_seconds)
    hours, remainder = divmod(absolute, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def selection_labels(match: DiscoveredMatch, market: str) -> tuple[str | None, str | None, str | None]:
    market_key = market.lower()
    if market_key == "ou":
        return ("Over", "Under", None)
    if market_key == "bts":
        return ("Yes", "No", None)
    if market_key == "dc":
        return ("1X", "12", "X2")
    if market_key in {"ah", "ha", "dnb"}:
        return (match.home_team, match.away_team, None)
    return (match.home_team, "Draw", match.away_team)


def export_final_odds(
    items: list[tuple[DiscoveredMatch, OddsSnapshot]],
    export_dir: Path,
    date_slug: str,
    fmt: str,
    timezone_offset: str = "+0",
    layout: str = "wide",
) -> Path:
    export_dir.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    layout = layout.lower()
    if layout == "wide":
        rows = final_odds_rows(items, timezone_offset)
        filename = f"final_odds_{date_slug}.{fmt}"
    elif layout == "long":
        rows = final_odds_long_rows(items, timezone_offset)
        filename = f"final_odds_long_{date_slug}.{fmt}"
    else:
        raise ValueError("layout must be wide or long")
    path = export_dir / filename
    frame = pd.DataFrame(rows)
    if fmt == "csv":
        frame.to_csv(path, index=False)
    elif fmt == "xlsx":
        frame.to_excel(path, index=False)
    else:
        raise ValueError("format must be csv or xlsx")
    return path
