"""Tests for app.main FastAPI factory."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_app_starts_and_returns_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "headers.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "test")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "check-rate" in r.text.lower()
