from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from app.config import Settings


def _make_settings() -> Settings:
    # pydantic-settings reads required fields from env at runtime; cast to
    # silence pyright strict reportCallIssue for the no-arg construction.
    return cast(Any, Settings)()


def test_settings_reads_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSO_BASE_URL", "https://example.com")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "moso-headers.json"))
    monkeypatch.setenv("COMPARE_TOLERANCE", "0.01")
    s = _make_settings()
    assert s.moso_base_url == "https://example.com"
    assert s.moso_headers_file == tmp_path / "moso-headers.json"
    assert s.compare_tolerance == Decimal("0.01")


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "h.json"))
    monkeypatch.delenv("COMPARE_TOLERANCE", raising=False)
    s = _make_settings()
    assert s.compare_tolerance == Decimal("0.001")
