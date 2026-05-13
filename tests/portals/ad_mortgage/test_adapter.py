"""Snapshot test for the AD Mortgage adapter using a synthetic DOM."""

from __future__ import annotations

from decimal import Decimal

import pytest
from playwright.async_api import async_playwright

from app.portals.ad_mortgage.adapter import AdMortgageAdapter, PortalParseError

_RESULT_HTML = """
<!doctype html>
<html><body>
  <div class="MuiDataGrid-root">
    <div role="row">
      <div role="gridcell">6.625</div>
      <div role="gridcell">$2,500.00</div>
      <div role="gridcell">$0.00</div>
      <div role="gridcell">-2.000% / -$8000</div>
    </div>
    <div role="row">
      <div role="gridcell">6.875</div>
      <div role="gridcell">$2,650.00</div>
      <div role="gridcell">$0.00</div>
      <div role="gridcell">-2.445% / -$9780</div>
    </div>
    <div role="row">
      <div role="gridcell">7.000</div>
      <div role="gridcell">$2,700.00</div>
      <div role="gridcell">$0.00</div>
      <div role="gridcell">-2.875% / -$11500</div>
    </div>
  </div>
</body></html>
"""


@pytest.mark.asyncio
async def test_parse_result_picks_target_rate() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(_RESULT_HTML)
            adapter = AdMortgageAdapter()
            result = await adapter.parse_result(page, target_rate=Decimal("6.875"))
            assert result.final_price == Decimal("-2.445")
            assert result.adjustments == []
            assert result.source == "portal"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_parse_result_missing_rate_raises() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(_RESULT_HTML)
            adapter = AdMortgageAdapter()
            with pytest.raises(PortalParseError):
                await adapter.parse_result(page, target_rate=Decimal("9.000"))
        finally:
            await browser.close()
