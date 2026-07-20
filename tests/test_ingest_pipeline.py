from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from betexplorer_scraper.ingest import CapturePriority, CaptureRequest, IngestCoordinator
from betexplorer_scraper.persistence import AttemptWrite, PersistenceCoordinator, ScheduleWrite
from betexplorer_scraper.transport import RawResponse


@pytest.mark.asyncio
async def test_ingest_deduplicates_same_event_market_and_reason() -> None:
    coordinator = IngestCoordinator(max_concurrency=2, queue_size=8)
    calls = 0

    async def fetch() -> RawResponse:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return RawResponse("test", "{}", 200)

    request = CaptureRequest("event", "1x2", CapturePriority.UPCOMING, "monitor")
    first, second = await asyncio.gather(
        coordinator.submit(request, fetch),
        coordinator.submit(request, fetch),
    )
    await coordinator.close()

    assert calls == 1
    assert first is second


@pytest.mark.asyncio
async def test_kickoff_capture_uses_reserved_slot_during_backfill() -> None:
    coordinator = IngestCoordinator(max_concurrency=2, queue_size=16)
    release = asyncio.Event()
    kickoff_finished = asyncio.Event()

    async def backfill() -> RawResponse:
        await release.wait()
        return RawResponse("backfill", "{}", 200)

    async def kickoff() -> RawResponse:
        kickoff_finished.set()
        return RawResponse("kickoff", "{}", 200)

    backfills = [
        asyncio.create_task(
            coordinator.submit(
                CaptureRequest(f"old-{index}", "1x2", CapturePriority.BACKFILL, "backfill"),
                backfill,
            )
        )
        for index in range(4)
    ]
    await asyncio.sleep(0.02)
    live = asyncio.create_task(
        coordinator.submit(
            CaptureRequest("live", "1x2", CapturePriority.KICKOFF, "monitor"),
            kickoff,
        )
    )
    await asyncio.wait_for(kickoff_finished.wait(), timeout=0.5)
    release.set()
    await asyncio.gather(*backfills, live)
    await coordinator.close()

    assert kickoff_finished.is_set()


@pytest.mark.asyncio
async def test_match_page_requests_dedupe_across_consumers() -> None:
    coordinator = IngestCoordinator(max_concurrency=2, queue_size=8)
    calls = 0

    async def fetch() -> RawResponse:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return RawResponse("match", "<html></html>", 200)

    first, second = await asyncio.gather(
        coordinator.submit(
            CaptureRequest("match-url", "html", CapturePriority.UPCOMING, "kickoff", request_kind="match_page"),
            fetch,
        ),
        coordinator.submit(
            CaptureRequest(
                "match-url",
                "html",
                CapturePriority.RESULT_RECOVERY,
                "result",
                request_kind="match_page",
            ),
            fetch,
        ),
    )
    await coordinator.close()

    assert calls == 1
    assert first is second


@pytest.mark.asyncio
async def test_persistence_coordinator_batches_multiple_matches() -> None:
    class RecordingDatabase:
        def __init__(self) -> None:
            self.calls: list[tuple[list[object], list[object]]] = []

        def persist_capture_batch(self, captures: list[object], schedules: list[object]) -> list[str | None]:
            self.calls.append((captures, schedules))
            return [None for _capture in captures]

    database = RecordingDatabase()
    coordinator = PersistenceCoordinator(database, batch_size=8, flush_interval_ms=20, queue_size=16)  # type: ignore[arg-type]
    now = datetime(2026, 7, 18, 12, 0)

    await asyncio.gather(
        coordinator.submit_capture(AttemptWrite("m1", "e1", "u1", 1, "ERROR", "x", {}, now, now)),
        coordinator.submit_capture(AttemptWrite("m2", "e2", "u2", 1, "ERROR", "x", {}, now, now)),
        coordinator.submit_schedule(ScheduleWrite("m1", "FINALIZING", now)),
    )
    await coordinator.close()

    assert len(database.calls) == 1
    captures, schedules = database.calls[0]
    assert {write.match_id for write in captures} == {"m1", "m2"}
    assert [write.match_id for write in schedules] == ["m1"]
