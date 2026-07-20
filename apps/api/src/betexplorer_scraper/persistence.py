from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Generic, TypeVar

from .models import OddsSnapshot

if TYPE_CHECKING:
    from .database import Database


T = TypeVar("T")


@dataclass(slots=True)
class AttemptWrite:
    match_id: str
    event_id: str
    source_url: str
    attempt_number: int
    status: str
    error_message: str | None
    required_found: dict[str, bool]
    started_at: datetime
    finished_at: datetime
    snapshot: OddsSnapshot | None = None


@dataclass(slots=True)
class ScheduleWrite:
    match_id: str
    capture_phase: str
    next_capture_at: datetime | None
    finalized_at: datetime | None = None
    captured_at: datetime | None = None


@dataclass(slots=True)
class _WriteItem(Generic[T]):
    kind: str
    payload: T
    future: asyncio.Future[str | None]


class PersistenceCoordinator:
    def __init__(
        self,
        database: Database,
        batch_size: int = 16,
        flush_interval_ms: int = 25,
        queue_size: int = 512,
    ) -> None:
        self.database = database
        self.batch_size = max(1, batch_size)
        self.flush_interval_seconds = max(0.001, flush_interval_ms / 1000)
        self._queue: asyncio.Queue[_WriteItem[object]] = asyncio.Queue(maxsize=max(32, queue_size))
        self._worker: asyncio.Task[None] | None = None
        self._batches = 0
        self._written = 0
        self._failed = 0

    async def submit_capture(self, write: AttemptWrite) -> str | None:
        return await self._submit("capture", write)

    async def submit_schedule(self, write: ScheduleWrite) -> None:
        await self._submit("schedule", write)

    def metrics(self) -> dict[str, int]:
        return {
            "queue_depth": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "batches": self._batches,
            "written": self._written,
            "failed": self._failed,
        }

    async def close(self) -> None:
        if self._worker is None:
            return
        await self._queue.join()
        self._worker.cancel()
        await asyncio.gather(self._worker, return_exceptions=True)
        self._worker = None

    async def _submit(self, kind: str, payload: object) -> str | None:
        self._ensure_worker()
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        await self._queue.put(_WriteItem(kind, payload, future))
        return await asyncio.shield(future)

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            items = [first]
            deadline = asyncio.get_running_loop().time() + self.flush_interval_seconds
            while len(items) < self.batch_size:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    items.append(await asyncio.wait_for(self._queue.get(), timeout))
                except TimeoutError:
                    break

            captures = [item.payload for item in items if item.kind == "capture"]
            schedules = [item.payload for item in items if item.kind == "schedule"]
            try:
                snapshot_ids = await asyncio.to_thread(
                    self.database.persist_capture_batch,
                    captures,
                    schedules,
                )
                capture_index = 0
                for item in items:
                    result = None
                    if item.kind == "capture":
                        result = snapshot_ids[capture_index]
                        capture_index += 1
                    if not item.future.done():
                        item.future.set_result(result)
                self._batches += 1
                self._written += len(items)
            except Exception as exc:
                self._failed += len(items)
                for item in items:
                    if not item.future.done():
                        item.future.set_exception(exc)
            finally:
                for _item in items:
                    self._queue.task_done()
