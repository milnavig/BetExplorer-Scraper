from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from threading import RLock

import duckdb

from .clock import utc_now
from .models import BookmakerOdds, CaptureType, DiscoveredMatch, OddsSnapshot, SnapshotQuality, TimingStatus
from .snapshot_metrics import final_snapshot_age_to_kickoff_seconds


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
                True,
                snapshot.source_page_type,
                snapshot.raw_payload_path,
                json.dumps(snapshot.required_bookmakers),
                now,
            ],
        )
        for odds in snapshot.bookmaker_odds:
            self.save_bookmaker_odds(snapshot_id, odds, now)
        return snapshot_id

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
                WHERE is_final = TRUE
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
            LEFT JOIN odds_snapshots fs ON fs.match_id = m.id AND fs.is_final = TRUE
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
                       bookmaker_id, betexplorer_bookmaker_id, raw_row_text
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
                        capture_phase=row[8],
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
            return {key: self._serialize(item) for key, item in value.items()}
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
