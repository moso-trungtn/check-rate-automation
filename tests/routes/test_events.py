from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.events.bus import Event, EventBus
from app.main import create_app


def test_sse_streams_buffered_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "h.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    with TestClient(app) as c:
        bus = EventBus()
        cast(Any, app.state).bus = bus
        # Pre-buffer events; the generator will yield them and then exit on "done"
        bus.publish("sess1", Event(type="progress", data={"step": "moso_pricing"}))
        bus.publish("sess1", Event(type="done", data={"report_id": "r1"}))
        r = c.get("/events/stream?session_id=sess1")
        assert r.status_code == 200
        body = r.text
        assert "progress" in body
        assert "done" in body
        assert "r1" in body
