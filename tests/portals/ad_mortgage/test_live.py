"""Live smoke test against the real AD Mortgage portal.

Run with:
    CHECK_RATE_PASSPHRASE=... uv run pytest tests/portals/ad_mortgage/test_live.py -m live -v
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.async_api import async_playwright

import app.portals.ad_mortgage  # noqa: F401 — register adapter  # pyright: ignore[reportUnusedImport]
from app.mfa.bridge import MfaBridge
from app.models import (
    LoanType,
    Occupancy,
    PropertyType,
    Purpose,
    Scenario,
)
from app.portals.base import get_adapter
from app.secrets.store import CredentialsStore


@pytest.mark.live
@pytest.mark.asyncio
async def test_ad_mortgage_live_end_to_end() -> None:
    passphrase = os.environ.get("CHECK_RATE_PASSPHRASE")
    if not passphrase:
        pytest.skip("Live test requires CHECK_RATE_PASSPHRASE env var")
    creds_path = Path("data/credentials.enc")
    if not creds_path.exists():
        pytest.skip(f"Live test requires {creds_path}")

    store = CredentialsStore(path=creds_path, passphrase=passphrase)
    creds = store.get("ad_mortgage")
    scenario = Scenario(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=Decimal("6.875"),
    )
    adapter = get_adapter("ad_mortgage")
    mfa_bridge = MfaBridge()
    session_id = uuid4().hex

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await adapter.ensure_logged_in(page, creds, mfa_bridge, session_id)
            await adapter.fill_scenario(page, scenario)
            await adapter.submit(page)
            result = await adapter.parse_result(page, scenario.target_rate)
            assert result.final_price is not None
        finally:
            await browser.close()
