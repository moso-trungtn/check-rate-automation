"""SSE event stream."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter()


@router.get("/events/stream")
async def stream(request: Request, session_id: str) -> EventSourceResponse:
    bus = request.app.state.bus

    async def generator() -> AsyncIterator[dict[str, Any]]:
        async for ev in bus.subscribe(session_id):
            yield {"event": ev.type, "data": json.dumps(ev.data)}
            if ev.type in ("done", "error"):
                break

    return EventSourceResponse(generator())
