"""Debug helper: walk the AD Mortgage adapter step by step with screenshots."""
# pyright: basic
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from pathlib import Path

from playwright.async_api import async_playwright

import app.portals.ad_mortgage  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.mfa.bridge import MfaBridge
from app.models import LoanType, Occupancy, PropertyType, Purpose, Scenario
from app.portals.ad_mortgage.adapter import AdMortgageAdapter
from app.secrets.store import CredentialsStore


SCREENSHOT_DIR = Path("data/screenshots/debug")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


async def screenshot(page, step: str) -> None:  # type: ignore[no-untyped-def]
    path = SCREENSHOT_DIR / f"{step}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"  📸 {path}")


async def main() -> None:
    passphrase = os.environ["CHECK_RATE_PASSPHRASE"]
    store = CredentialsStore(path=Path("data/credentials.enc"), passphrase=passphrase)
    creds = store.get("ad_mortgage")
    scenario = Scenario(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=Decimal("6.875"),
    )
    adapter = AdMortgageAdapter()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=300)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        try:
            print("Step 1: ensure_logged_in")
            await adapter.ensure_logged_in(page, creds, MfaBridge(), "debug")
            await screenshot(page, "01_after_login")

            print("Step 2: open Quick Pricer Pro")
            await page.get_by_role("banner").get_by_role("button").click()
            await page.wait_for_timeout(500)
            await screenshot(page, "02_banner_clicked")

            await page.get_by_text("Quick Pricer Pro").click()
            await page.wait_for_timeout(2000)
            await screenshot(page, "03_quick_pricer")

            print("Step 3: Conventional tab")
            await page.get_by_role("tab", name="Conventional").click()
            await page.wait_for_timeout(500)
            await screenshot(page, "04_conventional")

            print("Step 4: form fields (with logging per step)")
            steps = [
                ("primary_residence", lambda: page.get_by_text("Primary Residence").click()),
                ("primary_option",    lambda: page.get_by_test_id("6-175").click()),
                ("unit_sfr",          lambda: page.get_by_text("Unit SFR").click()),
                ("unit_sfr_option",   lambda: page.get_by_test_id("8-183").click()),
                ("1_unit",            lambda: page.get_by_test_id("13").get_by_text("1 Unit").click()),
                ("1_unit_option",     lambda: page.get_by_test_id("13-257").click()),
                ("zip",               lambda: page.get_by_role("textbox", name="ZIP").fill("95132")),
                ("purchase",          lambda: page.get_by_text("Purchase").click()),
                ("purchase_option",   lambda: page.get_by_test_id("7-178").click()),
                ("standard",          lambda: page.get_by_test_id("19").get_by_text("Standard").click()),
                ("standard_option",   lambda: page.get_by_test_id("19-370").click()),
                ("year_fixed",        lambda: page.get_by_test_id("2").get_by_text("Year Fixed").click()),
                ("year_fixed_option", lambda: page.get_by_test_id("2-3").click()),
                ("fico",              lambda: page.get_by_role("textbox", name="FICO").fill("740")),
                ("fico_enter",        lambda: page.get_by_role("textbox", name="FICO").press("Enter")),
                ("loan_amount",       lambda: page.get_by_role("textbox", name="Loan Amount").fill("400000")),
                ("cltv",              lambda: page.get_by_role("textbox", name="CLTV").fill("80")),
            ]
            for name, fn in steps:
                print(f"  -> {name}")
                try:
                    await fn()
                    await page.wait_for_timeout(400)
                except Exception as e:
                    print(f"     ❌ FAILED: {type(e).__name__}: {e}")
                    await screenshot(page, f"FAIL_{name}")
                    raise

            await screenshot(page, "05_form_filled")

            print("Step 5: poll for rate results — every 3s for 60s")
            found = False
            for attempt in range(20):
                counts = {}
                for selector in [
                    ".MuiDataGrid-row", '[role="row"]', '[role="gridcell"]',
                    '[data-testid="show-rate-stack"]', ".MuiDataGrid-root",
                    "table", "tbody tr", ".rate-row",
                ]:
                    counts[selector] = await page.locator(selector).count()
                non_zero = {k: v for k, v in counts.items() if v}
                print(f"  attempt {attempt + 1}: {non_zero or 'still nothing'}")
                if counts['[role="gridcell"]'] > 0 or counts['[data-testid="show-rate-stack"]'] > 0:
                    found = True
                    break
                await page.wait_for_timeout(3000)

            if found:
                print("  ✓ rate panel loaded")
                await screenshot(page, "06_panel_loaded")
                # Try clicking show-rate-stack to expand
                stack = page.get_by_test_id("show-rate-stack")
                stack_count = await stack.count()
                print(f"  show-rate-stack count: {stack_count}")
                if stack_count > 0:
                    await stack.first.click()
                    await page.wait_for_timeout(1500)
                    await screenshot(page, "07_stack_expanded")
                    gridcells = await page.locator('[role="gridcell"]').count()
                    print(f"  gridcells after stack click: {gridcells}")
                    if gridcells > 0:
                        # Sample first 5 gridcell texts
                        for i in range(min(gridcells, 10)):
                            text = await page.locator('[role="gridcell"]').nth(i).text_content()
                            print(f"    gridcell[{i}]: {text!r}")
            else:
                print("  ❌ rate panel never loaded after 60s")

            await screenshot(page, "08_final")
            html = await page.content()
            (SCREENSHOT_DIR / "08_page.html").write_text(html)
            print(f"  📄 saved page html ({len(html)} bytes)")

        finally:
            print("Browser will stay open for 30s — inspect manually.")
            await page.wait_for_timeout(30_000)
            await browser.close()


asyncio.run(main())
