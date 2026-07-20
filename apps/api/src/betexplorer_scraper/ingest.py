from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Awaitable, Callable, Generic, TypeVar


T = TypeVar("T")


class CapturePriority(IntEnum):
    KICKOFF = 0
    UPCOMING = 10
    RESULT_RECOVERY = 20
    MANUAL = 30
    BACKFILL = 40


@dataclass(slots=True)
class CaptureRequest:
    event_id: str
    market: str
    priority: CapturePriority
    reason: str
    deadline: float | None = None
    request_kind: str = "odds"

    @property
    def dedupe_key(self) -> tuple[str, str, str]:
        return self.request_kind, self.event_id, self.market.lower()


@dataclass(order=True)
class _QueueItem(Generic[T]):
    priority: int
    sequence: int
    enqueued_at: float = field(compare=False)
    request: CaptureRequest = field(compare=False)
    operation: Callable[[], Awaitable[T]] = field(compare=False)
    future: asyncio.Future[T] = field(compare=False)


class IngestCoordinator:
    def __init__(self, max_concurrency: int, queue_size: int = 512) -> None:
        self.max_concurrency = max(2, max_concurrency)
        self._adaptive_limit = self.max_concurrency
        self._queue: asyncio.PriorityQueue[_QueueItem[object]] = asyncio.PriorityQueue(maxsize=max(32, queue_size))
        self._kickoff_queue: asyncio.PriorityQueue[_QueueItem[object]] = asyncio.PriorityQueue(maxsize=64)
        self._pending: dict[tuple[str, str, str], asyncio.Future[object]] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._sequence = 0
        self._condition = asyncio.Condition()
        self._active = 0
        self._healthy = 0
        self._cooldown_until = 0.0
        self._completed = 0
        self._failed = 0
        self._started_at = time.monotonic()

    async def submit(self, request: CaptureRequest, operation: Callable[[], Awaitable[T]]) -> T:
        self._ensure_workers()
        key = request.dedupe_key
        existing = self._pending.get(key)
        if existing is not None:
            return await asyncio.shield(existing)  # type: ignore[return-value]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        self._pending[key] = future  # type: ignore[assignment]
        self._sequence += 1
        target_queue = self._kickoff_queue if request.priority == CapturePriority.KICKOFF else self._queue
        await target_queue.put(
            _QueueItem(
                int(request.priority),
                self._sequence,
                time.monotonic(),
                request,
                operation,
                future,
            )
        )
        return await asyncio.shield(future)

    def metrics(self) -> dict[str, object]:
        queued = [*self._kickoff_queue._queue, *self._queue._queue]
        oldest = max((time.monotonic() - item.enqueued_at for item in queued), default=0.0)
        elapsed = max(0.001, time.monotonic() - self._started_at)
        return {
            "queue_depth": self._queue.qsize() + self._kickoff_queue.qsize(),
            "queue_capacity": self._queue.maxsize + self._kickoff_queue.maxsize,
            "kickoff_queue_depth": self._kickoff_queue.qsize(),
            "oldest_item_seconds": round(oldest, 2),
            "active_workers": self._active,
            "adaptive_concurrency": self._adaptive_limit,
            "max_concurrency": self.max_concurrency,
            "completed": self._completed,
            "failed": self._failed,
            "throughput_per_minute": round(self._completed * 60 / elapsed, 2),
        }

    async def close(self) -> None:
        workers = list(self._workers)
        self._workers.clear()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    def _ensure_workers(self) -> None:
        if self._workers:
            return
        self._workers = [asyncio.create_task(self._worker(self._kickoff_queue))]
        self._workers.extend(
            asyncio.create_task(self._worker(self._queue)) for _ in range(max(1, self.max_concurrency - 1))
        )

    async def _worker(self, queue: asyncio.PriorityQueue[_QueueItem[object]]) -> None:
        while True:
            item = await queue.get()
            key = item.request.dedupe_key
            try:
                if item.request.deadline is not None and time.monotonic() > item.request.deadline:
                    raise TimeoutError(f"Capture deadline expired for {item.request.event_id}")
                await self._enter_slot(item.request.priority)
                try:
                    result = await item.operation()
                    status = int(getattr(result, "status_code", 200))
                    if status == 429 or status >= 500:
                        await self._record_failure()
                    else:
                        await self._record_success()
                    if not item.future.done():
                        item.future.set_result(result)
                    self._completed += 1
                finally:
                    await self._leave_slot()
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.cancel()
                raise
            except Exception as exc:
                self._failed += 1
                await self._record_failure()
                if not item.future.done():
                    item.future.set_exception(exc)
            finally:
                self._pending.pop(key, None)
                queue.task_done()

    async def _enter_slot(self, priority: CapturePriority) -> None:
        while True:
            delay = max(0.0, self._cooldown_until - time.monotonic())
            if delay:
                await asyncio.sleep(delay)
            async with self._condition:
                reserve = 0 if priority == CapturePriority.KICKOFF else 1
                allowed = max(1, self._adaptive_limit - reserve)
                if self._active < allowed:
                    self._active += 1
                    return
                await self._condition.wait()

    async def _leave_slot(self) -> None:
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    async def _record_failure(self) -> None:
        async with self._condition:
            self._adaptive_limit = max(2, self._adaptive_limit // 2)
            self._healthy = 0
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + 2.0)
            self._condition.notify_all()

    async def _record_success(self) -> None:
        async with self._condition:
            self._healthy += 1
            if self._healthy >= 20 and self._adaptive_limit < self.max_concurrency:
                self._adaptive_limit += 1
                self._healthy = 0
                self._condition.notify_all()
