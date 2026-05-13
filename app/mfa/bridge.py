"""In-memory future-based bridge for MFA code prompts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable


class MfaTimeout(TimeoutError):
    pass


class MfaAlreadySubmitted(RuntimeError):
    pass


class MfaUnknownSession(KeyError):
    pass


class MfaBridge:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}
        # callback hook the orchestrator wires up to emit SSE
        self._on_request: list[Callable[[str, str], None]] = []

    def on_request(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback called as ``callback(session_id, label)`` when a code is needed."""
        self._on_request.append(callback)

    async def request_code(self, session_id: str, label: str, timeout: float) -> str:
        if session_id in self._pending:
            raise RuntimeError(f"MFA already in flight for {session_id}")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[session_id] = fut
        for cb in self._on_request:
            cb(session_id, label)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError as e:
            raise MfaTimeout(f"MFA timeout for {session_id}") from e
        finally:
            self._pending.pop(session_id, None)

    def submit_code(self, session_id: str, code: str) -> None:
        fut = self._pending.get(session_id)
        if fut is None:
            raise MfaUnknownSession(f"No MFA in flight for {session_id}")
        if fut.done():
            raise MfaAlreadySubmitted(f"MFA already submitted for {session_id}")
        fut.set_result(code)
