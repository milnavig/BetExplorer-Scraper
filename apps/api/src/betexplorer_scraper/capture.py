from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .clock import utc_now
from .config import Settings
from .database import Database
from .models import DiscoveredMatch, OddsSnapshot, TimingStatus
from .parsers import DiscoveryParser, OddsParser
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
        self._last_discovery_at: datetime | None = None
        self._markets_cache: dict[str, tuple[datetime, list[str]]] = {}
        self._match_page_cache: dict[str, tuple[datetime, str]] = {}
        self._progress: dict[str, Any] = self._idle_progress()

    def progress_status(self) -> dict[str, Any]:
        return dict(self._progress)

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

    async def run_once(self, now: datetime | None = None, trigger: str = "manual", force_discovery: bool = True) -> dict[str, int]:
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
        async with self._run_lock:
            return await self._archive_football_date_locked(target_date)

    async def _archive_football_date_locked(self, target_date: date) -> dict[str, int]:
        archive_now = datetime.combine(target_date, time(23, 59))
        self._progress = {
            **self._idle_progress(),
            "running": True,
            "trigger": "archive_date",
            "phase": "archive_discovery",
            "started_at": utc_now().isoformat(),
        }
        page = await self.transport.fetch_football_date(target_date)
        parsed_matches = self.discovery_parser.parse_homepage(page.text, archive_now)
        matches = [
            match
            for match in parsed_matches
            if match.kickoff_time is not None and match.kickoff_time.date() == target_date
        ]
        discovered = len(matches)
        captured = 0
        complete = 0
        failed = 0
        results_captured = 0
        results_checked = 0
        self._set_progress(discovered=discovered, due=discovered, queued=discovered, phase="archive_capturing")

        for index, match in enumerate(matches, start=1):
            self._set_progress(active=1, completed=index - 1, current_event_id=match.event_id)
            await self._enrich_kickoff_from_match_page_if_needed(match, archive_now)
            match.timing_status = TimingStatus.FINISHED
            match.status = "finished"
            match_id = self.database.upsert_match(match)
            self.database.update_match_schedule(match_id, "FINALIZED", None, utc_now())
            saved, market_complete = await self.capture_match_market(match_id, match.event_id, match.source_url, "1x2")
            captured += 1 if saved else 0
            complete += 1 if market_complete else 0
            failed += 0 if saved else 1

            score = match.live_score
            if not score:
                results_checked += 1
                try:
                    match_page = await self._fetch_match_page_cached(match.source_url)
                    finished, parsed_score = self.discovery_parser.parse_match_page_result(match_page)
                    # Historical date pages are already past dates. Some archived match
                    # pages expose the full-time score without the structured Finished
                    # marker, so keeping the parsed score is safer than dropping it.
                    score = parsed_score if finished or parsed_score else None
                except Exception as exc:
                    self.database.log("warning", "archive", "archive_result_lookup_failed", match.event_id, {"error": str(exc)})
            if score and self.database.mark_result_captured(match_id, score, utc_now()):
                results_captured += 1
            self._set_progress(
                captured=captured,
                failed=failed,
                completed=index,
                results_captured=results_captured,
                results_checked=results_checked,
            )

        archive = self.database.archive_played_matches()
        recompute = self.database.recompute_historical_signals()
        result = {
            "date": target_date.isoformat(),
            "discovered": discovered,
            "captured": captured,
            "complete": complete,
            "failed": failed,
            "results_captured": results_captured,
            "results_checked": results_checked,
            "archived": archive["archived"],
            "signals": recompute["signals"],
            "matches_evaluated": recompute["matches_evaluated"],
        }
        self._set_progress(running=False, active=0, phase="archive_complete", finished_at=utc_now().isoformat())
        return result

    async def _run_once_locked(self, now: datetime | None = None, trigger: str = "manual", force_discovery: bool = True) -> dict[str, int]:
        now = now or datetime.now()
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
                live = await self.transport.fetch_live_results()
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
            self.database.update_match_schedule(match_id, decision.phase, decision.next_capture_at, decision.finalized_at)
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
        if capture_jobs:
            self._set_progress(phase="capturing", queued=len(capture_jobs), active=0, completed=0)
            semaphore = asyncio.Semaphore(max(1, self.settings.max_concurrent_captures))

            async def run_capture(job: tuple[str, str, str, datetime | None, str, datetime | None]) -> bool:
                nonlocal captured, failed
                match_id, event_id, source_url, next_capture_at, phase, finalized_at = job
                async with semaphore:
                    self._set_progress(active=self._progress["active"] + 1, current_event_id=event_id)
                    ok = await self.capture_match(match_id, event_id, source_url)
                    stored_phase = "FINALIZED" if finalized_at is not None else phase
                    self.database.mark_match_captured(match_id, utc_now(), next_capture_at, stored_phase, finalized_at)
                    captured += 1 if ok else 0
                    failed += 0 if ok else 1
                    self._set_progress(
                        active=max(0, self._progress["active"] - 1),
                        completed=self._progress["completed"] + 1,
                        captured=captured,
                        failed=failed,
                        current_event_id=event_id,
                    )
                    return ok

            results = await asyncio.gather(*(run_capture(job) for job in capture_jobs))
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
        pages = [await self.transport.fetch_homepage()]
        past_days = max(1, (self.settings.result_capture_lookback_hours + 23) // 24)
        future_days = max(self.settings.discovery_days_ahead, (self.settings.odds_capture_lookahead_hours + 23) // 24)
        for offset in range(-past_days, future_days + 1):
            target_date = (now + timedelta(days=offset)).date()
            try:
                pages.append(await self.transport.fetch_football_date(target_date))
            except NotImplementedError:
                continue
            except Exception as exc:
                self.database.log(
                    "warning",
                    "capture",
                    "date_discovery_failed",
                    details={"date": target_date.isoformat(), "error": str(exc)},
                )

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
                page = await self.transport.fetch_match_page(match.source_url)
                self._cache_match_page(match.source_url, page.text)
                finished, score = self.discovery_parser.parse_match_page_result(page.text)
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

    async def _enrich_kickoff_from_match_page_if_needed(self, match: DiscoveredMatch, now: datetime) -> None:
        if not match.kickoff_time:
            return
        if abs((match.kickoff_time - now).total_seconds()) > (self.odds_capture_window_minutes + 180) * 60:
            return
        try:
            html = await self._fetch_match_page_cached(match.source_url)
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

    async def _fetch_match_page_cached(self, source_url: str) -> str:
        now = utc_now()
        cached = self._match_page_cache.get(source_url)
        if cached and cached[0] > now:
            return cached[1]
        page = await self.transport.fetch_match_page(source_url)
        self._cache_match_page(source_url, page.text)
        return page.text

    def _cache_match_page(self, source_url: str, html: str) -> None:
        self._match_page_cache[source_url] = (utc_now() + timedelta(seconds=self.settings.market_discovery_cache_seconds), html)

    async def capture_match(self, match_id: str, event_id: str, source_url: str) -> bool:
        markets = await self._markets_for_match(source_url)
        market_semaphore = asyncio.Semaphore(max(1, self.settings.max_concurrent_markets_per_match))

        async def capture_market(market: str) -> tuple[bool, bool]:
            async with market_semaphore:
                return await self.capture_match_market(match_id, event_id, source_url, market)

        results = await asyncio.gather(*(capture_market(market) for market in markets))
        saved_any = any(saved for saved, _complete in results)
        return saved_any

    async def capture_match_market(self, match_id: str, event_id: str, source_url: str, market: str) -> tuple[bool, bool]:
        saved = False
        for attempt in range(1, self.settings.max_retries_per_match + 1):
            started = utc_now()
            try:
                response = await self.transport.fetch_match_odds(event_id, source_url, market)
                raw_path = self._save_raw_payload(event_id, attempt, market, response.text)
                odds = self.odds_parser.parse_match_odds_payload(response.text)
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
                self.database.save_snapshot(match_id, snapshot)
                saved = saved or bool(odds)
                self.database.save_attempt(match_id, event_id, source_url, attempt, quality.value, None, presence, started, utc_now())
                self.database.log(
                    "info",
                    "capture",
                    "snapshot_saved",
                    event_id,
                    {"market": market, "quality": quality.value, "bookmakers": len(odds)},
                )
                if quality.value == "COMPLETE":
                    return True, True
            except Exception as exc:
                self.database.save_attempt(match_id, event_id, source_url, attempt, "ERROR", str(exc), {}, started, utc_now())
                self.database.log("error", "capture", "capture_failed", event_id, {"market": market, "attempt": attempt, "error": str(exc)})
            if attempt < self.settings.max_retries_per_match:
                await asyncio.sleep(self.settings.retry_delay_seconds)
        return saved, False

    async def _markets_for_match(self, source_url: str) -> list[str]:
        configured = self.settings.capture_market.strip().lower()
        if configured and configured != "all":
            return [configured]
        cached = self._markets_cache.get(source_url)
        now = utc_now()
        if cached and cached[0] > now:
            return cached[1]
        try:
            html = await self._fetch_match_page_cached(source_url)
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
        path = self.settings.raw_snapshot_dir / f"{event_id}_{safe_market}_{timestamp}_attempt{attempt}.json"
        path.write_text(payload, encoding="utf-8")
        return path
