from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
from typing import Literal

from .models import (
    AppSnapshot,
    CourseCandidate,
    CourseTarget,
    Event,
    EventLevel,
    RuntimeConfig,
    SchedulerPhase,
    TargetStatus,
    TaskPhase,
)

StreamMessage = tuple[Literal["snapshot", "event"], dict[str, object]]


class AppState:
    def __init__(self) -> None:
        self.snapshot = AppSnapshot()
        self._event_id = 0
        self._history: deque[Event] = deque(maxlen=500)
        self._subscribers: set[asyncio.Queue[StreamMessage]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[StreamMessage]:
        queue: asyncio.Queue[StreamMessage] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
            queue.put_nowait(("snapshot", self.snapshot.model_dump(mode="json")))
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[StreamMessage]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish_snapshot(self) -> None:
        await self._broadcast("snapshot", self.snapshot.model_dump(mode="json"))

    async def _broadcast(self, kind: Literal["snapshot", "event"], data: dict[str, object]) -> None:
        async with self._lock:
            for queue in tuple(self._subscribers):
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait((kind, data))

    async def add_event(self, level: str, category: str, message: str) -> Event:
        self._event_id += 1
        event = Event(
            id=self._event_id, level=EventLevel(level), category=category, message=message
        )
        self._history.append(event)
        self.snapshot.events = list(self._history)
        await self._broadcast("event", event.model_dump(mode="json"))
        return event

    async def configure(self, runtime: RuntimeConfig, targets: list[CourseTarget]) -> None:
        self.snapshot.runtime = runtime
        self.snapshot.targets = targets
        known = {status.target_id: status for status in self.snapshot.statuses}
        self.snapshot.statuses = [
            known.get(item.id, TargetStatus(target_id=item.id)) for item in targets
        ]
        await self.publish_snapshot()

    async def set_status(self, target_id: str, phase: TaskPhase, message: str) -> None:
        status = next(
            (item for item in self.snapshot.statuses if item.target_id == target_id), None
        )
        if status is None:
            status = TargetStatus(target_id=target_id)
            self.snapshot.statuses.append(status)
        status.phase = phase
        status.message = message
        status.updated_at = datetime.now(UTC)
        await self.publish_snapshot()

    async def set_candidates(self, candidates: list[CourseCandidate]) -> None:
        self.snapshot.candidates = candidates
        await self.publish_snapshot()

    async def set_catalog(
        self,
        candidates: list[CourseCandidate],
        module_counts: dict[str, int] | None = None,
        module_errors: dict[str, str] | None = None,
        loaded_at: datetime | None = None,
    ) -> None:
        self.snapshot.catalog_candidates = candidates
        self.snapshot.catalog_module_counts = module_counts or {}
        self.snapshot.catalog_module_errors = module_errors or {}
        self.snapshot.catalog_loaded_at = loaded_at
        await self.publish_snapshot()

    async def set_scheduler(self, phase: SchedulerPhase) -> None:
        self.snapshot.scheduler = phase
        await self.publish_snapshot()
