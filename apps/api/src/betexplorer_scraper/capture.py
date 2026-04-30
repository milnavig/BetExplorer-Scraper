from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from .clock import utc_now
from .config import Settings
from .database import Database
from .models import OddsSnapshot
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
        self.discovery_parser = DiscoveryParser(settings.betexplorer_base_url)
        self.odds_parser = OddsParser()
        self.scheduler = Scheduler(
            SchedulerConfig(
                upcoming_window_minutes=settings.upcoming_window_minutes,
                recently_started_window_minutes=settings.recently_started_window_minutes,
                max_match_age_after_kickoff_minutes=settings.max_match_age_after_kickoff_minutes,
                final_capture_poll_interval_seconds=settings.final_capture_poll_interval_seconds,
                discovery_poll_interval_seconds=settings.discovery_poll_interval_seconds,
            )
        )

    async def run_once(self, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now()
        matches = await self._discover_matches(now)
        try:
            live = await self.transport.fetch_live_results()
            matches = self.discovery_parser.apply_live_results(matches, live.text)
        except Exception as exc:
            self.database.log("warning", "capture", "live_results_failed", details={"error": str(exc)})

        captured = 0
        failed = 0
        due = 0
        skipped = 0
        finalized = 0
        waiting = 0
        capture_jobs: list[tuple[str, str, str, datetime | None, str, datetime | None]] = []
        for match in matches:
            match.timing_status = classify_timing(
                match.kickoff_time,
                now,
                self.settings.upcoming_window_minutes,
                self.settings.recently_started_window_minutes,
                is_live=match.timing_status.value == "LIVE",
                is_finished=match.timing_status.value == "FINISHED",
            )
            match_id = self.database.upsert_match(match)
            schedule_state = self.database.get_match_schedule(match_id)
            decision = self.scheduler.plan(
                match,
                now,
                next_capture_at=schedule_state["next_capture_at"],
                finalized_at=schedule_state["finalized_at"],
            )
            self.database.update_match_schedule(match_id, decision.phase, decision.next_capture_at, decision.finalized_at)
            if not decision.should_capture:
                skipped += 1
                finalized += 1 if decision.phase == "FINALIZED" else 0
                waiting += 1 if decision.phase in {"WAITING", "DISCOVERY_ONLY"} else 0
                continue
            due += 1
            capture_jobs.append((match_id, match.event_id, match.source_url, decision.next_capture_at, decision.phase, decision.finalized_at))
        if capture_jobs:
            semaphore = asyncio.Semaphore(max(1, self.settings.max_concurrent_captures))

            async def run_capture(job: tuple[str, str, str, datetime | None, str, datetime | None]) -> bool:
                match_id, event_id, source_url, next_capture_at, phase, finalized_at = job
                async with semaphore:
                    ok = await self.capture_match(match_id, event_id, source_url)
                    self.database.mark_match_captured(match_id, utc_now(), next_capture_at, phase, finalized_at)
                    return ok

            results = await asyncio.gather(*(run_capture(job) for job in capture_jobs))
            captured = sum(1 for ok in results if ok)
            failed = len(results) - captured
        result = {
            "discovered": len(matches),
            "due": due,
            "captured": captured,
            "failed": failed,
            "skipped": skipped,
            "finalized": finalized,
            "waiting": waiting,
        }
        self.database.log("info", "capture", "run_once_completed", details=result)
        return result

    async def _discover_matches(self, now: datetime) -> list:
        pages = [await self.transport.fetch_homepage()]
        for offset in range(self.settings.discovery_days_ahead + 1):
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

    async def capture_match(self, match_id: str, event_id: str, source_url: str) -> bool:
        for attempt in range(1, self.settings.max_retries_per_match + 1):
            started = utc_now()
            try:
                response = await self.transport.fetch_match_odds(event_id, source_url, self.settings.capture_market)
                raw_path = self._save_raw_payload(event_id, attempt, response.text)
                odds = self.odds_parser.parse_match_odds_payload(response.text)
                quality = classify_snapshot_quality(odds, self.settings.required_bookmakers)
                presence = required_bookmaker_presence(odds, self.settings.required_bookmakers)
                snapshot = OddsSnapshot(
                    event_id=event_id,
                    market=self.settings.capture_market,
                    captured_at=utc_now(),
                    quality_status=quality,
                    required_bookmakers=self.settings.required_bookmakers,
                    bookmaker_odds=odds,
                    raw_payload_path=str(raw_path),
                )
                self.database.save_snapshot(match_id, snapshot)
                self.database.save_attempt(match_id, event_id, source_url, attempt, quality.value, None, presence, started, utc_now())
                self.database.log("info", "capture", "snapshot_saved", event_id, {"quality": quality.value, "bookmakers": len(odds)})
                if quality.value == "COMPLETE":
                    return True
            except Exception as exc:
                self.database.save_attempt(match_id, event_id, source_url, attempt, "ERROR", str(exc), {}, started, utc_now())
                self.database.log("error", "capture", "capture_failed", event_id, {"attempt": attempt, "error": str(exc)})
            if attempt < self.settings.max_retries_per_match:
                await asyncio.sleep(self.settings.retry_delay_seconds)
        return False

    def _save_raw_payload(self, event_id: str, attempt: int, payload: str) -> Path:
        self.settings.raw_snapshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().strftime("%Y%m%dT%H%M%S%f")
        path = self.settings.raw_snapshot_dir / f"{event_id}_{timestamp}_attempt{attempt}.json"
        path.write_text(payload, encoding="utf-8")
        return path
