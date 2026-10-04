"""Event bus: persists activity events and fans them out to live subscribers (SSE).

``emit`` is safe to call from the event-loop thread and from worker threads.
Ephemeral events (e.g. token-progress ticks) are broadcast but not stored.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from .db import Store
from .log import get_logger
from .util import iso, utcnow

log = get_logger("events")


class EventBus:
    def __init__(self, store: Store):
        self.store = store
        self._subscribers: set[tuple[asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add((q, asyncio.get_running_loop()))
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers = {pair for pair in self._subscribers if pair[0] is not q}

    def emit(
        self,
        project_id: str | None,
        type: str,
        message: str,
        *,
        agent: str | None = None,
        task_id: str | None = None,
        level: str = "info",
        data: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        if persist:
            row = self.store.add_event(
                project_id=project_id,
                type=type,
                message=message,
                agent=agent,
                task_id=task_id,
                level=level,
                data=data or {},
            )
            payload = row.to_dict()
            log_fn = log.warning if level in ("warning", "error") else log.info
            log_fn(message, extra={"project_id": project_id, "task_id": task_id, "agent": agent})
        else:
            payload = {
                "id": None,
                "project_id": project_id,
                "ts": iso(utcnow()),
                "type": type,
                "level": level,
                "agent": agent,
                "task_id": task_id,
                "message": message,
                "data": data or {},
            }
        self._broadcast(payload)
        return payload

    def _broadcast(self, payload: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q, loop in subscribers:
            try:
                loop.call_soon_threadsafe(self._put_nowait, q, payload)
            except RuntimeError:  # loop closed
                self.unsubscribe(q)

    @staticmethod
    def _put_nowait(q: asyncio.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
        if q.full():  # slow consumer: drop the oldest event rather than block producers
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(payload)
