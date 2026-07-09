from __future__ import annotations

import hashlib
import re
from threading import Lock
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docx import Document

if TYPE_CHECKING:
    from .database import Database


NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
SCORE_RE = re.compile(r"^(\d+)\s*[-:]\s*(\d+)\.?$")
NEIGHBOR_TOLERANCE = 0.05
ONE_DRAW_MIN_SAMPLE = 2


def normalize_odds(value: float | str | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(str(value).strip()), 2)
    except ValueError:
        return None


def normalize_score(value: str | None) -> str | None:
    if not value:
        return None
    match = SCORE_RE.match(value.strip())
    if not match:
        return None
    return f"{int(match.group(1))}-{int(match.group(2))}"


def compute_outcome_stats(scores: list[str]) -> dict[str, float | int]:
    parsed = [_parse_score(score) for score in scores]
    parsed = [score for score in parsed if score is not None]
    sample_size = len(parsed)
    if sample_size == 0:
        return {
            "sample_size": 0,
            "home_win_pct": 0.0,
            "draw_pct": 0.0,
            "away_win_pct": 0.0,
            "over_0_5_pct": 0.0,
            "over_1_5_pct": 0.0,
            "over_2_5_pct": 0.0,
            "btts_pct": 0.0,
            "double_chance_1x_pct": 0.0,
            "double_chance_x2_pct": 0.0,
            "double_chance_12_pct": 0.0,
        }

    home_wins = sum(1 for home, away in parsed if home > away)
    draws = sum(1 for home, away in parsed if home == away)
    away_wins = sum(1 for home, away in parsed if home < away)
    over_0_5 = sum(1 for home, away in parsed if home + away > 0.5)
    over_1_5 = sum(1 for home, away in parsed if home + away > 1.5)
    over_2_5 = sum(1 for home, away in parsed if home + away > 2.5)
    btts = sum(1 for home, away in parsed if home > 0 and away > 0)

    return {
        "sample_size": sample_size,
        "home_win_pct": _pct(home_wins, sample_size),
        "draw_pct": _pct(draws, sample_size),
        "away_win_pct": _pct(away_wins, sample_size),
        "over_0_5_pct": _pct(over_0_5, sample_size),
        "over_1_5_pct": _pct(over_1_5, sample_size),
        "over_2_5_pct": _pct(over_2_5, sample_size),
        "btts_pct": _pct(btts, sample_size),
        "double_chance_1x_pct": _pct(home_wins + draws, sample_size),
        "double_chance_x2_pct": _pct(away_wins + draws, sample_size),
        "double_chance_12_pct": _pct(home_wins + away_wins, sample_size),
    }


class HistoricalDocxImporter:
    def __init__(self, database: Database) -> None:
        self.database = database

    def import_roots(self, roots: list[Path]) -> dict[str, int]:
        files_seen = 0
        files_imported = 0
        records_imported = 0
        warning_count = 0
        for root in roots:
            if not root.exists():
                continue
            for dataset_dir, dataset in _dataset_directories(root):
                for path in sorted(dataset_dir.rglob("*.docx")):
                    files_seen += 1
                    fingerprint = _file_fingerprint(path)
                    if self.database.historical_file_is_current(str(path), fingerprint):
                        continue
                    records, warnings = self._parse_file(path, dataset)
                    self.database.replace_historical_records(str(path), records)
                    self.database.record_historical_import_file(str(path), dataset, fingerprint, len(records), len(warnings))
                    files_imported += 1
                    records_imported += len(records)
                    warning_count += len(warnings)
        return {
            "files_seen": files_seen,
            "files_imported": files_imported,
            "records_imported": records_imported,
            "warnings": warning_count,
        }

    def _parse_file(self, path: Path, dataset: str) -> tuple[list[dict[str, Any]], list[str]]:
        document = Document(str(path))
        records: list[dict[str, Any]] = []
        warnings: list[str] = []
        query_odds: tuple[float, float, float] | None = None
        source_home_bucket = normalize_odds(path.parent.name)
        source_away_file = None if path.stem.lower() == "odds" else normalize_odds(path.stem)

        for table_index, table in enumerate(document.tables):
            for row_index, row in enumerate(table.rows):
                cells = [_cell_text(cell.text) for cell in row.cells[:5]]
                if not any(cells):
                    continue
                odds = _row_odds(cells)
                full_time_score = normalize_score(cells[3] if len(cells) > 3 else "")
                half_time_score = normalize_score(cells[4] if len(cells) > 4 else "")
                has_score = full_time_score is not None

                if odds and not has_score:
                    query_odds = odds
                    continue
                if odds and has_score:
                    effective_query = query_odds or odds
                    records.append(
                        _record(
                            dataset,
                            str(path),
                            source_home_bucket,
                            source_away_file,
                            effective_query,
                            odds,
                            full_time_score,
                            half_time_score,
                            "parsed",
                            None,
                        )
                    )
                    continue
                if has_score and query_odds:
                    records.append(
                        _record(
                            dataset,
                            str(path),
                            source_home_bucket,
                            source_away_file,
                            query_odds,
                            (None, None, None),
                            full_time_score,
                            half_time_score,
                            "inherited_odds",
                            None,
                        )
                    )
                    continue
                warning = f"{path}:{table_index + 1}:{row_index + 1}: unparsed row"
                warnings.append(warning)

        return records, warnings


class HistoricalSignalAutoRefresh:
    def __init__(self, database: Database, importer: HistoricalDocxImporter, roots: list[Path]) -> None:
        self.database = database
        self.importer = importer
        self.roots = roots
        self._lock = Lock()

    def refresh(self, reason: str) -> dict[str, int]:
        with self._lock:
            import_result = self.importer.import_roots(self.roots)
            archive_result = self.database.archive_played_matches()
            recompute_result = self.database.recompute_historical_signals()
            result = {
                **import_result,
                **archive_result,
                **{f"recompute_{key}": value for key, value in recompute_result.items()},
            }
            self.database.log("info", "historical", "auto_refresh_completed", details={"reason": reason, **result})
            return result


def _record(
    dataset: str,
    source_file: str,
    source_home_bucket: float | None,
    source_away_file: float | None,
    query_odds: tuple[float, float, float],
    historical_odds: tuple[float | None, float | None, float | None],
    full_time_score: str,
    half_time_score: str | None,
    parse_status: str,
    parse_warning: str | None,
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "source_file": source_file,
        "source_home_bucket": source_home_bucket,
        "source_away_file": source_away_file,
        "query_home_odds": query_odds[0],
        "query_draw_odds": query_odds[1],
        "query_away_odds": query_odds[2],
        "historical_home_odds": historical_odds[0],
        "historical_draw_odds": historical_odds[1],
        "historical_away_odds": historical_odds[2],
        "full_time_score": full_time_score,
        "half_time_score": half_time_score,
        "parse_status": parse_status,
        "parse_warning": parse_warning,
    }


def _dataset_directories(root: Path) -> list[tuple[Path, str]]:
    candidates = [root, *[path for path in root.iterdir() if path.is_dir()]]
    result: list[tuple[Path, str]] = []
    for path in candidates:
        name = path.name.lower()
        if "gebruikbare" in name or "usable" in name:
            result.append((path, "Usable Odds"))
        elif "odds" in name:
            result.append((path, "Odds"))
    return result


def _file_fingerprint(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(path.resolve()).encode("utf-8"))
    digest.update(str(stat.st_size).encode("ascii"))
    digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


def _cell_text(value: str) -> str:
    return " ".join(value.replace("\n", " ").strip().split())


def _row_odds(cells: list[str]) -> tuple[float, float, float] | None:
    if len(cells) < 3:
        return None
    values = [normalize_odds(cells[index]) for index in range(3)]
    if any(value is None for value in values):
        return None
    return values[0], values[1], values[2]  # type: ignore[return-value]


def _parse_score(score: str) -> tuple[int, int] | None:
    normalized = normalize_score(score)
    if not normalized:
        return None
    home, away = normalized.split("-")
    return int(home), int(away)


def _pct(value: int, sample_size: int) -> float:
    return round((value / sample_size) * 100, 1)
