"""Per-session async event bus used to fan out progress + MFA prompts to SSE."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Event]] = {}

    def _queue(self, session_id: str) -> asyncio.Queue[Event]:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]

    def publish(self, session_id: str, event: Event) -> None:
        self._queue(session_id).put_nowait(event)

    async def subscribe(self, session_id: str) -> AsyncIterator[Event]:
        q = self._queue(session_id)
        while True:
            ev = await q.get()
            yield ev
            if ev.type in ("done", "error"):
                # leave queue in place briefly in case of reconnect; orchestrator decides cleanup
                pass
