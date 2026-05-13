"""Route tests for /moso/session/from-curl and /moso/session/status."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("MOSO_BASE_URL", "https://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "moso-headers.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    return create_app()


_CURL = (
    "curl 'https://www.viet18.com/exec/GetRatesOp' "
    "-H 'xsrf: abc-123' "
    "-H 'user: u@x' "
    "-H 'x-sdk-namespace: 5716' "
    "-b 'JSESSIONID=xyz' "
    "-H 'content-type: application/json'"
)


def test_from_curl_writes_file_and_returns_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app = _setup(monkeypatch, tmp_path)
    with TestClient(app) as c:
        r = c.post("/moso/session/from-curl", json={"curl": _CURL})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "XSRF" in body["saved_keys"]
        assert "user" in body["saved_keys"]
        assert "Cookie" in body["saved_keys"]
        # File now exists with the same keys.
        path = tmp_path / "moso-headers.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["XSRF"] == "abc-123"
        assert data["user"] == "u@x"
        assert data["Cookie"] == "JSESSIONID=xyz"


def test_from_curl_invalid_input_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app = _setup(monkeypatch, tmp_path)
    with TestClient(app) as c:
        # Plain prose — no curl keyword in first 200 chars.
        r = c.post("/moso/session/from-curl", json={"curl": "just some prose"})
        assert r.status_code == 400
        assert "cURL" in r.json()["detail"]


def test_status_returns_keys_when_file_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app = _setup(monkeypatch, tmp_path)
    (tmp_path / "moso-headers.json").write_text(
        json.dumps({"XSRF": "x", "user": "u"}),
    )
    with TestClient(app) as c:
        r = c.get("/moso/session/status")
        assert r.status_code == 200
        body = r.json()
        assert body["present"] is True
        assert "XSRF" in body["keys"]
        assert "user" in body["keys"]


def test_status_when_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    app = _setup(monkeypatch, tmp_path)
    with TestClient(app) as c:
        r = c.get("/moso/session/status")
        assert r.status_code == 200
        assert r.json() == {"present": False, "keys": []}


def test_from_curl_hotswaps_facade_headers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """If a MosoFacade is on app.state, save updates its client.headers live."""
    app = _setup(monkeypatch, tmp_path)
    with TestClient(app) as c:
        # Pre-populate a fake facade onto app.state.
        class FakeClient:
            headers: dict[str, str] = {"XSRF": "old"}
        class FakeFacade:
            client = FakeClient()
        fake = FakeFacade()
        app.state.moso_facade = fake
        r = c.post("/moso/session/from-curl", json={"curl": _CURL})
        assert r.status_code == 200
        assert fake.client.headers["XSRF"] == "abc-123"
        assert fake.client.headers["Cookie"] == "JSESSIONID=xyz"
