from __future__ import annotations

import hashlib
import re
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import Database

SCORE_RE = re.compile(r"^(\d+)\s*[-:]\s*(\d+)\.?$")
NEIGHBOR_TOLERANCE = 0.05


def is_word_lock_file(path: str | Path) -> bool:
    return Path(path).name.startswith("~$")


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

    def import_roots(
        self,
        roots: list[Path],
        *,
        replace_active: bool = False,
        source_name: str = "Historical database folder",
        source_kind: str = "folder",
        content_hash: str | None = None,
    ) -> dict[str, object]:
        active_batch = self.database.active_historical_batch()
        if (
            not replace_active
            and active_batch
            and active_batch.get("source_kind") in {"zip", "legacy"}
        ):
            return {
                "files_seen": 0,
                "files_imported": 0,
                "files_skipped": 0,
                "records_imported": 0,
                "warnings": 0,
                "batch_id": active_batch["id"],
                "activated": False,
                "skipped": "active client database is already selected",
            }
        if (
            replace_active
            and content_hash
            and active_batch
            and active_batch.get("content_hash") == content_hash
        ):
            return {
                "files_seen": int(active_batch.get("files") or 0),
                "files_imported": 0,
                "files_skipped": 0,
                "records_imported": 0,
                "warnings": int(active_batch.get("warnings") or 0),
                "batch_id": active_batch["id"],
                "activated": False,
                "content_hash": content_hash,
            }

        files_seen = 0
        skipped_files: list[dict[str, str]] = []
        discovered_files: list[dict[str, object]] = []
        seen_logical_files: set[str] = set()
        for root in roots:
            if not root.exists():
                continue
            for dataset_dir, dataset in _dataset_directories(root):
                for path in sorted(dataset_dir.rglob("*.docx")):
                    if is_word_lock_file(path):
                        skipped_files.append(
                            {
                                "source_file": path.relative_to(dataset_dir).as_posix(),
                                "reason": "Microsoft Word temporary lock file",
                            }
                        )
                        continue
                    logical_source_file = f"{dataset}/{path.relative_to(dataset_dir).as_posix()}"
                    if logical_source_file in seen_logical_files:
                        continue
                    seen_logical_files.add(logical_source_file)
                    files_seen += 1
                    fingerprint = _file_fingerprint(path)
                    discovered_files.append(
                        {
                            "path": path,
                            "source_file": logical_source_file,
                            "dataset": dataset,
                            "fingerprint": fingerprint,
                        }
                    )

        if not discovered_files:
            return {
                "files_seen": files_seen,
                "files_imported": 0,
                "files_skipped": len(skipped_files),
                "records_imported": 0,
                "warnings": len(skipped_files),
                "batch_id": active_batch["id"] if active_batch else None,
                "activated": False,
                "skipped_files": skipped_files,
            }

        normalized_hash = content_hash or _dataset_fingerprint(discovered_files)
        if active_batch and active_batch.get("content_hash") == normalized_hash:
            return {
                "files_seen": files_seen,
                "files_imported": 0,
                "files_skipped": len(skipped_files),
                "records_imported": 0,
                "warnings": int(active_batch.get("warnings") or 0) + len(skipped_files),
                "batch_id": active_batch["id"],
                "activated": False,
                "content_hash": normalized_hash,
                "skipped_files": skipped_files,
            }

        parsed_files: list[dict[str, object]] = []
        for file in discovered_files:
            try:
                records, warnings = self._parse_file(
                    Path(file["path"]),
                    str(file["dataset"]),
                    str(file["source_file"]),
                )
            except Exception as exc:
                skipped_files.append(
                    {
                        "source_file": str(file["source_file"]),
                        "reason": f"Unreadable DOCX: {type(exc).__name__}: {exc}",
                    }
                )
                continue
            parsed_files.append(
                {
                    "source_file": file["source_file"],
                    "dataset": file["dataset"],
                    "fingerprint": file["fingerprint"],
                    "records": records,
                    "warnings": warnings,
                }
            )
        if not parsed_files:
            return {
                "files_seen": files_seen,
                "files_imported": 0,
                "files_skipped": len(skipped_files),
                "records_imported": 0,
                "warnings": len(skipped_files),
                "batch_id": active_batch["id"] if active_batch else None,
                "activated": False,
                "content_hash": normalized_hash,
                "skipped_files": skipped_files,
            }
        activation = self.database.replace_active_historical_dataset(
            source_name=source_name,
            source_kind=source_kind,
            content_hash=normalized_hash,
            files=parsed_files,
        )
        activated = bool(activation["activated"])
        records_imported = sum(len(file["records"]) for file in parsed_files) if activated else 0
        warning_count = sum(len(file["warnings"]) for file in parsed_files) + len(skipped_files)
        return {
            "files_seen": files_seen,
            "files_imported": len(parsed_files) if activated else 0,
            "files_skipped": len(skipped_files),
            "records_imported": records_imported,
            "warnings": warning_count,
            "batch_id": activation["batch_id"],
            "activated": activated,
            "content_hash": normalized_hash,
            "skipped_files": skipped_files,
        }

    def _parse_file(
        self,
        path: Path,
        dataset: str,
        logical_source_file: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        from .historical_parser import block_records, parse_historical_docx

        blocks, parse_warnings = parse_historical_docx(path, dataset, logical_source_file)
        records = [record for block in blocks for record in block_records(block)]
        return records, [warning.message() for warning in parse_warnings]


class HistoricalSignalAutoRefresh:
    def __init__(self, database: Database, importer: HistoricalDocxImporter, roots: list[Path]) -> None:
        self.database = database
        self.importer = importer
        self.roots = roots
        self._lock = Lock()

    def refresh(self, reason: str) -> dict[str, object]:
        with self._lock:
            import_result = self.importer.import_roots(self.roots)
            archive_result = self.database.archive_played_matches()
            if reason == "startup" and not import_result.get("activated"):
                recompute_result = {"matches_evaluated": 0, "signals": 0}
            else:
                recompute_result = self.database.recompute_historical_signals()
            result = {
                **import_result,
                **archive_result,
                **{f"recompute_{key}": value for key, value in recompute_result.items()},
            }
            self.database.log("info", "historical", "auto_refresh_completed", details={"reason": reason, **result})
            return result


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
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_fingerprint(files: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for file in sorted(files, key=lambda item: str(item["source_file"])):
        digest.update(str(file["source_file"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(file["fingerprint"]).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _parse_score(score: str) -> tuple[int, int] | None:
    normalized = normalize_score(score)
    if not normalized:
        return None
    home, away = normalized.split("-")
    return int(home), int(away)


def _pct(value: int, sample_size: int) -> float:
    return round((value / sample_size) * 100, 1)
