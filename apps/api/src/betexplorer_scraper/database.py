from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from threading import RLock

import duckdb

from .clock import utc_now
from .historical import ONE_DRAW_MIN_SAMPLE, compute_outcome_stats, normalize_odds, normalize_score
from .models import BookmakerOdds, CaptureType, DiscoveredMatch, OddsSnapshot, SnapshotQuality, TimingStatus
from .snapshot_metrics import final_snapshot_age_to_kickoff_seconds
from .utils import normalize_bookmaker_name


def _locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class Database:
    def __init__(self, path: Path, timezone_offset: str = "+0") -> None:
        self.path = path
        self.timezone_offset = timezone_offset
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.connection = duckdb.connect(str(path))
        self.migrate()

    @_locked
    def migrate(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                id VARCHAR PRIMARY KEY,
                betexplorer_match_id VARCHAR UNIQUE,
                sport VARCHAR,
                league VARCHAR,
                home_team VARCHAR,
                away_team VARCHAR,
                kickoff_time TIMESTAMP,
                status VARCHAR,
                timing_status VARCHAR,
                source_url VARCHAR,
                live_score VARCHAR,
                capture_phase VARCHAR,
                next_capture_at TIMESTAMP,
                last_capture_at TIMESTAMP,
                finalized_at TIMESTAMP,
                result_captured_at TIMESTAMP,
                result_checked_at TIMESTAMP,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        self._ensure_column("matches", "capture_phase", "VARCHAR")
        self._ensure_column("matches", "next_capture_at", "TIMESTAMP")
        self._ensure_column("matches", "last_capture_at", "TIMESTAMP")
        self._ensure_column("matches", "finalized_at", "TIMESTAMP")
        self._ensure_column("matches", "result_captured_at", "TIMESTAMP")
        self._ensure_column("matches", "result_checked_at", "TIMESTAMP")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_snapshots (
                id VARCHAR PRIMARY KEY,
                match_id VARCHAR,
                event_id VARCHAR,
                captured_at TIMESTAMP,
                market VARCHAR,
                capture_type VARCHAR,
                quality_status VARCHAR,
                is_final_candidate BOOLEAN,
                is_final BOOLEAN,
                source_page_type VARCHAR,
                raw_payload_path VARCHAR,
                required_bookmakers_json VARCHAR,
                created_at TIMESTAMP
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bookmaker_odds (
                id VARCHAR PRIMARY KEY,
                snapshot_id VARCHAR,
                bookmaker VARCHAR,
                normalized_bookmaker VARCHAR,
                bookmaker_id VARCHAR,
                betexplorer_bookmaker_id VARCHAR,
                home_odds DOUBLE,
                draw_odds DOUBLE,
                away_odds DOUBLE,
                is_available BOOLEAN,
                raw_row_text VARCHAR,
                raw_attributes_json VARCHAR,
                created_at TIMESTAMP
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scrape_attempts (
                id VARCHAR PRIMARY KEY,
                match_id VARCHAR,
                event_id VARCHAR,
                source_url VARCHAR,
                attempt_number INTEGER,
                status VARCHAR,
                error_message VARCHAR,
                required_found_json VARCHAR,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                created_at TIMESTAMP
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id VARCHAR PRIMARY KEY,
                timestamp TIMESTAMP,
                level VARCHAR,
                module VARCHAR,
                event VARCHAR,
                event_id VARCHAR,
                details_json VARCHAR
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_import_files (
                source_file VARCHAR PRIMARY KEY,
                dataset VARCHAR,
                fingerprint VARCHAR,
                records INTEGER,
                warnings INTEGER,
                imported_at TIMESTAMP
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_records (
                id VARCHAR PRIMARY KEY,
                dataset VARCHAR,
                source_file VARCHAR,
                source_home_bucket DOUBLE,
                source_away_file DOUBLE,
                query_home_odds DOUBLE,
                query_draw_odds DOUBLE,
                query_away_odds DOUBLE,
                historical_home_odds DOUBLE,
                historical_draw_odds DOUBLE,
                historical_away_odds DOUBLE,
                full_time_score VARCHAR,
                half_time_score VARCHAR,
                parse_status VARCHAR,
                parse_warning VARCHAR,
                imported_at TIMESTAMP
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_signals (
                id VARCHAR PRIMARY KEY,
                match_id VARCHAR,
                event_id VARCHAR,
                league VARCHAR,
                home_team VARCHAR,
                away_team VARCHAR,
                kickoff_time TIMESTAMP,
                capture_phase VARCHAR,
                bookmaker VARCHAR,
                normalized_bookmaker VARCHAR,
                dataset VARCHAR,
                signal_type VARCHAR,
                current_home_odds DOUBLE,
                current_draw_odds DOUBLE,
                current_away_odds DOUBLE,
                matched_odds_home DOUBLE,
                matched_odds_draw DOUBLE,
                matched_odds_away DOUBLE,
                odds_distance_home DOUBLE,
                odds_distance_draw DOUBLE,
                odds_distance_away DOUBLE,
                similarity_score DOUBLE,
                match_explanation VARCHAR,
                signal_rank INTEGER,
                sample_size INTEGER,
                home_win_pct DOUBLE,
                draw_pct DOUBLE,
                away_win_pct DOUBLE,
                over_0_5_pct DOUBLE,
                over_1_5_pct DOUBLE,
                over_2_5_pct DOUBLE,
                btts_pct DOUBLE,
                double_chance_1x_pct DOUBLE,
                double_chance_x2_pct DOUBLE,
                double_chance_12_pct DOUBLE,
                historical_scores_json VARCHAR,
                source_files_json VARCHAR,
                created_at TIMESTAMP
            )
            """
        )
        self._ensure_column("historical_signals", "matched_odds_home", "DOUBLE")
        self._ensure_column("historical_signals", "matched_odds_draw", "DOUBLE")
        self._ensure_column("historical_signals", "matched_odds_away", "DOUBLE")
        self._ensure_column("historical_signals", "odds_distance_home", "DOUBLE")
        self._ensure_column("historical_signals", "odds_distance_draw", "DOUBLE")
        self._ensure_column("historical_signals", "odds_distance_away", "DOUBLE")
        self._ensure_column("historical_signals", "similarity_score", "DOUBLE")
        self._ensure_column("historical_signals", "match_explanation", "VARCHAR")
        self._ensure_column("historical_signals", "signal_rank", "INTEGER")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS played_match_archive (
                match_id VARCHAR PRIMARY KEY,
                event_id VARCHAR,
                league VARCHAR,
                home_team VARCHAR,
                away_team VARCHAR,
                kickoff_time TIMESTAMP,
                finalized_at TIMESTAMP,
                result_captured_at TIMESTAMP,
                full_time_score VARCHAR,
                bwin_home_odds DOUBLE,
                bwin_draw_odds DOUBLE,
                bwin_away_odds DOUBLE,
                unibet_home_odds DOUBLE,
                unibet_draw_odds DOUBLE,
                unibet_away_odds DOUBLE,
                archived_at TIMESTAMP
            )
            """
        )

    @_locked
    def _ensure_column(self, table: str, column: str, data_type: str) -> None:
        exists = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = ? AND column_name = ?
            """,
            [table, column],
        ).fetchone()[0]
        if not exists:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {data_type}")

    @_locked
    def upsert_match(self, match: DiscoveredMatch) -> str:
        existing = self.connection.execute(
            "SELECT id FROM matches WHERE betexplorer_match_id = ?",
            [match.event_id],
        ).fetchone()
        now = utc_now()
        if existing:
            match_id = existing[0]
            self.connection.execute(
                """
                UPDATE matches
                SET league = ?, home_team = ?, away_team = ?, kickoff_time = ?, status = ?,
                    timing_status = ?, source_url = ?, live_score = ?, updated_at = ?
                WHERE id = ?
                """,
                [
                    match.league,
                    match.home_team,
                    match.away_team,
                    match.kickoff_time,
                    match.status,
                    match.timing_status.value,
                    match.source_url,
                    match.live_score,
                    now,
                    match_id,
                ],
            )
            return match_id
        match_id = str(uuid.uuid4())
        self.connection.execute(
            """
            INSERT INTO matches (
                id, betexplorer_match_id, sport, league, home_team, away_team, kickoff_time,
                status, timing_status, source_url, live_score, capture_phase, next_capture_at,
                last_capture_at, finalized_at, result_captured_at, result_checked_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                match_id,
                match.event_id,
                "football",
                match.league,
                match.home_team,
                match.away_team,
                match.kickoff_time,
                match.status,
                match.timing_status.value,
                match.source_url,
                match.live_score,
                "DISCOVERED",
                None,
                None,
                None,
                None,
                None,
                now,
                now,
            ],
        )
        return match_id

    @_locked
    def mark_result_captured(self, match_id: str, score: str | None, captured_at: datetime) -> bool:
        row = self.connection.execute("SELECT result_captured_at FROM matches WHERE id = ?", [match_id]).fetchone()
        if not row or row[0] is not None:
            return False
        self.connection.execute(
            """
            UPDATE matches
            SET status = 'finished',
                timing_status = ?,
                live_score = COALESCE(?, live_score),
                result_captured_at = ?,
                updated_at = ?
            WHERE id = ? AND result_captured_at IS NULL
            """,
            [TimingStatus.FINISHED.value, score, captured_at, utc_now(), match_id],
        )
        return True

    @_locked
    def mark_result_checked(self, match_id: str, checked_at: datetime) -> None:
        self.connection.execute(
            "UPDATE matches SET result_checked_at = ?, updated_at = ? WHERE id = ?",
            [checked_at, utc_now(), match_id],
        )

    @_locked
    def update_match_kickoff_time(self, match_id: str, kickoff_time: datetime) -> None:
        self.connection.execute(
            "UPDATE matches SET kickoff_time = ?, updated_at = ? WHERE id = ?",
            [kickoff_time, utc_now(), match_id],
        )

    @_locked
    def list_result_backfill_candidates(
        self,
        now: datetime,
        lookback_hours: int,
        finish_grace_minutes: int,
        retry_seconds: int,
        limit: int,
    ) -> list[tuple[str, DiscoveredMatch]]:
        cutoff = now - timedelta(hours=lookback_hours)
        finish_cutoff = now - timedelta(minutes=finish_grace_minutes)
        retry_cutoff = now - timedelta(seconds=retry_seconds)
        rows = self.connection.execute(
            """
            SELECT id, betexplorer_match_id, source_url, league, home_team, away_team, kickoff_time,
                   timing_status, status, live_score, capture_phase, finalized_at, result_captured_at
            FROM matches
            WHERE result_captured_at IS NULL
              AND kickoff_time IS NOT NULL
              AND kickoff_time >= ?
              AND kickoff_time <= ?
              AND source_url IS NOT NULL
              AND (result_checked_at IS NULL OR result_checked_at <= ?)
            ORDER BY kickoff_time ASC
            LIMIT ?
            """,
            [cutoff, finish_cutoff, retry_cutoff, limit],
        ).fetchall()
        candidates: list[tuple[str, DiscoveredMatch]] = []
        for row in rows:
            candidates.append(
                (
                    row[0],
                    DiscoveredMatch(
                        event_id=row[1],
                        source_url=row[2],
                        league=row[3],
                        home_team=row[4],
                        away_team=row[5],
                        kickoff_time=row[6],
                        timing_status=TimingStatus(row[7] or TimingStatus.UNKNOWN.value),
                        status=row[8] or "scheduled",
                        live_score=row[9],
                        capture_phase=row[10],
                        finalized_at=row[11],
                        result_captured_at=row[12],
                    ),
                )
            )
        return candidates

    @_locked
    def list_empty_finalized_odds_backfill_candidates(
        self,
        now: datetime,
        lookback_hours: int,
        limit: int,
    ) -> list[tuple[str, DiscoveredMatch]]:
        cutoff = now - timedelta(hours=lookback_hours)
        rows = self.connection.execute(
            """
            SELECT m.id, m.betexplorer_match_id, m.source_url, m.league, m.home_team, m.away_team, m.kickoff_time,
                   m.timing_status, m.status, m.live_score, m.capture_phase, m.finalized_at, m.result_captured_at
            FROM matches m
            WHERE m.finalized_at IS NOT NULL
              AND m.kickoff_time IS NOT NULL
              AND m.kickoff_time >= ?
              AND m.source_url IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM odds_snapshots s WHERE s.match_id = m.id)
              AND NOT EXISTS (SELECT 1 FROM scrape_attempts a WHERE a.match_id = m.id)
            ORDER BY m.kickoff_time DESC
            LIMIT ?
            """,
            [cutoff, limit],
        ).fetchall()
        candidates: list[tuple[str, DiscoveredMatch]] = []
        for row in rows:
            candidates.append(
                (
                    row[0],
                    DiscoveredMatch(
                        event_id=row[1],
                        source_url=row[2],
                        league=row[3],
                        home_team=row[4],
                        away_team=row[5],
                        kickoff_time=row[6],
                        timing_status=TimingStatus(row[7] or TimingStatus.UNKNOWN.value),
                        status=row[8] or "scheduled",
                        live_score=row[9],
                        capture_phase=row[10],
                        finalized_at=row[11],
                        result_captured_at=row[12],
                    ),
                )
            )
        return candidates

    @_locked
    def get_match_schedule(self, match_id: str) -> dict[str, datetime | str | None]:
        row = self.connection.execute(
            """
            SELECT capture_phase, next_capture_at, last_capture_at, finalized_at, result_captured_at
            FROM matches WHERE id = ?
            """,
            [match_id],
        ).fetchone()
        if not row:
            return {
                "capture_phase": None,
                "next_capture_at": None,
                "last_capture_at": None,
                "finalized_at": None,
                "result_captured_at": None,
            }
        return {
            "capture_phase": row[0],
            "next_capture_at": row[1],
            "last_capture_at": row[2],
            "finalized_at": row[3],
            "result_captured_at": row[4],
        }

    @_locked
    def list_due_scheduled_matches(self, now: datetime) -> list[tuple[str, DiscoveredMatch, dict[str, datetime | str | None]]]:
        rows = self.connection.execute(
            """
            SELECT id, betexplorer_match_id, source_url, league, home_team, away_team, kickoff_time,
                   timing_status, status, live_score, capture_phase, next_capture_at, last_capture_at, finalized_at, result_captured_at
            FROM matches
            WHERE finalized_at IS NULL
              AND next_capture_at IS NOT NULL
              AND next_capture_at <= ?
            """,
            [now],
        ).fetchall()
        items: list[tuple[str, DiscoveredMatch, dict[str, datetime | str | None]]] = []
        for row in rows:
            match = DiscoveredMatch(
                event_id=row[1],
                source_url=row[2],
                league=row[3],
                home_team=row[4],
                away_team=row[5],
                kickoff_time=row[6],
                timing_status=TimingStatus(row[7] or TimingStatus.UNKNOWN.value),
                status=row[8] or "scheduled",
                live_score=row[9],
                capture_phase=row[10],
                finalized_at=row[13],
                result_captured_at=row[14],
            )
            items.append(
                (
                    row[0],
                    match,
                    {
                        "capture_phase": row[10],
                        "next_capture_at": row[11],
                        "last_capture_at": row[12],
                        "finalized_at": row[13],
                        "result_captured_at": row[14],
                    },
                )
            )
        return items

    @_locked
    def update_match_schedule(
        self,
        match_id: str,
        capture_phase: str,
        next_capture_at: datetime | None,
        finalized_at: datetime | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE matches
            SET capture_phase = ?, next_capture_at = ?, finalized_at = COALESCE(?, finalized_at), updated_at = ?
            WHERE id = ?
            """,
            [capture_phase, next_capture_at, finalized_at, utc_now(), match_id],
        )

    @_locked
    def mark_match_captured(
        self,
        match_id: str,
        captured_at: datetime,
        next_capture_at: datetime | None,
        capture_phase: str,
        finalized_at: datetime | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE matches
            SET last_capture_at = ?, next_capture_at = ?, capture_phase = ?,
                finalized_at = COALESCE(?, finalized_at), updated_at = ?
            WHERE id = ?
            """,
            [captured_at, next_capture_at, capture_phase, finalized_at, utc_now(), match_id],
        )

    @_locked
    def save_snapshot(self, match_id: str, snapshot: OddsSnapshot) -> str:
        snapshot_id = str(uuid.uuid4())
        now = utc_now()
        should_be_final = self._should_promote_snapshot(match_id, snapshot)
        if should_be_final:
            self.connection.execute("UPDATE odds_snapshots SET is_final = FALSE WHERE match_id = ? AND market = ?", [match_id, snapshot.market])
        self.connection.execute(
            """
            INSERT INTO odds_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                snapshot_id,
                match_id,
                snapshot.event_id,
                snapshot.captured_at,
                snapshot.market,
                snapshot.capture_type.value,
                snapshot.quality_status.value,
                True,
                should_be_final,
                snapshot.source_page_type,
                snapshot.raw_payload_path,
                json.dumps(snapshot.required_bookmakers),
                now,
            ],
        )
        for odds in snapshot.bookmaker_odds:
            self.save_bookmaker_odds(snapshot_id, odds, now)
        return snapshot_id

    def _should_promote_snapshot(self, match_id: str, snapshot: OddsSnapshot) -> bool:
        current = self.connection.execute(
            """
            SELECT id, quality_status, required_bookmakers_json
            FROM odds_snapshots
            WHERE match_id = ? AND market = ? AND is_final = TRUE
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            [match_id, snapshot.market],
        ).fetchone()
        if not current:
            return True
        current_required = _required_bookmaker_names(current[2])
        if not current_required:
            return True
        placeholders = ", ".join(["?"] * len(current_required))
        current_score = self.connection.execute(
            f"""
            SELECT COUNT(DISTINCT normalized_bookmaker)
            FROM bookmaker_odds
            WHERE snapshot_id = ?
              AND is_available = TRUE
              AND normalized_bookmaker IN ({placeholders})
            """,
            [current[0], *current_required],
        ).fetchone()[0]
        new_score = _required_bookmaker_score(snapshot.bookmaker_odds, snapshot.required_bookmakers)
        return new_score >= int(current_score or 0)

    @_locked
    def repair_final_snapshots(self, required_bookmakers: list[str] | None = None) -> dict[str, int]:
        required = [normalize_bookmaker_name(item) for item in (required_bookmakers or ["Bwin", "Unibet"])]
        required = [item for item in required if item]
        if not required:
            return {"groups_checked": 0, "groups_repaired": 0}
        placeholders = ", ".join(["?"] * len(required))
        best_rows = self.connection.execute(
            f"""
            WITH scored AS (
                SELECT
                    s.id,
                    s.match_id,
                    s.market,
                    s.captured_at,
                    COUNT(DISTINCT CASE
                        WHEN o.is_available = TRUE AND o.normalized_bookmaker IN ({placeholders})
                        THEN o.normalized_bookmaker
                    END) AS required_score
                FROM odds_snapshots s
                LEFT JOIN bookmaker_odds o ON o.snapshot_id = s.id
                GROUP BY s.id, s.match_id, s.market, s.captured_at
            ),
            ranked AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY match_id, market
                           ORDER BY required_score DESC, captured_at DESC, id DESC
                       ) AS rank
                FROM scored
            )
            SELECT id, match_id, market
            FROM ranked
            WHERE rank = 1
            """,
            required,
        ).fetchall()
        if not best_rows:
            return {"groups_checked": 0, "groups_repaired": 0}
        current_rows = self.connection.execute(
            """
            SELECT match_id, market, id
            FROM odds_snapshots
            WHERE is_final = TRUE
            """
        ).fetchall()
        current_by_group = {(str(row[0]), str(row[1])): str(row[2]) for row in current_rows}
        best_by_group = {(str(row[1]), str(row[2])): str(row[0]) for row in best_rows}
        repaired = sum(1 for group, snapshot_id in best_by_group.items() if current_by_group.get(group) != snapshot_id)
        self.connection.execute("UPDATE odds_snapshots SET is_final = FALSE")
        best_ids = [str(row[0]) for row in best_rows]
        for chunk_start in range(0, len(best_ids), 500):
            chunk = best_ids[chunk_start : chunk_start + 500]
            chunk_placeholders = ", ".join(["?"] * len(chunk))
            self.connection.execute(
                f"UPDATE odds_snapshots SET is_final = TRUE WHERE id IN ({chunk_placeholders})",
                chunk,
            )
        return {"groups_checked": len(best_rows), "groups_repaired": repaired}

    @_locked
    def save_bookmaker_odds(self, snapshot_id: str, odds: BookmakerOdds, created_at: datetime) -> None:
        self.connection.execute(
            """
            INSERT INTO bookmaker_odds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(uuid.uuid4()),
                snapshot_id,
                odds.bookmaker,
                odds.normalized_bookmaker,
                odds.bookmaker_id,
                odds.betexplorer_bookmaker_id,
                odds.home_odds,
                odds.draw_odds,
                odds.away_odds,
                odds.is_available,
                odds.raw_row_text,
                json.dumps(odds.raw_attributes, ensure_ascii=False),
                created_at,
            ],
        )

    @_locked
    def save_attempt(
        self,
        match_id: str,
        event_id: str,
        source_url: str,
        attempt_number: int,
        status: str,
        error_message: str | None,
        required_found: dict[str, bool],
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO scrape_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(uuid.uuid4()),
                match_id,
                event_id,
                source_url,
                attempt_number,
                status,
                error_message,
                json.dumps(required_found),
                started_at,
                finished_at,
                utc_now(),
            ],
        )

    @_locked
    def log(self, level: str, module: str, event: str, event_id: str | None = None, details: dict | None = None) -> None:
        self.connection.execute(
            "INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?, ?)",
            [str(uuid.uuid4()), utc_now(), level, module, event, event_id, json.dumps(details or {})],
        )

    @_locked
    def historical_file_is_current(self, source_file: str, fingerprint: str) -> bool:
        row = self.connection.execute(
            "SELECT fingerprint FROM historical_import_files WHERE source_file = ?",
            [source_file],
        ).fetchone()
        return bool(row and row[0] == fingerprint)

    @_locked
    def replace_historical_records(self, source_file: str, records: list[dict[str, object]]) -> None:
        now = utc_now()
        self.connection.execute("DELETE FROM historical_records WHERE source_file = ?", [source_file])
        for row in records:
            self.connection.execute(
                """
                INSERT INTO historical_records (
                    id, dataset, source_file, source_home_bucket, source_away_file,
                    query_home_odds, query_draw_odds, query_away_odds,
                    historical_home_odds, historical_draw_odds, historical_away_odds,
                    full_time_score, half_time_score, parse_status, parse_warning, imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()),
                    row["dataset"],
                    row.get("source_file", source_file),
                    row.get("source_home_bucket"),
                    row.get("source_away_file"),
                    row["query_home_odds"],
                    row["query_draw_odds"],
                    row["query_away_odds"],
                    row.get("historical_home_odds"),
                    row.get("historical_draw_odds"),
                    row.get("historical_away_odds"),
                    row["full_time_score"],
                    row.get("half_time_score"),
                    row.get("parse_status", "parsed"),
                    row.get("parse_warning"),
                    now,
                ],
            )

    @_locked
    def record_historical_import_file(
        self,
        source_file: str,
        dataset: str,
        fingerprint: str,
        records: int,
        warnings: int,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO historical_import_files
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_file) DO UPDATE SET
                dataset = excluded.dataset,
                fingerprint = excluded.fingerprint,
                records = excluded.records,
                warnings = excluded.warnings,
                imported_at = excluded.imported_at
            """,
            [source_file, dataset, fingerprint, records, warnings, utc_now()],
        )

    @_locked
    def list_historical_records(self, limit: int = 500) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT dataset, source_file, source_home_bucket, source_away_file,
                   query_home_odds, query_draw_odds, query_away_odds,
                   historical_home_odds, historical_draw_odds, historical_away_odds,
                   full_time_score, half_time_score, parse_status, parse_warning
            FROM historical_records
            ORDER BY dataset, source_file, CASE parse_status WHEN 'parsed' THEN 0 ELSE 1 END, full_time_score, id
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        columns = [col[0] for col in self.connection.description]
        return [self._serialize(dict(zip(columns, row))) for row in rows]

    @_locked
    def historical_import_status(self) -> dict[str, object]:
        records = self.connection.execute("SELECT COUNT(*) FROM historical_records").fetchone()[0]
        files = self.connection.execute("SELECT COUNT(*) FROM historical_import_files").fetchone()[0]
        warnings = self.connection.execute(
            "SELECT COALESCE(SUM(warnings), 0) FROM historical_import_files"
        ).fetchone()[0]
        datasets = [
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT dataset FROM historical_records ORDER BY dataset"
            ).fetchall()
            if row[0]
        ]
        last_import = self.connection.execute("SELECT MAX(imported_at) FROM historical_import_files").fetchone()[0]
        return {
            "records": records,
            "files": files,
            "warnings": warnings,
            "datasets": datasets,
            "last_import": last_import.isoformat() if last_import else None,
        }

    @_locked
    def recompute_historical_signals(self) -> dict[str, int]:
        self.connection.execute("DELETE FROM historical_signals")
        candidates = self._signal_candidates()
        complete_records = self._fetch_complete_historical_records()
        record_index = _build_complete_record_index(complete_records)
        inserted = 0
        for candidate in candidates:
            for signal_type, records in self._historical_record_groups_for_candidate(candidate, record_index):
                if not records:
                    continue
                inserted += self._insert_historical_signal(candidate, signal_type, records)
        return {"matches_evaluated": len({row["match_id"] for row in candidates}), "signals": inserted}

    def _signal_candidates(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT m.id AS match_id, m.betexplorer_match_id AS event_id, m.league, m.home_team, m.away_team,
                   m.kickoff_time, m.capture_phase, m.finalized_at,
                   MAX(CASE WHEN o.normalized_bookmaker = 'bwin' THEN o.bookmaker END) AS bwin_bookmaker,
                   MAX(CASE WHEN o.normalized_bookmaker = 'bwin' THEN o.home_odds END) AS bwin_home_odds,
                   MAX(CASE WHEN o.normalized_bookmaker = 'bwin' THEN o.draw_odds END) AS bwin_draw_odds,
                   MAX(CASE WHEN o.normalized_bookmaker = 'bwin' THEN o.away_odds END) AS bwin_away_odds,
                   MAX(CASE WHEN o.normalized_bookmaker = 'unibet' THEN o.bookmaker END) AS unibet_bookmaker,
                   MAX(CASE WHEN o.normalized_bookmaker = 'unibet' THEN o.home_odds END) AS unibet_home_odds,
                   MAX(CASE WHEN o.normalized_bookmaker = 'unibet' THEN o.draw_odds END) AS unibet_draw_odds,
                   MAX(CASE WHEN o.normalized_bookmaker = 'unibet' THEN o.away_odds END) AS unibet_away_odds
            FROM matches m
            JOIN odds_snapshots s ON s.match_id = m.id AND s.is_final = TRUE AND lower(s.market) = '1x2'
            JOIN bookmaker_odds o ON o.snapshot_id = s.id
            WHERE o.normalized_bookmaker IN ('bwin', 'unibet')
              AND o.home_odds IS NOT NULL
              AND o.draw_odds IS NOT NULL
              AND o.away_odds IS NOT NULL
            GROUP BY m.id, m.betexplorer_match_id, m.league, m.home_team, m.away_team,
                     m.kickoff_time, m.capture_phase, m.finalized_at
            HAVING bwin_home_odds IS NOT NULL
               AND bwin_draw_odds IS NOT NULL
               AND bwin_away_odds IS NOT NULL
               AND unibet_home_odds IS NOT NULL
               AND unibet_draw_odds IS NOT NULL
               AND unibet_away_odds IS NOT NULL
            ORDER BY m.kickoff_time NULLS LAST, m.home_team
            """
        ).fetchall()
        columns = [col[0] for col in self.connection.description]
        return [dict(zip(columns, row)) for row in rows]

    def _historical_record_groups_for_candidate(
        self,
        candidate: dict[str, object],
        record_index: dict[str, dict[tuple[object, ...], list[dict[str, object]]]],
    ) -> list[tuple[str, list[dict[str, object]]]]:
        if not _candidate_has_complete_required_odds(candidate):
            return []
        dataset_order = ["Odds", "Usable Odds", "Played archive"]

        exact_records = _matching_indexed_records(candidate, record_index, "exact_odds")
        for dataset in dataset_order:
            dataset_records = [record for record in exact_records if record["dataset"] == dataset]
            if dataset_records:
                return [("exact_odds", dataset_records)]

        one_draw_records = _matching_indexed_records(candidate, record_index, "one_draw")
        for dataset in dataset_order:
            dataset_records = [record for record in one_draw_records if record["dataset"] == dataset]
            if len(dataset_records) >= ONE_DRAW_MIN_SAMPLE:
                return [("one_draw", dataset_records)]
        return []

    def _fetch_complete_historical_records(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            WITH historical_pool AS (
                SELECT dataset, source_file,
                       query_home_odds AS bwin_home_odds,
                       query_draw_odds AS bwin_draw_odds,
                       query_away_odds AS bwin_away_odds,
                       historical_home_odds AS unibet_home_odds,
                       historical_draw_odds AS unibet_draw_odds,
                       historical_away_odds AS unibet_away_odds,
                       full_time_score,
                       TRUE AS allow_reverse
                FROM historical_records
                WHERE full_time_score IS NOT NULL
                  AND query_home_odds IS NOT NULL
                  AND query_draw_odds IS NOT NULL
                  AND query_away_odds IS NOT NULL
                  AND historical_home_odds IS NOT NULL
                  AND historical_draw_odds IS NOT NULL
                  AND historical_away_odds IS NOT NULL
                UNION ALL
                SELECT 'Played archive' AS dataset, event_id AS source_file,
                       bwin_home_odds AS query_home_odds,
                       bwin_draw_odds AS query_draw_odds,
                       bwin_away_odds AS query_away_odds,
                       unibet_home_odds AS query_home_odds,
                       unibet_draw_odds AS query_draw_odds,
                       unibet_away_odds AS query_away_odds,
                       full_time_score,
                       FALSE AS allow_reverse
                FROM played_match_archive
                WHERE full_time_score IS NOT NULL
                  AND unibet_home_odds IS NOT NULL
                  AND unibet_draw_odds IS NOT NULL
                  AND unibet_away_odds IS NOT NULL
                  AND bwin_home_odds IS NOT NULL
                  AND bwin_draw_odds IS NOT NULL
                  AND bwin_away_odds IS NOT NULL
            )
            SELECT dataset, source_file,
                   bwin_home_odds, bwin_draw_odds, bwin_away_odds,
                   unibet_home_odds, unibet_draw_odds, unibet_away_odds,
                   full_time_score, allow_reverse
            FROM historical_pool
            ORDER BY dataset, source_file, bwin_home_odds, bwin_draw_odds, bwin_away_odds
            """
        ).fetchall()
        columns = [
            "dataset",
            "source_file",
            "bwin_home_odds",
            "bwin_draw_odds",
            "bwin_away_odds",
            "unibet_home_odds",
            "unibet_draw_odds",
            "unibet_away_odds",
            "full_time_score",
            "allow_reverse",
        ]
        return [
            dict(zip(columns, row))
            for row in rows
        ]

    def _insert_historical_signal(
        self,
        candidate: dict[str, object],
        signal_type: str,
        records: list[dict[str, object]],
    ) -> int:
        grouped: dict[str, list[dict[str, object]]] = {}
        for record in records:
            grouped.setdefault(str(record["dataset"]), []).append(record)
        inserted = 0
        for dataset, dataset_records in grouped.items():
            scores = [str(record["full_time_score"]) for record in dataset_records]
            stats = compute_outcome_stats(scores)
            explanation = _signal_explanation(signal_type)
            signal_rank = _signal_rank(signal_type)
            source_files = sorted({str(record["source_file"]) for record in dataset_records})[:20]
            historical_scores = scores[:10]
            for normalized_bookmaker, bookmaker in [("bwin", "Bwin"), ("unibet", "Unibet")]:
                similarity = _signal_similarity(signal_type)
                matched_home = _average_odds(dataset_records, f"{normalized_bookmaker}_home_odds")
                matched_draw = _average_odds(dataset_records, f"{normalized_bookmaker}_draw_odds")
                matched_away = _average_odds(dataset_records, f"{normalized_bookmaker}_away_odds")
                current_home = normalize_odds(candidate[f"{normalized_bookmaker}_home_odds"])
                current_draw = normalize_odds(candidate[f"{normalized_bookmaker}_draw_odds"])
                current_away = normalize_odds(candidate[f"{normalized_bookmaker}_away_odds"])
                distance_home = _odds_distance(current_home, matched_home)
                distance_draw = _odds_distance(current_draw, matched_draw)
                distance_away = _odds_distance(current_away, matched_away)
                self.connection.execute(
                    """
                    INSERT INTO historical_signals (
                        id, match_id, event_id, league, home_team, away_team, kickoff_time, capture_phase,
                        bookmaker, normalized_bookmaker, dataset, signal_type,
                        current_home_odds, current_draw_odds, current_away_odds,
                        matched_odds_home, matched_odds_draw, matched_odds_away,
                        odds_distance_home, odds_distance_draw, odds_distance_away,
                        similarity_score, match_explanation, signal_rank,
                        sample_size, home_win_pct, draw_pct, away_win_pct,
                        over_0_5_pct, over_1_5_pct, over_2_5_pct, btts_pct,
                        double_chance_1x_pct, double_chance_x2_pct, double_chance_12_pct,
                        historical_scores_json, source_files_json, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        str(uuid.uuid4()),
                        candidate["match_id"],
                        candidate["event_id"],
                        candidate["league"],
                        candidate["home_team"],
                        candidate["away_team"],
                        candidate["kickoff_time"],
                        self._effective_capture_phase(candidate.get("capture_phase"), candidate.get("finalized_at")),
                        bookmaker,
                        normalized_bookmaker,
                        dataset,
                        signal_type,
                        current_home,
                        current_draw,
                        current_away,
                        matched_home,
                        matched_draw,
                        matched_away,
                        distance_home,
                        distance_draw,
                        distance_away,
                        similarity,
                        explanation,
                        signal_rank,
                        stats["sample_size"],
                        stats["home_win_pct"],
                        stats["draw_pct"],
                        stats["away_win_pct"],
                        stats["over_0_5_pct"],
                        stats["over_1_5_pct"],
                        stats["over_2_5_pct"],
                        stats["btts_pct"],
                        stats["double_chance_1x_pct"],
                        stats["double_chance_x2_pct"],
                        stats["double_chance_12_pct"],
                        json.dumps(historical_scores),
                        json.dumps(source_files),
                        utc_now(),
                    ],
                )
                inserted += 1
        return inserted

    @_locked
    def list_signals(
        self,
        match_id: str | None = None,
        dataset: str | None = None,
        bookmaker: str | None = None,
        signal_type: str | None = None,
        min_sample: int = 1,
        from_date: str | None = None,
        match_date: str | None = None,
        actionable_after: datetime | None = None,
        sort_mode: str = "quality",
    ) -> list[dict[str, object]]:
        clauses = ["sample_size >= ?"]
        params: list[object] = [min_sample]
        if match_id:
            clauses.append("match_id = ?")
            params.append(match_id)
        if dataset and dataset != "all":
            clauses.append("dataset = ?")
            params.append(dataset)
        if bookmaker and bookmaker != "all":
            clauses.append("normalized_bookmaker = ?")
            params.append(bookmaker.lower())
        if signal_type and signal_type != "all":
            clauses.append("signal_type = ?")
            params.append(signal_type)
        if from_date:
            clauses.append("CAST(kickoff_time AS DATE) >= ?")
            params.append(from_date)
        if match_date:
            clauses.append("CAST(kickoff_time AS DATE) = ?")
            params.append(match_date)
        if actionable_after:
            clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM matches m
                    WHERE m.id = historical_signals.match_id
                      AND m.finalized_at IS NULL
                      AND m.result_captured_at IS NULL
                      AND (m.kickoff_time IS NULL OR m.kickoff_time >= ?)
                )
                """
            )
            params.append(actionable_after)
        order_sql = _signal_order_sql(sort_mode)
        rows = self.connection.execute(
            f"""
            SELECT *
            FROM historical_signals
            WHERE {' AND '.join(clauses)}
            ORDER BY {order_sql}
            LIMIT 500
            """,
            params,
        ).fetchall()
        columns = [col[0] for col in self.connection.description]
        signals = [self._serialize(dict(zip(columns, row))) for row in rows]
        for signal in signals:
            signal["historical_scores"] = json.loads(str(signal.pop("historical_scores_json") or "[]"))
            signal["source_files"] = json.loads(str(signal.pop("source_files_json") or "[]"))
        return signals

    @_locked
    def list_signal_days(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT CAST(kickoff_time AS DATE) AS signal_date,
                   COUNT(DISTINCT match_id) AS matches,
                   COUNT(*) AS signals
            FROM historical_signals
            WHERE kickoff_time IS NOT NULL
            GROUP BY signal_date
            ORDER BY signal_date
            """
        ).fetchall()
        return [
            {
                "date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "matches": row[1],
                "signals": row[2],
            }
            for row in rows
        ]

    @_locked
    def archive_played_matches(self) -> dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT m.id, m.betexplorer_match_id, m.league, m.home_team, m.away_team,
                   m.kickoff_time, m.finalized_at, m.result_captured_at, m.live_score,
                   o.normalized_bookmaker, o.home_odds, o.draw_odds, o.away_odds
            FROM matches m
            JOIN odds_snapshots s ON s.match_id = m.id AND s.is_final = TRUE AND lower(s.market) = '1x2'
            JOIN bookmaker_odds o ON o.snapshot_id = s.id AND o.normalized_bookmaker IN ('bwin', 'unibet')
            WHERE m.result_captured_at IS NOT NULL
            ORDER BY m.id, o.normalized_bookmaker
            """
        ).fetchall()
        grouped: dict[str, dict[str, object]] = {}
        for row in rows:
            item = grouped.setdefault(
                row[0],
                {
                    "match_id": row[0],
                    "event_id": row[1],
                    "league": row[2],
                    "home_team": row[3],
                    "away_team": row[4],
                    "kickoff_time": row[5],
                    "finalized_at": row[6],
                    "result_captured_at": row[7],
                    "full_time_score": normalize_score(str(row[8]).replace(":", "-") if row[8] else None),
                    "bwin": None,
                    "unibet": None,
                },
            )
            item[str(row[9])] = (row[10], row[11], row[12])
        archived = 0
        for item in grouped.values():
            if not item.get("full_time_score") or not item.get("bwin") or not item.get("unibet"):
                continue
            bwin = item["bwin"]
            unibet = item["unibet"]
            self.connection.execute(
                """
                INSERT INTO played_match_archive VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (match_id) DO UPDATE SET
                    finalized_at = excluded.finalized_at,
                    result_captured_at = excluded.result_captured_at,
                    full_time_score = excluded.full_time_score,
                    bwin_home_odds = excluded.bwin_home_odds,
                    bwin_draw_odds = excluded.bwin_draw_odds,
                    bwin_away_odds = excluded.bwin_away_odds,
                    unibet_home_odds = excluded.unibet_home_odds,
                    unibet_draw_odds = excluded.unibet_draw_odds,
                    unibet_away_odds = excluded.unibet_away_odds,
                    archived_at = excluded.archived_at
                """,
                [
                    item["match_id"],
                    item["event_id"],
                    item["league"],
                    item["home_team"],
                    item["away_team"],
                    item["kickoff_time"],
                    item["finalized_at"],
                    item["result_captured_at"],
                    item["full_time_score"],
                    bwin[0],  # type: ignore[index]
                    bwin[1],  # type: ignore[index]
                    bwin[2],  # type: ignore[index]
                    unibet[0],  # type: ignore[index]
                    unibet[1],  # type: ignore[index]
                    unibet[2],  # type: ignore[index]
                    utc_now(),
                ],
            )
            archived += 1
        return {"archived": archived}

    @_locked
    def list_played_match_archive(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            "SELECT * FROM played_match_archive ORDER BY result_captured_at DESC LIMIT 500"
        ).fetchall()
        columns = [col[0] for col in self.connection.description]
        return [self._serialize(dict(zip(columns, row))) for row in rows]

    @_locked
    def status(self, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now()
        match_count = self.connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        snapshot_attempts = self.connection.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0]
        final_snapshot_count = self.connection.execute("SELECT COUNT(*) FROM odds_snapshots WHERE is_final = TRUE").fetchone()[0]
        bookmaker_row_attempts = self.connection.execute("SELECT COUNT(*) FROM bookmaker_odds").fetchone()[0]
        bookmaker_rows = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM bookmaker_odds o
            JOIN odds_snapshots s ON s.id = o.snapshot_id
            WHERE s.is_final = TRUE
            """
        ).fetchone()[0]
        quality = dict(
            self.connection.execute(
                "SELECT quality_status, COUNT(*) FROM odds_snapshots WHERE is_final = TRUE GROUP BY quality_status"
            ).fetchall()
        )
        last_capture = self.connection.execute("SELECT MAX(captured_at) FROM odds_snapshots").fetchone()[0]
        last_run = self.connection.execute(
            "SELECT MAX(timestamp) FROM logs WHERE module = 'capture' AND event = 'run_once_completed'"
        ).fetchone()[0]
        next_capture = self.connection.execute(
            """
            SELECT MIN(next_capture_at)
            FROM matches
            WHERE finalized_at IS NULL
              AND next_capture_at IS NOT NULL
              AND next_capture_at >= ?
            """,
            [now],
        ).fetchone()[0]
        due_count = self.connection.execute(
            "SELECT COUNT(*) FROM matches WHERE finalized_at IS NULL AND next_capture_at IS NOT NULL AND next_capture_at <= ?",
            [now],
        ).fetchone()[0]
        finalized_count = self.connection.execute("SELECT COUNT(*) FROM matches WHERE finalized_at IS NOT NULL").fetchone()[0]
        captured_match_count = self.connection.execute(
            "SELECT COUNT(DISTINCT match_id) FROM odds_snapshots WHERE is_final = TRUE"
        ).fetchone()[0]
        finalized_without_snapshot_count = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM matches m
            LEFT JOIN odds_snapshots s ON s.match_id = m.id AND s.is_final = TRUE
            WHERE m.finalized_at IS NOT NULL AND s.id IS NULL
            """
        ).fetchone()[0]
        capture_missed_count = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM matches m
            LEFT JOIN odds_snapshots s ON s.match_id = m.id AND s.is_final = TRUE
            WHERE m.finalized_at IS NOT NULL
              AND s.id IS NULL
              AND EXISTS (SELECT 1 FROM scrape_attempts a WHERE a.match_id = m.id)
            """
        ).fetchone()[0]
        skipped_out_of_window_count = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM matches m
            LEFT JOIN odds_snapshots s ON s.match_id = m.id AND s.is_final = TRUE
            WHERE m.finalized_at IS NOT NULL
              AND s.id IS NULL
              AND NOT EXISTS (SELECT 1 FROM scrape_attempts a WHERE a.match_id = m.id)
            """
        ).fetchone()[0]
        result_captured_count = self.connection.execute("SELECT COUNT(*) FROM matches WHERE result_captured_at IS NOT NULL").fetchone()[0]
        return {
            "running": False,
            "matches": match_count,
            "snapshots": final_snapshot_count,
            "snapshot_attempts": snapshot_attempts,
            "bookmaker_rows": bookmaker_rows,
            "bookmaker_row_attempts": bookmaker_row_attempts,
            "complete_snapshots": quality.get("COMPLETE", 0),
            "partial_snapshots": quality.get("PARTIAL", 0),
            "failed_snapshots": quality.get("FAILED", 0),
            "due_matches": due_count,
            "captured_matches": captured_match_count,
            "finalized_matches": finalized_count,
            "missed_finalized_matches": finalized_without_snapshot_count,
            "capture_missed_matches": capture_missed_count,
            "skipped_out_of_window_matches": skipped_out_of_window_count,
            "result_captured_matches": result_captured_count,
            "last_capture": last_capture.isoformat() if last_capture else None,
            "last_run": last_run.isoformat() if last_run else None,
            "next_capture": next_capture.isoformat() if next_capture else None,
        }

    @_locked
    def list_matches(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            WITH final_snapshot_summary AS (
                SELECT
                    match_id,
                    arg_max(id, captured_at) AS snapshot_id,
                    arg_max(quality_status, captured_at) AS quality_status,
                    MAX(captured_at) AS captured_at
                FROM odds_snapshots
                WHERE is_final = TRUE AND lower(market) = '1x2'
                GROUP BY match_id
            )
            SELECT m.id, m.betexplorer_match_id, m.league, m.home_team, m.away_team, m.kickoff_time,
                   m.status, m.timing_status, m.source_url, m.live_score,
                   m.capture_phase, m.next_capture_at, m.last_capture_at, m.finalized_at,
                   m.result_captured_at, s.snapshot_id, s.quality_status, s.captured_at,
                   COUNT(o.id) AS bookmaker_count,
                   COALESCE(SUM(CASE WHEN o.normalized_bookmaker = 'bwin' THEN 1 ELSE 0 END), 0) > 0 AS has_bwin,
                   COALESCE(SUM(CASE WHEN o.normalized_bookmaker = 'unibet' THEN 1 ELSE 0 END), 0) > 0 AS has_unibet,
                   COALESCE(a.attempt_count, 0) AS attempt_count
            FROM matches m
            LEFT JOIN final_snapshot_summary s ON s.match_id = m.id
            LEFT JOIN odds_snapshots fs ON fs.match_id = m.id AND fs.is_final = TRUE AND lower(fs.market) = '1x2'
            LEFT JOIN bookmaker_odds o ON o.snapshot_id = fs.id
            LEFT JOIN (
                SELECT match_id, COUNT(*) AS attempt_count
                FROM scrape_attempts
                GROUP BY match_id
            ) a ON a.match_id = m.id
            GROUP BY m.id, m.betexplorer_match_id, m.league, m.home_team, m.away_team, m.kickoff_time,
                     m.status, m.timing_status, m.source_url, m.live_score, m.capture_phase,
                     m.next_capture_at, m.last_capture_at, m.finalized_at, m.result_captured_at,
                     s.snapshot_id, s.quality_status, s.captured_at,
                     a.attempt_count
            ORDER BY (s.snapshot_id IS NULL), s.captured_at DESC NULLS LAST, m.kickoff_time NULLS LAST, m.home_team
            """
        ).fetchall()
        columns = [
            "id",
            "event_id",
            "league",
            "home_team",
            "away_team",
            "kickoff_time",
            "status",
            "timing_status",
            "source_url",
            "live_score",
            "capture_phase",
            "next_capture_at",
            "last_capture_at",
            "finalized_at",
            "result_captured_at",
            "snapshot_id",
            "quality_status",
            "captured_at",
            "bookmaker_count",
            "has_bwin",
            "has_unibet",
            "attempt_count",
        ]
        return [self._with_final_snapshot_age(self._serialize(dict(zip(columns, row)))) for row in rows]

    @_locked
    def list_matches_page(
        self,
        query: str = "",
        match_filter: str = "all",
        sort_mode: str = "capture_desc",
        match_date: str = "",
        offset: int = 0,
        limit: int = 120,
    ) -> dict[str, object]:
        rows = self.list_matches()
        visible = [row for row in rows if self._match_row_visible(row, query, match_filter, match_date)]
        visible.sort(key=lambda row: self._match_sort_key(row, sort_mode), reverse=sort_mode in {"capture_desc", "bookmakers_desc", "attempts_desc"})
        safe_offset = max(0, offset)
        safe_limit = min(max(1, limit), 500)
        return {
            "items": visible[safe_offset : safe_offset + safe_limit],
            "total": len(visible),
            "offset": safe_offset,
            "limit": safe_limit,
        }

    def _match_row_visible(self, row: dict[str, object], query: str, match_filter: str, match_date: str = "") -> bool:
        if match_date and not str(row.get("kickoff_time") or "").startswith(match_date):
            return False
        bookmaker_count = int(row.get("bookmaker_count") or 0)
        attempt_count = int(row.get("attempt_count") or 0)
        quality_status = row.get("quality_status")
        finalized = bool(row.get("finalized_at"))
        state_ok = (
            match_filter == "all"
            or (match_filter == "with_odds" and bookmaker_count > 0)
            or (match_filter == "req_full" and quality_status == "COMPLETE")
            or (match_filter == "req_partial" and quality_status == "PARTIAL")
            or (match_filter == "req_missing" and quality_status == "FAILED")
            or (match_filter == "missing_bwin" and bookmaker_count > 0 and not row.get("has_bwin"))
            or (match_filter == "missing_unibet" and bookmaker_count > 0 and not row.get("has_unibet"))
            or (match_filter == "capture_miss" and finalized and bookmaker_count == 0 and attempt_count > 0)
            or (match_filter == "skipped_old" and finalized and bookmaker_count == 0 and attempt_count == 0)
            or (match_filter == "due" and bool(row.get("next_capture_at")))
            or (match_filter == "finalized" and finalized)
            or (match_filter == "new" and not quality_status)
        )
        if not state_ok:
            return False
        needle = query.strip().lower()
        if not needle:
            return True
        haystack = " ".join(
            str(value)
            for value in [
                row.get("league"),
                row.get("home_team"),
                row.get("away_team"),
                row.get("event_id"),
                row.get("quality_status"),
                row.get("capture_phase"),
                row.get("timing_status"),
            ]
            if value
        ).lower()
        return needle in haystack

    def _match_sort_key(self, row: dict[str, object], sort_mode: str) -> object:
        if sort_mode == "kickoff_asc":
            return row.get("kickoff_time") or ""
        if sort_mode == "bookmakers_desc":
            return int(row.get("bookmaker_count") or 0)
        if sort_mode == "attempts_desc":
            return int(row.get("attempt_count") or 0)
        return row.get("captured_at") or ""

    @_locked
    def list_match_days(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT CAST(kickoff_time AS DATE) AS match_date,
                   COUNT(*) AS matches,
                   SUM(CASE WHEN next_capture_at IS NOT NULL AND finalized_at IS NULL THEN 1 ELSE 0 END) AS due_or_scheduled,
                   SUM(CASE WHEN finalized_at IS NULL THEN 1 ELSE 0 END) AS active
            FROM matches
            WHERE kickoff_time IS NOT NULL
            GROUP BY match_date
            ORDER BY match_date
            """
        ).fetchall()
        return [
            {
                "date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "matches": row[1],
                "due_or_scheduled": row[2] or 0,
                "active": row[3] or 0,
            }
            for row in rows
        ]

    @_locked
    def match_detail(self, match_id: str) -> dict[str, object] | None:
        match = next((row for row in self.list_matches() if row["id"] == match_id), None)
        if not match:
            return None
        snapshots = self.connection.execute(
            """
            SELECT s.*, COUNT(o.id) AS bookmaker_count,
                   m.kickoff_time
            FROM odds_snapshots s
            JOIN matches m ON m.id = s.match_id
            LEFT JOIN bookmaker_odds o ON o.snapshot_id = s.id
            WHERE s.match_id = ?
            GROUP BY s.id, s.match_id, s.event_id, s.captured_at, s.market, s.capture_type,
                     s.quality_status, s.is_final_candidate, s.is_final, s.source_page_type,
                     s.raw_payload_path, s.required_bookmakers_json, s.created_at, m.kickoff_time
            ORDER BY s.captured_at DESC
            """,
            [match_id],
        ).fetchall()
        snapshot_columns = [col[0] for col in self.connection.description]
        odds_rows = self.connection.execute(
            """
            SELECT o.*, s.market, s.captured_at AS snapshot_captured_at, s.quality_status AS snapshot_quality_status
            FROM bookmaker_odds o
            JOIN odds_snapshots s ON s.id = o.snapshot_id
            WHERE s.match_id = ? AND s.is_final = TRUE
            ORDER BY s.market, s.captured_at DESC, o.bookmaker
            """,
            [match_id],
        ).fetchall()
        odds_columns = [col[0] for col in self.connection.description]
        attempts = self.connection.execute(
            "SELECT * FROM scrape_attempts WHERE match_id = ? ORDER BY started_at DESC",
            [match_id],
        ).fetchall()
        attempt_columns = [col[0] for col in self.connection.description]
        return self._serialize(
            {
                "match": match,
                "snapshots": [self._with_final_snapshot_age(self._serialize(dict(zip(snapshot_columns, row)))) for row in snapshots],
                "bookmaker_odds": [dict(zip(odds_columns, row)) for row in odds_rows],
                "attempts": [dict(zip(attempt_columns, row)) for row in attempts],
            }
        )

    @_locked
    def list_snapshots(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT s.*, m.league, m.home_team, m.away_team, COUNT(o.id) AS bookmaker_count,
                   m.kickoff_time
            FROM odds_snapshots s
            LEFT JOIN matches m ON m.id = s.match_id
            LEFT JOIN bookmaker_odds o ON o.snapshot_id = s.id
            GROUP BY s.id, s.match_id, s.event_id, s.captured_at, s.market, s.capture_type,
                     s.quality_status, s.is_final_candidate, s.is_final, s.source_page_type,
                     s.raw_payload_path, s.required_bookmakers_json, s.created_at,
                     m.league, m.home_team, m.away_team, m.kickoff_time
            ORDER BY s.captured_at DESC LIMIT 300
            """
        ).fetchall()
        columns = [col[0] for col in self.connection.description]
        return [self._with_final_snapshot_age(self._serialize(dict(zip(columns, row)))) for row in rows]

    @_locked
    def list_attempts(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT a.*, m.league, m.home_team, m.away_team
            FROM scrape_attempts a
            LEFT JOIN matches m ON m.id = a.match_id
            ORDER BY a.started_at DESC LIMIT 300
            """
        ).fetchall()
        columns = [col[0] for col in self.connection.description]
        return [self._serialize(dict(zip(columns, row))) for row in rows]

    @_locked
    def list_logs(self) -> list[dict[str, object]]:
        rows = self.connection.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 200").fetchall()
        columns = [col[0] for col in self.connection.description]
        return [self._serialize(dict(zip(columns, row))) for row in rows]

    @_locked
    def bookmaker_coverage(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT o.bookmaker, o.normalized_bookmaker,
                   COUNT(*) AS rows,
                   COUNT(DISTINCT s.match_id) AS matches,
                   AVG(o.home_odds) AS avg_home_odds,
                   AVG(o.draw_odds) AS avg_draw_odds,
                   AVG(o.away_odds) AS avg_away_odds,
                   MAX(s.captured_at) AS last_seen
            FROM bookmaker_odds o
            JOIN odds_snapshots s ON s.id = o.snapshot_id AND s.is_final = TRUE
            GROUP BY o.bookmaker, o.normalized_bookmaker
            ORDER BY matches DESC, rows DESC, o.bookmaker
            """
        ).fetchall()
        columns = [col[0] for col in self.connection.description]
        return [self._serialize(dict(zip(columns, row))) for row in rows]

    @_locked
    def final_snapshot_items(self) -> list[tuple[DiscoveredMatch, OddsSnapshot]]:
        rows = self.connection.execute(
            """
            SELECT m.betexplorer_match_id, m.source_url, m.league, m.home_team, m.away_team, m.kickoff_time,
                   m.timing_status, m.status, m.capture_phase, m.finalized_at,
                   s.event_id, s.market, s.captured_at, s.quality_status,
                   s.required_bookmakers_json, s.source_page_type, s.capture_type, s.id
            FROM matches m
            JOIN odds_snapshots s ON s.match_id = m.id AND s.is_final = TRUE
            ORDER BY s.captured_at DESC
            """
        ).fetchall()
        items: list[tuple[DiscoveredMatch, OddsSnapshot]] = []
        for row in rows:
            snapshot_id = row[17]
            odds_rows = self.connection.execute(
                """
                SELECT bookmaker, normalized_bookmaker, home_odds, draw_odds, away_odds,
                       bookmaker_id, betexplorer_bookmaker_id, raw_row_text, raw_attributes_json
                FROM bookmaker_odds WHERE snapshot_id = ? ORDER BY bookmaker
                """,
                [snapshot_id],
            ).fetchall()
            odds = [
                BookmakerOdds(
                    bookmaker=o[0],
                    normalized_bookmaker=o[1],
                    home_odds=o[2],
                    draw_odds=o[3],
                    away_odds=o[4],
                    bookmaker_id=o[5],
                    betexplorer_bookmaker_id=o[6],
                    raw_row_text=o[7] or "",
                    raw_attributes=json.loads(o[8] or "{}"),
                )
                for o in odds_rows
            ]
            items.append(
                (
                    DiscoveredMatch(
                        event_id=row[0],
                        source_url=row[1],
                        league=row[2],
                        home_team=row[3],
                        away_team=row[4],
                        kickoff_time=row[5],
                        timing_status=TimingStatus(row[6]),
                        status=row[7],
                        capture_phase=self._effective_capture_phase(row[8], row[9]),
                        finalized_at=row[9],
                    ),
                    OddsSnapshot(
                        event_id=row[10],
                        market=row[11],
                        captured_at=row[12],
                        quality_status=SnapshotQuality(row[13]),
                        required_bookmakers=json.loads(row[14] or "[]"),
                        source_page_type=row[15],
                        capture_type=CaptureType(row[16]),
                        bookmaker_odds=odds,
                    ),
                )
            )
        return items

    def _serialize(self, value):
        if isinstance(value, dict):
            serialized = {key: self._serialize(item) for key, item in value.items()}
            if serialized.get("finalized_at"):
                serialized["capture_phase"] = "FINALIZED"
            return serialized
        if isinstance(value, list):
            return [self._serialize(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _with_final_snapshot_age(self, row: dict[str, object]) -> dict[str, object]:
        kickoff = self._parse_serialized_datetime(row.get("kickoff_time"))
        captured = self._parse_serialized_datetime(row.get("captured_at"))
        row["final_snapshot_age_to_kickoff_seconds"] = final_snapshot_age_to_kickoff_seconds(
            kickoff,
            captured,
            self.timezone_offset,
        )
        return row

    def _parse_serialized_datetime(self, value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value)
        return None

    def _effective_capture_phase(self, capture_phase: str | None, finalized_at: datetime | None) -> str | None:
        if finalized_at:
            return "FINALIZED"
        return capture_phase


def _average_odds(records: list[dict[str, object]], field: str) -> float | None:
    values = [normalize_odds(record.get(field)) for record in records]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _odds_distance(current: float | None, matched: float | None) -> float | None:
    if current is None or matched is None:
        return None
    return round(abs(current - matched), 2)


def _signal_explanation(signal_type: str) -> str:
    if signal_type == "exact_odds":
        return "Exact 6-odds Bwin + Unibet match"
    if signal_type == "neighbor_odds":
        return "Nearby odds within 0.05"
    if signal_type == "one_draw":
        return "One draw odd differs; other five odds match"
    return "Historical odds pattern"


def _signal_rank(signal_type: str) -> int:
    if signal_type == "exact_odds":
        return 1
    if signal_type == "neighbor_odds":
        return 2
    if signal_type == "one_draw":
        return 3
    return 99


def _signal_order_sql(sort_mode: str) -> str:
    if sort_mode == "kickoff_asc":
        return (
            "kickoff_time NULLS LAST, COALESCE(signal_rank, 99), "
            "COALESCE(similarity_score, 0) DESC, sample_size DESC, normalized_bookmaker"
        )
    if sort_mode == "kickoff_desc":
        return (
            "kickoff_time DESC NULLS LAST, COALESCE(signal_rank, 99), "
            "COALESCE(similarity_score, 0) DESC, sample_size DESC, normalized_bookmaker"
        )
    if sort_mode == "sample_desc":
        return (
            "sample_size DESC, COALESCE(signal_rank, 99), "
            "COALESCE(similarity_score, 0) DESC, kickoff_time NULLS LAST, normalized_bookmaker"
        )
    return (
        "COALESCE(signal_rank, 99), COALESCE(similarity_score, 0) DESC, "
        "sample_size DESC, kickoff_time NULLS LAST, normalized_bookmaker"
    )


def _candidate_has_complete_required_odds(candidate: dict[str, object]) -> bool:
    keys = [
        "bwin_home_odds",
        "bwin_draw_odds",
        "bwin_away_odds",
        "unibet_home_odds",
        "unibet_draw_odds",
        "unibet_away_odds",
    ]
    return all(normalize_odds(candidate.get(key)) is not None for key in keys)


def _build_complete_record_index(
    records: list[dict[str, object]],
) -> dict[str, dict[tuple[object, ...], list[dict[str, object]]]]:
    index: dict[str, dict[tuple[object, ...], list[dict[str, object]]]] = {
        "exact_odds": {},
        "one_draw": {},
    }
    for record in records:
        orientations = [_record_with_orientation(record, reverse=False)]
        if record.get("allow_reverse"):
            orientations.append(_record_with_orientation(record, reverse=True))
        for oriented in orientations:
            exact_key = _exact_six_odds_key(oriented)
            if exact_key:
                index["exact_odds"].setdefault(exact_key, []).append(oriented)
            for key in _one_draw_keys(oriented):
                index["one_draw"].setdefault(key, []).append(oriented)
    return index


def _matching_indexed_records(
    candidate: dict[str, object],
    record_index: dict[str, dict[tuple[object, ...], list[dict[str, object]]]],
    signal_type: str,
) -> list[dict[str, object]]:
    if signal_type == "exact_odds":
        keys = [_exact_six_odds_key(candidate)]
    elif signal_type == "one_draw":
        keys = _one_draw_keys(candidate)
    else:
        keys = []
    matched_by_identity: dict[tuple[object, ...], dict[str, object]] = {}
    for key in [key for key in keys if key]:
        for record in record_index.get(signal_type, {}).get(key, []):
            if record.get("dataset") == "Played archive" and record.get("source_file") == candidate.get("event_id"):
                continue
            if signal_type == "exact_odds" and not _is_exact_six_odds(candidate, record):
                continue
            if signal_type == "one_draw" and not _is_one_draw_match(candidate, record):
                continue
            identity = (
                record.get("dataset"),
                record.get("source_file"),
                record.get("full_time_score"),
                record.get("bwin_home_odds"),
                record.get("bwin_draw_odds"),
                record.get("bwin_away_odds"),
                record.get("unibet_home_odds"),
                record.get("unibet_draw_odds"),
                record.get("unibet_away_odds"),
            )
            matched_by_identity[identity] = record
    return list(matched_by_identity.values())


def _exact_six_odds_key(record: dict[str, object]) -> tuple[object, ...] | None:
    values = [
        normalize_odds(record.get(f"{bookmaker}_{side}_odds"))
        for bookmaker in ["bwin", "unibet"]
        for side in ["home", "draw", "away"]
    ]
    if any(value is None for value in values):
        return None
    return tuple(values)


def _one_draw_keys(record: dict[str, object]) -> list[tuple[object, ...]]:
    bwin_home = normalize_odds(record.get("bwin_home_odds"))
    bwin_draw = normalize_odds(record.get("bwin_draw_odds"))
    bwin_away = normalize_odds(record.get("bwin_away_odds"))
    unibet_home = normalize_odds(record.get("unibet_home_odds"))
    unibet_draw = normalize_odds(record.get("unibet_draw_odds"))
    unibet_away = normalize_odds(record.get("unibet_away_odds"))
    if any(value is None for value in [bwin_home, bwin_draw, bwin_away, unibet_home, unibet_draw, unibet_away]):
        return []
    return [
        ("bwin_draw_differs", bwin_home, bwin_away, unibet_home, unibet_draw, unibet_away),
        ("unibet_draw_differs", unibet_home, unibet_away, bwin_home, bwin_draw, bwin_away),
    ]


def _record_with_orientation(record: dict[str, object], reverse: bool) -> dict[str, object]:
    if not reverse:
        return record
    oriented = dict(record)
    for side in ["home", "draw", "away"]:
        bwin_key = f"bwin_{side}_odds"
        unibet_key = f"unibet_{side}_odds"
        oriented[bwin_key], oriented[unibet_key] = oriented[unibet_key], oriented[bwin_key]
    return oriented


def _is_exact_six_odds(candidate: dict[str, object], record: dict[str, object]) -> bool:
    return all(
        normalize_odds(candidate.get(f"{bookmaker}_{side}_odds"))
        == normalize_odds(record.get(f"{bookmaker}_{side}_odds"))
        for bookmaker in ["bwin", "unibet"]
        for side in ["home", "draw", "away"]
    )


def _is_one_draw_match(candidate: dict[str, object], record: dict[str, object]) -> bool:
    bwin_draw_differs = _bookmaker_has_one_draw_difference(candidate, record, "bwin")
    unibet_draw_differs = _bookmaker_has_one_draw_difference(candidate, record, "unibet")
    bwin_exact = _bookmaker_is_exact(candidate, record, "bwin")
    unibet_exact = _bookmaker_is_exact(candidate, record, "unibet")
    return (bwin_draw_differs and unibet_exact) or (unibet_draw_differs and bwin_exact)


def _bookmaker_is_exact(candidate: dict[str, object], record: dict[str, object], bookmaker: str) -> bool:
    return all(
        normalize_odds(candidate.get(f"{bookmaker}_{side}_odds"))
        == normalize_odds(record.get(f"{bookmaker}_{side}_odds"))
        for side in ["home", "draw", "away"]
    )


def _bookmaker_has_one_draw_difference(
    candidate: dict[str, object],
    record: dict[str, object],
    bookmaker: str,
) -> bool:
    home_exact = normalize_odds(candidate.get(f"{bookmaker}_home_odds")) == normalize_odds(
        record.get(f"{bookmaker}_home_odds")
    )
    away_exact = normalize_odds(candidate.get(f"{bookmaker}_away_odds")) == normalize_odds(
        record.get(f"{bookmaker}_away_odds")
    )
    draw_differs = normalize_odds(candidate.get(f"{bookmaker}_draw_odds")) != normalize_odds(
        record.get(f"{bookmaker}_draw_odds")
    )
    return home_exact and away_exact and draw_differs


def _signal_similarity(signal_type: str) -> float:
    if signal_type == "exact_odds":
        return 100.0
    if signal_type == "one_draw":
        return 83.3
    return 0.0


def _required_bookmaker_names(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
    elif isinstance(value, list):
        parsed = value
    else:
        parsed = []
    names = {
        normalize_bookmaker_name(str(item))
        for item in parsed
        if item is not None and normalize_bookmaker_name(str(item))
    }
    return sorted(names)


def _required_bookmaker_score(odds: list[BookmakerOdds], required_bookmakers: list[str]) -> int:
    required = set(_required_bookmaker_names(required_bookmakers))
    if not required:
        return 0
    present = {
        normalize_bookmaker_name(row.normalized_bookmaker or row.bookmaker)
        for row in odds
        if row.is_available and normalize_bookmaker_name(row.normalized_bookmaker or row.bookmaker) in required
    }
    return len(present)
