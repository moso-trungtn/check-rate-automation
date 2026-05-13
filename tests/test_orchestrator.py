"""Tests for the comparison orchestrator."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.events.bus import EventBus
from app.mfa.bridge import MfaBridge
from app.models import (
    Adjustment,
    LoanType,
    MosoResult,
    Occupancy,
    PortalResult,
    PropertyType,
    Purpose,
    Scenario,
)
from app.orchestrator import Orchestrator


def _scenario() -> Scenario:
    return Scenario(
        loan_amount=Decimal("400000"),
        credit_score=740,
        property_value=Decimal("500000"),
        ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY,
        property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE,
        loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL,
        target_rate=Decimal("6.875"),
    )


@pytest.mark.asyncio
async def test_run_comparison_happy_path(tmp_path: Any) -> None:
    moso_facade = AsyncMock()
    moso_facade.quote.return_value = MosoResult(
        base_price=Decimal("100"),
        adjustment_total=Decimal("-0.25"),
        final_price=Decimal("99.75"),
        adjustments=[Adjustment(label="X", amount=Decimal("-0.25"))],
    )

    portal_result = PortalResult(
        final_price=Decimal("99.75"),
        adjustments=[Adjustment(label="X", amount=Decimal("-0.25"))],
        raw_html_snapshot_path="/tmp/x.html",
        captured_at=datetime(2026, 5, 13),
    )
    adapter = AsyncMock()
    adapter.ensure_logged_in = AsyncMock()
    adapter.fill_scenario = AsyncMock()
    adapter.submit = AsyncMock()
    adapter.parse_result = AsyncMock(return_value=portal_result)

    browser = MagicMock()
    ctx = MagicMock()
    ctx.new_page = AsyncMock()
    ctx.storage_state = AsyncMock()
    ctx.close = AsyncMock()
    browser.new_context = AsyncMock(return_value=ctx)

    bus = EventBus()
    mfa = MfaBridge()
    secrets = MagicMock()
    secrets.get.side_effect = FileNotFoundError("no creds file")

    orch = Orchestrator(
        moso_facade=cast(Any, moso_facade),
        adapter_factory=lambda _lender: cast(Any, adapter),
        browser=browser,
        bus=bus,
        mfa_bridge=mfa,
        secrets=cast(Any, secrets),
        tolerance=Decimal("0.001"),
        reports_dir=tmp_path,
        sessions_dir=tmp_path / "sessions",
    )

    report = await orch.run("sess1", _scenario(), lender="ad_mortgage")
    assert report.matches is True
    moso_facade.quote.assert_awaited_once()
    adapter.fill_scenario.assert_awaited_once()
    adapter.submit.assert_awaited_once()
    adapter.parse_result.assert_awaited_once()

    # Report file persisted
    assert (tmp_path / f"{report.id}.json").exists()
