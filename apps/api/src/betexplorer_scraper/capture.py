from __future__ import annotations

import asyncio
import gzip
import json
import time as monotonic_time
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .clock import now_for_timezone_offset, utc_now
from .config import Settings
from .database import Database
from .ingest import CapturePriority, CaptureRequest, IngestCoordinator
from .models import DiscoveredMatch, OddsSnapshot, TimingStatus
from .parsers import DiscoveryParser, OddsParser
from .persistence import AttemptWrite, PersistenceCoordinator, ScheduleWrite
from .scheduler import Scheduler, SchedulerConfig
from .timing import classify_timing
from .transport import BetExplorerTransport, HttpBetExplorerTransport
from .validator import classify_snapshot_quality, required_bookmaker_presence


class CaptureService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        transport: BetExplorerTransport | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.transport = transport or HttpBetExplorerTransport(
            settings.betexplorer_base_url,
            timezone_offset=settings.betexplorer_timezone_offset,
        )
        self.discovery_parser = DiscoveryParser(settings.betexplorer_base_url, settings.result_finish_grace_minutes)
        self.odds_parser = OddsParser()
        self.odds_capture_window_minutes = max(
            settings.upcoming_window_minutes,
            settings.odds_capture_lookahead_hours * 60,
        )
        self.scheduler = Scheduler(
            SchedulerConfig(
                upcoming_window_minutes=self.odds_capture_window_minutes,
                recently_started_window_minutes=settings.recently_started_window_minutes,
                max_match_age_after_kickoff_minutes=settings.finalize_after_kickoff_minutes,
                monitoring_capture_poll_interval_seconds=settings.monitoring_capture_poll_interval_seconds,
                final_capture_poll_interval_seconds=settings.final_capture_poll_interval_seconds,
                final_capture_fast_window_minutes=settings.final_capture_fast_window_minutes,
                discovery_poll_interval_seconds=settings.discovery_poll_interval_seconds,
            )
        )
        self._run_lock = asyncio.Lock()
        self._archive_lock = asyncio.Lock()
        self.ingest = IngestCoordinator(settings.max_concurrent_captures, settings.ingest_queue_size)
        self.persistence = PersistenceCoordinator(
            database,
            settings.persistence_batch_size,
            settings.persistence_flush_interval_ms,
            settings.persistence_queue_size,
        )
        self._last_discovery_at: datetime | None = None
        self._markets_cache: dict[str, tuple[datetime, list[str]]] = {}
        self._match_page_cache: dict[str, tuple[datetime, str]] = {}
        self._progress: dict[str, Any] = self._idle_progress()
        self._archive_progress: dict[str, Any] = self._idle_progress()
        self._last_changed_match_ids: list[str] = []
        self._last_raw_cleanup_at = 0.0

    def progress_status(self) -> dict[str, Any]:
        return dict(self._progress)

    def archive_progress_status(self) -> dict[str, Any]:
        return dict(self._archive_progress)

    def last_changed_match_ids(self) -> list[str]:
        return list(self._last_changed_match_ids)

    def ingest_status(self) -> dict[str, object]:
        return {**self.ingest.metrics(), "persistence": self.persistence.metrics()}

    async def close(self) -> None:
        await self.persistence.close()
        await self.ingest.close()

    def _idle_progress(self) -> dict[str, Any]:
        return {
            "running": False,
            "trigger": None,
            "phase": "idle",
            "started_at": None,
            "finished_at": None,
            "discovered": 0,
            "due": 0,
            "queued": 0,
            "active": 0,
            "completed": 0,
            "captured": 0,
            "complete": 0,
            "partial": 0,
            "unavailable": 0,
            "failed": 0,
            "skipped": 0,
            "finalized": 0,
            "waiting": 0,
            "results_captured": 0,
            "results_checked": 0,
            "current_event_id": None,
            "last_error": None,
            "last_discovery_at": None,
            "next_discovery_at": None,
        }

    def _set_progress(self, **values: Any) -> None:
        self._progress = {**self._progress, **values}

    def _set_archive_progress(self, **values: Any) -> None:
        self._archive_progress = {**self._archive_progress, **values}

    async def run_once(self, now: datetime | None = None, trigger: str = "manual", force_discovery: bool = True) -> dict[str, object]:
        async with self._run_lock:
            try:
                return await self._run_once_locked(now, trigger, force_discovery)
            except Exception as exc:
                self._set_progress(
                    running=False,
                    phase="error",
                    finished_at=utc_now().isoformat(),
                    last_error=str(exc),
                )
                raise

    async def archive_football_date(self, target_date: date) -> dict[str, int]:
        async with self._archive_lock:
            return await self._archive_football_date_locked(target_date, None)

    async def run_archive_job(self, job_id: str, target_date: date) -> dict[str, int]:
        async with self._archive_lock:
            self.database.start_archive_job(job_id)
            try:
                result = await self._archive_football_date_locked(target_date, job_id)
                self.database.finish_archive_job(job_id)
                return result
            except Exception as exc:
                self.database.finish_archive_job(job_id, str(exc))
                raise

    async def _archive_football_date_locked(self, target_date: date, job_id: str | None) -> dict[str, int]:
        archive_now = datetime.combine(target_date, time(23, 59))
        self._archive_progress = {
            **self._idle_progress(),
            "running": True,
            "trigger": "archive_date",
            "phase": "archive_discovery",
            "started_at": utc_now().isoformat(),
        }
        page = await self.ingest.submit(
            CaptureRequest(
                f"date:{target_date.isoformat()}",
                "html",
                CapturePriority.BACKFILL,
                "archive_discovery",
                request_kind="discovery_date",
            ),
            lambda: self.transport.fetch_football_date(target_date),
        )
        parsed_matches = self.discovery_parser.parse_homepage(page.text, archive_now)
        matches_by_event_id = {
            match.event_id: match
            for match in parsed_matches
            if match.kickoff_time is not None and match.kickoff_time.date() == target_date
        }
        matches = list(matches_by_event_id.values())
        discovered = len(matches)
        if job_id:
            self.database.set_archive_job_items(
                job_id,
                [{"event_id": match.event_id, "source_url": match.source_url} for match in matches],
            )
            pending_event_ids = self.database.pending_archive_job_events(job_id)
            matches = [match for match in matches if match.event_id in pending_event_ids]
        captured = 0
        complete = 0
        partial = 0
        unavailable = 0
        failed = 0
        results_captured = 0
        results_checked = 0
        processed_match_ids: list[str] = []
        self._set_archive_progress(discovered=discovered, due=discovered, queued=discovered, phase="archive_capturing")
        counter_lock = asyncio.Lock()

        async def process_match(match: DiscoveredMatch) -> None:
            nonlocal captured, complete, partial, unavailable, failed, results_captured, results_checked
            if job_id:
                self.database.update_archive_job_item(
                    job_id,
                    match.event_id,
                    state="processing",
                    increment_attempt=True,
                )
            self._set_archive_progress(
                active=int(self._archive_progress["active"]) + 1,
                current_event_id=match.event_id,
            )
            await self._enrich_kickoff_from_match_page_if_needed(
                match,
                archive_now,
                CapturePriority.BACKFILL,
                "archive_kickoff",
            )
            match.timing_status = TimingStatus.FINISHED
            match.status = "finished"
            match_id = self.database.upsert_match(match)
            processed_match_ids.append(match_id)
            if job_id:
                self.database.update_archive_job_item(
                    job_id,
                    match.event_id,
                    match_id=match_id,
                    state="processing",
                )
            await self.persistence.submit_schedule(
                ScheduleWrite(match_id, "FINALIZED", None, utc_now())
            )
            saved, market_complete, odds_status = await self.capture_match_market(
                match_id, match.event_id, match.source_url, "1x2", CapturePriority.BACKFILL, "backfill"
            )
            if job_id:
                self.database.update_archive_job_item(
                    job_id,
                    match.event_id,
                    odds_status=odds_status,
                    error_message=self._archive_odds_message(odds_status),
                )

            score = match.live_score
            checked = 0
            captured_result = 0
            if not score:
                checked = 1
                try:
                    match_page = await self._fetch_match_page_cached(
                        match.source_url,
                        CapturePriority.RESULT_RECOVERY,
                        "archive_result",
                    )
                    finished, parsed_score = self.discovery_parser.parse_match_page_result(match_page)
                    score = parsed_score if finished or parsed_score else None
                except Exception as exc:
                    self.database.log(
                        "warning",
                        "archive",
                        "archive_result_lookup_failed",
                        match.event_id,
                        {"error": str(exc)},
                    )
            if score and self.database.mark_result_captured(match_id, score, utc_now()):
                captured_result = 1
            if job_id:
                score_captured = bool(score) and bool(
                    self.database.get_match_schedule(match_id).get("result_captured_at")
                )
                error_message = self._archive_odds_message(odds_status)
                if error_message is None and not score_captured:
                    error_message = "Final score is unavailable"
                self.database.update_archive_job_item(
                    job_id,
                    match.event_id,
                    state="ready",
                    score_status="complete" if score_captured else "failed",
                    error_message=error_message,
                )

            async with counter_lock:
                captured += 1 if saved else 0
                complete += 1 if market_complete else 0
                partial += 1 if odds_status == "partial" else 0
                unavailable += 1 if odds_status == "unavailable" else 0
                failed += 1 if odds_status == "failed" else 0
                results_checked += checked
                results_captured += captured_result
                self._set_archive_progress(
                    active=max(0, int(self._archive_progress["active"]) - 1),
                    completed=int(self._archive_progress["completed"]) + 1,
                    captured=captured,
                    complete=complete,
                    partial=partial,
                    unavailable=unavailable,
                    failed=failed,
                    results_captured=results_captured,
                    results_checked=results_checked,
                )

        match_iterator = iter(matches)

        async def archive_worker() -> None:
            while True:
                try:
                    match = next(match_iterator)
                except StopIteration:
                    return
                await process_match(match)

        worker_count = min(len(matches), max(1, self.settings.historical_backfill_concurrency))
        await asyncio.gather(*(archive_worker() for _ in range(worker_count)))

        archive = self.database.archive_played_matches(processed_match_ids)
        if job_id:
            self.database.mark_archive_job_archived_items(job_id)
        recompute = self.database.recompute_historical_signals(processed_match_ids)
        result = {
            "date": target_date.isoformat(),
            "discovered": discovered,
            "captured": captured,
            "complete": complete,
            "partial": partial,
            "unavailable": unavailable,
            "failed": failed,
            "results_captured": results_captured,
            "results_checked": results_checked,
            "archived": archive["archived"],
            "signals": recompute["signals"],
            "matches_evaluated": recompute["matches_evaluated"],
        }
        self._set_archive_progress(running=False, active=0, phase="archive_complete", finished_at=utc_now().isoformat())
        return result

    async def _run_once_locked(self, now: datetime | None = None, trigger: str = "manual", force_discovery: bool = True) -> dict[str, object]:
        now = now or now_for_timezone_offset(self.settings.betexplorer_timezone_offset)
        next_discovery = self._next_discovery_at()
        self._progress = {
            **self._idle_progress(),
            "running": True,
            "trigger": trigger,
            "phase": "starting",
            "started_at": utc_now().isoformat(),
            "last_discovery_at": self._last_discovery_at.isoformat() if self._last_discovery_at else None,
            "next_discovery_at": next_discovery.isoformat() if next_discovery else None,
        }
        should_discover = force_discovery or self._discovery_due(now)
        if should_discover:
            self._set_progress(phase="discovery")
            matches = await self._discover_matches(now)
            self._last_discovery_at = now
            next_discovery = self._next_discovery_at()
            self._set_progress(
                discovered=len(matches),
                phase="live_results",
                last_discovery_at=self._last_discovery_at.isoformat(),
                next_discovery_at=next_discovery.isoformat() if next_discovery else None,
            )
            try:
                live = await self.ingest.submit(
                    CaptureRequest(
                        "live-results",
                        "json",
                        CapturePriority.KICKOFF,
                        "live_results",
                        request_kind="live_results",
                    ),
                    self.transport.fetch_live_results,
                )
                matches = self.discovery_parser.apply_live_results(matches, live.text)
            except Exception as exc:
                self.database.log("warning", "capture", "live_results_failed", details={"error": str(exc)})
                self._set_progress(last_error=str(exc))
        else:
            matches = []
            self._set_progress(phase="due_scan", discovered=0)

        captured = 0
        failed = 0
        due = 0
        skipped = 0
        finalized = 0
        waiting = 0
        results_captured = 0
        results_checked = 0
        capture_jobs: list[tuple[str, str, str, datetime | None, str, datetime | None]] = []
        planned_schedules: list[ScheduleWrite] = []
        changed_match_ids: list[str] = []
        self._set_progress(phase="planning")

        seen_match_ids: set[str] = set()

        def schedule_match(match_id: str, match: DiscoveredMatch, schedule_state: dict[str, datetime | str | None]) -> None:
            nonlocal due, skipped, finalized, waiting
            decision = self.scheduler.plan(
                match,
                now,
                next_capture_at=schedule_state["next_capture_at"],
                finalized_at=schedule_state["finalized_at"],
                last_capture_at=schedule_state["last_capture_at"],
            )
            planned_schedules.append(
                ScheduleWrite(match_id, decision.phase, decision.next_capture_at, decision.finalized_at)
            )
            if not decision.should_capture:
                skipped += 1
                finalized += 1 if decision.phase == "FINALIZED" else 0
                waiting += 1 if decision.phase in {"WAITING", "DISCOVERY_ONLY"} else 0
                return
            due += 1
            capture_jobs.append((match_id, match.event_id, match.source_url, decision.next_capture_at, decision.phase, decision.finalized_at))
            self._set_progress(due=due, queued=len(capture_jobs), skipped=skipped, finalized=finalized, waiting=waiting)

        for match in matches:
            await self._enrich_kickoff_from_match_page_if_needed(match, now)
            match.timing_status = classify_timing(
                match.kickoff_time,
                now,
                self.odds_capture_window_minutes,
                self.settings.recently_started_window_minutes,
                is_live=match.timing_status.value == "LIVE",
                is_finished=match.timing_status.value == "FINISHED",
            )
            match_id = self.database.upsert_match(match)
            seen_match_ids.add(match_id)
            schedule_state = self.database.get_match_schedule(match_id)
            if self._should_capture_result(match, now, schedule_state):
                results_captured += 1 if self.database.mark_result_captured(match_id, match.live_score, utc_now()) else 0
            schedule_match(match_id, match, schedule_state)

        if should_discover:
            self._set_progress(phase="result_backfill", results_captured=results_captured)
            backfill_checked, backfill_captured = await self._capture_result_backfill(now, seen_match_ids)
            results_checked += backfill_checked
            results_captured += backfill_captured
            for match_id, match in self.database.list_empty_finalized_odds_backfill_candidates(
                now,
                self.settings.result_capture_lookback_hours,
                self.settings.result_backfill_batch_size,
            ):
                due += 1
                capture_jobs.append((match_id, match.event_id, match.source_url, None, "FINALIZING", now))
            self._set_progress(due=due, queued=len(capture_jobs))

        for match_id, match, schedule_state in self.database.list_due_scheduled_matches(now):
            if match_id in seen_match_ids:
                continue
            match.timing_status = classify_timing(
                match.kickoff_time,
                now,
                self.odds_capture_window_minutes,
                self.settings.recently_started_window_minutes,
                is_live=match.timing_status.value == "LIVE",
                is_finished=match.timing_status.value == "FINISHED",
            )
            schedule_match(match_id, match, schedule_state)

        self._set_progress(due=due, queued=len(capture_jobs), skipped=skipped, finalized=finalized, waiting=waiting)
        if planned_schedules:
            await asyncio.gather(
                *(self.persistence.submit_schedule(write) for write in planned_schedules)
            )
        if capture_jobs:
            self._set_progress(phase="capturing", queued=len(capture_jobs), active=0, completed=0)

            async def run_capture(job: tuple[str, str, str, datetime | None, str, datetime | None]) -> bool:
                nonlocal captured, failed
                match_id, event_id, source_url, next_capture_at, phase, finalized_at = job
                self._set_progress(active=self._progress["active"] + 1, current_event_id=event_id)
                capture_priority = CapturePriority.KICKOFF if phase in {"FINALIZING", "FINAL"} else CapturePriority.UPCOMING
                if trigger == "manual_force":
                    capture_priority = CapturePriority.MANUAL
                ok = await self.capture_match(match_id, event_id, source_url, capture_priority, trigger)
                stored_phase = "FINALIZED" if finalized_at is not None else phase
                await self.persistence.submit_schedule(
                    ScheduleWrite(match_id, stored_phase, next_capture_at, finalized_at, utc_now())
                )
                captured += 1 if ok else 0
                failed += 0 if ok else 1
                if ok:
                    changed_match_ids.append(match_id)
                self._set_progress(
                    active=max(0, self._progress["active"] - 1),
                    completed=self._progress["completed"] + 1,
                    captured=captured,
                    failed=failed,
                    current_event_id=event_id,
                )
                return ok

            job_iterator = iter(capture_jobs)
            results: list[bool] = []

            async def capture_worker() -> None:
                while True:
                    try:
                        job = next(job_iterator)
                    except StopIteration:
                        return
                    results.append(await run_capture(job))

            worker_count = min(len(capture_jobs), max(1, self.settings.max_concurrent_captures))
            await asyncio.gather(*(capture_worker() for _ in range(worker_count)))
            captured = sum(1 for ok in results if ok)
            failed = len(results) - captured
        else:
            self._set_progress(phase="completed", queued=0, active=0, completed=0)
        result = {
            "discovered": len(matches),
            "due": due,
            "captured": captured,
            "failed": failed,
            "skipped": skipped,
            "finalized": finalized,
            "waiting": waiting,
            "results_captured": results_captured,
            "results_checked": results_checked,
        }
        self._last_changed_match_ids = sorted(set(changed_match_ids))
        self.database.log("info", "capture", "run_once_completed", details=result)
        self._set_progress(
            running=False,
            phase="completed",
            finished_at=utc_now().isoformat(),
            discovered=result["discovered"],
            due=result["due"],
            queued=len(capture_jobs),
            active=0,
            completed=len(capture_jobs),
            captured=result["captured"],
            failed=result["failed"],
            skipped=result["skipped"],
            finalized=result["finalized"],
            waiting=result["waiting"],
            results_captured=result["results_captured"],
            results_checked=result["results_checked"],
            last_discovery_at=self._last_discovery_at.isoformat() if self._last_discovery_at else None,
            next_discovery_at=self._next_discovery_at().isoformat() if self._next_discovery_at() else None,
        )
        return result

    def _discovery_due(self, now: datetime) -> bool:
        if self._last_discovery_at is None:
            return True
        return now - self._last_discovery_at >= timedelta(seconds=self.settings.discovery_poll_interval_seconds)

    def _next_discovery_at(self) -> datetime | None:
        if self._last_discovery_at is None:
            return None
        return self._last_discovery_at + timedelta(seconds=self.settings.discovery_poll_interval_seconds)

    async def _discover_matches(self, now: datetime) -> list:
        pages = [
            await self.ingest.submit(
                CaptureRequest(
                    "homepage",
                    "html",
                    CapturePriority.UPCOMING,
                    "discovery",
                    request_kind="discovery_homepage",
                ),
                self.transport.fetch_homepage,
            )
        ]
        past_days = max(1, (self.settings.result_capture_lookback_hours + 23) // 24)
        future_days = max(self.settings.discovery_days_ahead, (self.settings.odds_capture_lookahead_hours + 23) // 24)
        discovery_semaphore = asyncio.Semaphore(max(1, self.settings.discovery_concurrency))

        async def fetch_date_page(target_date: date):
            async with discovery_semaphore:
                try:
                    return await self.ingest.submit(
                        CaptureRequest(
                            f"date:{target_date.isoformat()}",
                            "html",
                            CapturePriority.UPCOMING,
                            "discovery",
                            request_kind="discovery_date",
                        ),
                        lambda: self.transport.fetch_football_date(target_date),
                    )
                except NotImplementedError:
                    return None
                except Exception as exc:
                    self.database.log(
                        "warning",
                        "capture",
                        "date_discovery_failed",
                        details={"date": target_date.isoformat(), "error": str(exc)},
                    )
                    return None

        target_dates = []
        for offset in range(-past_days, future_days + 1):
            target_date = (now + timedelta(days=offset)).date()
            target_dates.append(target_date)
        date_pages = await asyncio.gather(*(fetch_date_page(target_date) for target_date in target_dates))
        pages.extend(page for page in date_pages if page is not None)

        matches_by_event_id = {}
        for page in pages:
            for match in self.discovery_parser.parse_homepage(page.text, now):
                matches_by_event_id[match.event_id] = match
        return list(matches_by_event_id.values())

    def _should_capture_result(
        self,
        match: DiscoveredMatch,
        now: datetime,
        schedule_state: dict[str, datetime | str | None],
    ) -> bool:
        if schedule_state.get("result_captured_at") is not None:
            return False
        if match.timing_status != TimingStatus.FINISHED and match.status != "finished":
            return False
        if not match.kickoff_time or not match.live_score:
            return False
        age = now - match.kickoff_time
        return timedelta(0) <= age <= timedelta(hours=self.settings.result_capture_lookback_hours)

    async def _capture_result_backfill(self, now: datetime, skip_match_ids: set[str]) -> tuple[int, int]:
        checked = 0
        captured = 0
        candidates = self.database.list_result_backfill_candidates(
            now,
            self.settings.result_capture_lookback_hours,
            self.settings.result_finish_grace_minutes,
            self.settings.result_check_retry_seconds,
            self.settings.result_backfill_batch_size,
        )
        for match_id, match in candidates:
            if match_id in skip_match_ids:
                continue
            checked += 1
            checked_at = utc_now()
            try:
                html = await self._fetch_match_page_cached(
                    match.source_url,
                    CapturePriority.RESULT_RECOVERY,
                    "result_backfill",
                )
                finished, score = self.discovery_parser.parse_match_page_result(html)
                if finished and score:
                    captured += 1 if self.database.mark_result_captured(match_id, score, checked_at) else 0
                self.database.mark_result_checked(match_id, checked_at)
            except Exception as exc:
                self.database.mark_result_checked(match_id, checked_at)
                self.database.log(
                    "warning",
                    "capture",
                    "result_backfill_failed",
                    match.event_id,
                    {"error": str(exc), "source_url": match.source_url},
                )
            self._set_progress(results_checked=checked, results_captured=captured)
        return checked, captured

    async def _enrich_kickoff_from_match_page_if_needed(
        self,
        match: DiscoveredMatch,
        now: datetime,
        priority: CapturePriority | None = None,
        reason: str = "kickoff_enrichment",
    ) -> None:
        if not match.kickoff_time:
            return
        if abs((match.kickoff_time - now).total_seconds()) > (self.odds_capture_window_minutes + 180) * 60:
            return
        try:
            resolved_priority = priority or (
                CapturePriority.KICKOFF
                if abs((match.kickoff_time - now).total_seconds()) <= self.settings.final_capture_fast_window_minutes * 60
                else CapturePriority.UPCOMING
            )
            html = await self._fetch_match_page_cached(match.source_url, resolved_priority, reason)
            kickoff = self.discovery_parser.parse_match_page_start_time(html, self.settings.betexplorer_timezone_offset)
        except Exception as exc:
            self.database.log("warning", "capture", "kickoff_enrichment_failed", match.event_id, {"error": str(exc)})
            return
        if not kickoff:
            return
        if abs((kickoff - match.kickoff_time).total_seconds()) >= 60:
            self.database.log(
                "info",
                "capture",
                "kickoff_time_corrected",
                match.event_id,
                {"from": match.kickoff_time.isoformat(), "to": kickoff.isoformat()},
            )
            match.kickoff_time = kickoff

    async def _fetch_match_page_cached(
        self,
        source_url: str,
        priority: CapturePriority = CapturePriority.UPCOMING,
        reason: str = "match_page",
    ) -> str:
        now = utc_now()
        cached = self._match_page_cache.get(source_url)
        if cached and cached[0] > now:
            return cached[1]
        page = await self.ingest.submit(
            CaptureRequest(
                source_url,
                "html",
                priority,
                reason,
                request_kind="match_page",
            ),
            lambda: self.transport.fetch_match_page(source_url),
        )
        self._cache_match_page(source_url, page.text)
        return page.text

    def _cache_match_page(self, source_url: str, html: str) -> None:
        self._match_page_cache[source_url] = (utc_now() + timedelta(seconds=self.settings.market_discovery_cache_seconds), html)

    async def capture_match(
        self,
        match_id: str,
        event_id: str,
        source_url: str,
        priority: CapturePriority = CapturePriority.UPCOMING,
        reason: str = "monitor",
    ) -> bool:
        markets = await self._markets_for_match(source_url, priority, reason)
        market_semaphore = asyncio.Semaphore(max(1, self.settings.max_concurrent_markets_per_match))

        async def capture_market(market: str) -> tuple[bool, bool, str]:
            async with market_semaphore:
                return await self.capture_match_market(match_id, event_id, source_url, market, priority, reason)

        results = await asyncio.gather(*(capture_market(market) for market in markets))
        saved_any = any(saved for saved, _complete, _status in results)
        return saved_any

    async def capture_match_market(
        self,
        match_id: str,
        event_id: str,
        source_url: str,
        market: str,
        priority: CapturePriority = CapturePriority.UPCOMING,
        reason: str = "monitor",
    ) -> tuple[bool, bool, str]:
        saved = False
        unavailable_responses = 0
        technical_failures = 0
        for attempt in range(1, self.settings.max_retries_per_match + 1):
            started = utc_now()
            try:
                deadline = (
                    monotonic_time.monotonic() + self.settings.final_capture_poll_interval_seconds
                    if priority == CapturePriority.KICKOFF
                    else None
                )
                response = await self.ingest.submit(
                    CaptureRequest(event_id, market, priority, reason, deadline),
                    lambda: self.transport.fetch_match_odds(event_id, source_url, market),
                )
                raw_path = await asyncio.to_thread(
                    self._save_raw_payload,
                    event_id,
                    attempt,
                    market,
                    response.text,
                )
                odds = self.odds_parser.parse_match_odds_payload(response.text)
                diagnostics = self._odds_payload_diagnostics(response.text, odds)
                if not odds:
                    if diagnostics["no_data_message"]:
                        unavailable_responses += 1
                    else:
                        technical_failures += 1
                quality = classify_snapshot_quality(odds, self.settings.required_bookmakers)
                presence = required_bookmaker_presence(odds, self.settings.required_bookmakers)
                snapshot = OddsSnapshot(
                    event_id=event_id,
                    market=market,
                    captured_at=utc_now(),
                    quality_status=quality,
                    required_bookmakers=self.settings.required_bookmakers,
                    bookmaker_odds=odds,
                    raw_payload_path=str(raw_path),
                )
                await self.persistence.submit_capture(
                    AttemptWrite(
                        match_id=match_id,
                        event_id=event_id,
                        source_url=source_url,
                        attempt_number=attempt,
                        status=quality.value,
                        error_message=None,
                        required_found=presence,
                        started_at=started,
                        finished_at=utc_now(),
                        snapshot=snapshot,
                    )
                )
                saved = saved or bool(odds)
                self.database.log(
                    "info",
                    "capture",
                    "snapshot_saved",
                    event_id,
                    {
                        "market": market,
                        "quality": quality.value,
                        "bookmakers": len(odds),
                        **diagnostics,
                    },
                )
                if quality.value == "COMPLETE":
                    return True, True, "complete"
            except Exception as exc:
                technical_failures += 1
                try:
                    await self.persistence.submit_capture(
                        AttemptWrite(
                            match_id=match_id,
                            event_id=event_id,
                            source_url=source_url,
                            attempt_number=attempt,
                            status="ERROR",
                            error_message=str(exc),
                            required_found={},
                            started_at=started,
                            finished_at=utc_now(),
                        )
                    )
                except Exception as persistence_exc:
                    self.database.log(
                        "error",
                        "capture",
                        "attempt_persistence_failed",
                        event_id,
                        {"market": market, "attempt": attempt, "error": str(persistence_exc)},
                    )
                self.database.log("error", "capture", "capture_failed", event_id, {"market": market, "attempt": attempt, "error": str(exc)})
            if attempt < self.settings.max_retries_per_match:
                await asyncio.sleep(self.settings.retry_delay_seconds)
        if saved:
            return True, False, "partial"
        if unavailable_responses > 0 and technical_failures == 0:
            return False, False, "unavailable"
        return False, False, "failed"

    def _archive_odds_message(self, odds_status: str) -> str | None:
        if odds_status == "partial":
            return "Bwin/Unibet coverage is incomplete"
        if odds_status == "unavailable":
            return "BetExplorer reports no bookmaker odds for this match"
        if odds_status == "failed":
            return "Odds response could not be retrieved or parsed"
        return None

    async def _markets_for_match(
        self,
        source_url: str,
        priority: CapturePriority = CapturePriority.UPCOMING,
        reason: str = "market_discovery",
    ) -> list[str]:
        configured = self.settings.capture_market.strip().lower()
        if configured and configured != "all":
            return [configured]
        cached = self._markets_cache.get(source_url)
        now = utc_now()
        if cached and cached[0] > now:
            return cached[1]
        try:
            html = await self._fetch_match_page_cached(source_url, priority, reason)
            markets = self.odds_parser.parse_available_markets(html)
            resolved = markets or ["1x2"]
            expires_at = now + timedelta(seconds=self.settings.market_discovery_cache_seconds)
            self._markets_cache[source_url] = (expires_at, resolved)
            return resolved
        except Exception as exc:
            self.database.log("warning", "capture", "market_discovery_failed", details={"source_url": source_url, "error": str(exc)})
            return ["1x2"]

    def _save_raw_payload(self, event_id: str, attempt: int, market: str, payload: str) -> Path:
        self.settings.raw_snapshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().strftime("%Y%m%dT%H%M%S%f")
        safe_market = "".join(char if char.isalnum() else "_" for char in market)
        path = self.settings.raw_snapshot_dir / f"{event_id}_{safe_market}_{timestamp}_attempt{attempt}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as output:
            output.write(payload)
        self._cleanup_raw_payloads()
        return path

    def _cleanup_raw_payloads(self) -> None:
        now = monotonic_time.monotonic()
        if now - self._last_raw_cleanup_at < self.settings.raw_snapshot_cleanup_interval_seconds:
            return
        self._last_raw_cleanup_at = now
        files = [
            path
            for pattern in ("*.json", "*.json.gz")
            for path in self.settings.raw_snapshot_dir.rglob(pattern)
            if path.is_file()
        ]
        cutoff = utc_now().timestamp() - self.settings.raw_snapshot_retention_days * 86400
        for path in files:
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue
        remaining = sorted(
            (path for path in files if path.exists()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in remaining[self.settings.raw_snapshot_max_files :]:
            try:
                path.unlink()
            except OSError:
                pass

    def _odds_payload_diagnostics(self, payload: str, odds: list[Any]) -> dict[str, Any]:
        try:
            data = json.loads(payload)
            odds_html = str(data.get("odds", "")) if isinstance(data, dict) else ""
        except json.JSONDecodeError:
            odds_html = ""
        bookmaker_names = sorted({str(row.normalized_bookmaker) for row in odds if row.normalized_bookmaker})
        return {
            "payload_bytes": len(payload.encode("utf-8")),
            "odds_html_bytes": len(odds_html.encode("utf-8")),
            "no_data_message": "isn't any bookmaker offering odds" in odds_html,
            "parsed_bookmakers": bookmaker_names[:30],
        }
