"""Tests for /compare and /report endpoints."""
from __future__ import annotations

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
