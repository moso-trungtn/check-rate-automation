from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.mfa.bridge import MfaBridge


def _make_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "h.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    return create_app()


def test_post_mfa_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as c:
        bridge = MfaBridge()
        cast(Any, app.state).mfa = bridge
        # Pre-register a pending future to simulate request_code in flight.
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        bridge._pending["sess1"] = fut  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        r = c.post("/mfa/sess1/code", json={"code": "987654"})
        assert r.status_code == 200
        assert r.json() == {"status": "accepted"}
        # The future was set by submit_code
        assert fut.done()
        assert fut.result() == "987654"


def test_post_mfa_unknown_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as c:
        cast(Any, app.state).mfa = MfaBridge()
        r = c.post("/mfa/sess-nope/code", json={"code": "x"})
        assert r.status_code == 404


def test_post_mfa_already_submitted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with TestClient(app) as c:
        bridge = MfaBridge()
        cast(Any, app.state).mfa = bridge
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        fut.set_result("first")
        bridge._pending["sess2"] = fut  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        r = c.post("/mfa/sess2/code", json={"code": "second"})
        assert r.status_code == 409
