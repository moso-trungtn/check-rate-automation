"""Tests for /compare and /report endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_post_compare_returns_session_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object,
) -> None:
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path) + "/headers.json")
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    payload = {
        "lender": "ad_mortgage",
        "scenario": {
            "loan_amount": 400000,
            "credit_score": 740,
            "property_value": 500000,
            "ltv": 80,
            "occupancy": "primary_residence",
            "property_type": "single_family",
            "purpose": "purchase",
            "loan_program": "30yr Fixed Conv",
            "loan_type": "conventional",
            "target_rate": 6.875,
        },
    }
    with TestClient(app) as c:
        # State must be set AFTER lifespan enters (inside the with block).
        app.state.orchestrator = AsyncMock()
        r = c.post("/compare", json=payload)
        assert r.status_code == 202
        body = r.json()
        assert "session_id" in body


def test_get_report_404_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "h.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    with TestClient(app) as c:
        # cast Any: pyright doesn't know app.state can take a data_dir override
        cast(Any, app.state).settings.data_dir = tmp_path
        r = c.get("/report/abcdef012345")
        assert r.status_code == 404


def test_get_report_returns_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "h.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "abcdef012345.json").write_text('{"id": "abcdef012345", "matches": true}')
    with TestClient(app) as c:
        cast(Any, app.state).settings.data_dir = tmp_path
        r = c.get("/report/abcdef012345")
        assert r.status_code == 200
        assert r.json() == {"id": "abcdef012345", "matches": True}


def test_get_report_rejects_path_traversal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "h.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/report/..%2F..%2Fetc%2Fpasswd")
        # FastAPI's path converter rejects raw / first, but for any non-hex-12, return 400
        assert r.status_code in (400, 404)
