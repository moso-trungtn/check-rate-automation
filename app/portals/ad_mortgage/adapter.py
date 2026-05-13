"""AD Mortgage AIM portal adapter (login + Quick Pricer Pro)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from app.mfa.bridge import MfaBridge
from app.models import Adjustment, PortalResult, Scenario
from app.portals.base import PortalAdapter, register_adapter
from app.secrets.store import Credentials

_PRICE_PATTERN = re.compile(r"([-+]?\d+\.\d+)%")


class PortalParseError(RuntimeError):
    """Raised when the adapter can't find/parse the rate row."""


@register_adapter("ad_mortgage")
class AdMortgageAdapter(PortalAdapter):
    LENDER: ClassVar[str] = "ad_mortgage"
    LOGIN_URL: ClassVar[str] = "https://aim.admortgage.com/login"

    EMAIL_INPUT_ROLE_NAME: ClassVar[str] = "Email"
    PASSWORD_INPUT_ROLE_NAME: ClassVar[str] = "Password"
    LOGIN_BUTTON_TESTID: ClassVar[str] = "login-page__login-button"

    async def ensure_logged_in(
        self,
        page: Any,
        creds: Credentials | None,
        mfa_bridge: MfaBridge,
        session_id: str,
    ) -> None:
        if creds is None:
            raise PortalParseError(
                "AD Mortgage requires credentials; populate data/credentials.enc "
                "via scripts/manage_secrets.py."
            )
        await page.goto(self.LOGIN_URL)
        # If we're already logged in via storage_state, the login form won't render.
        login_btn = page.get_by_test_id(self.LOGIN_BUTTON_TESTID)
        if await login_btn.count() == 0:
            return
        await page.get_by_role("textbox", name=self.EMAIL_INPUT_ROLE_NAME).fill(creds.username)
        await page.get_by_role("textbox", name=self.PASSWORD_INPUT_ROLE_NAME).fill(creds.password)
        await login_btn.click()
        # Wait for navigation away from login.
        await page.wait_for_url(
            lambda url: "/login" not in str(url),  # type: ignore[no-any-return]
            timeout=20_000,
        )

    async def fill_scenario(self, page: Any, scenario: Scenario) -> None:
        # Open Quick Pricer Pro from the banner menu.
        await page.get_by_role("banner").get_by_role("button").click()
        await page.get_by_text("Quick Pricer Pro").click()
        await page.get_by_role("tab", name="Conventional").click()

        # The codegen recorded position-dependent test-ids. v1 uses them verbatim;
        # if they shift in production, the live test will catch it (Task 23).
        await page.get_by_text("Primary Residence").click()
        await page.get_by_test_id("6-175").click()
        await page.get_by_text("Unit SFR").click()
        await page.get_by_test_id("8-183").click()
        await page.get_by_test_id("13").get_by_text("1 Unit").click()
        await page.get_by_test_id("13-257").click()
        await page.get_by_role("textbox", name="ZIP").fill("95132")
        await page.get_by_text("Purchase").click()
        await page.get_by_test_id("7-178").click()
        await page.get_by_test_id("19").get_by_text("Standard").click()
        await page.get_by_test_id("19-370").click()
        await page.get_by_test_id("2").get_by_text("Year Fixed").click()
        await page.get_by_test_id("2-3").click()
        await page.get_by_role("textbox", name="FICO").fill(str(scenario.credit_score))
        await page.get_by_role("textbox", name="FICO").press("Enter")
        await page.get_by_role("textbox", name="Loan Amount").fill(str(int(scenario.loan_amount)))
        await page.get_by_role("textbox", name="CLTV").fill(str(int(scenario.ltv)))

    async def submit(self, page: Any) -> None:
        # Quick Pricer Pro is reactive — no submit button.
        # Wait for the result panel to compute; show-rate-stack appears when ready.
        await page.wait_for_selector(
            '[data-testid="show-rate-stack"]', timeout=60_000,
        )
        # Expand the rate ladder so gridcells become visible.
        await page.get_by_test_id("show-rate-stack").first.click()
        await page.wait_for_selector('[role="gridcell"]', timeout=20_000)
        # Brief settle to let virtualized rows render.
        await page.wait_for_timeout(800)

    async def parse_result(self, page: Any, target_rate: Decimal) -> PortalResult:
        # Each rate row contributes 4 gridcells in order: rate, payment, credits, price.
        # We find the gridcell whose text equals the target rate, then read the
        # gridcell three slots later for the "X.XXX% / $..." price string.
        rate_text = format(target_rate.normalize(), "f")
        cells = page.locator('[role="gridcell"]')
        count = await cells.count()
        if count == 0:
            raise PortalParseError("No gridcells in AD Mortgage result panel")

        # The rate ladder uses row virtualization — only on-screen rows are in the DOM.
        # Use Playwright's role/name locator + scroll_into_view to materialize the row.
        rate_locator = page.get_by_role("gridcell", name=rate_text, exact=True)
        try:
            await rate_locator.first.scroll_into_view_if_needed(timeout=5_000)
        except Exception as e:  # noqa: BLE001
            # Re-query gridcells to give a useful diagnostic.
            sampled: list[str] = []
            current = await cells.count()
            for i in range(min(current, 30)):
                sampled.append((await cells.nth(i).text_content() or "").strip())
            raise PortalParseError(
                f"Rate {target_rate} (as text {rate_text!r}) not visible "
                f"after scrolling; saw {current} gridcells. First 30: {sampled}"
            ) from e

        # After scroll the rate cell exists; locate it + walk to its row's price cell.
        # In production each rate row contributes exactly 4 sibling gridcells:
        # [rate, payment, credits, price]. Sibling traversal is more robust than
        # global indexing because virtualization re-indexes cells as you scroll.
        price_text = await rate_locator.first.evaluate(
            """el => {
                // Find the row container, then walk 3 siblings forward to the price cell.
                let row = el.closest('[role="row"]') || el.parentElement;
                if (!row) return null;
                const rowCells = Array.from(row.querySelectorAll('[role="gridcell"]'));
                const idx = rowCells.indexOf(el);
                if (idx < 0 || idx + 3 >= rowCells.length) return null;
                return rowCells[idx + 3].textContent;
            }"""
        )
        if not price_text:
            raise PortalParseError(
                f"Could not locate price cell for rate {target_rate}"
            )
        price_text = price_text.strip()

        match = _PRICE_PATTERN.search(price_text)
        if not match:
            raise PortalParseError(
                f"Could not parse final price from {price_text!r}"
            )
        final_price = Decimal(match.group(1))

        # Click the rate cell to open the Adjustments breakdown panel, then
        # scrape the itemized LLPAs. Failure here is non-fatal: we still
        # return the final price even if the breakdown can't be parsed.
        try:
            await rate_locator.first.click()
            await page.wait_for_selector(
                'text=Adjustments:', timeout=8_000,
            )
            await page.wait_for_timeout(500)
            adjustments = await self._scrape_adjustments(page)
        except Exception:  # noqa: BLE001
            adjustments = []

        snapshot_dir = Path("data/screenshots")
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{uuid4().hex[:8]}_ad_mortgage.html"
        snapshot_path.write_text(await page.content())

        return PortalResult(
            final_price=final_price,
            adjustments=adjustments,
            raw_html_snapshot_path=str(snapshot_path),
            captured_at=datetime.now(UTC),
        )

    async def _scrape_adjustments(self, page: Any) -> list[Adjustment]:
        """Read the Adjustments DataGrid that appears below the rate ladder
        after the user (or our automation) clicks a rate row.

        The DOM is roughly:
            <Stack>
              <span>Adjustments:</span>
              <DataGrid>
                <row><cell>Description</cell><cell>Rate</cell><cell>Price</cell></row>
                ...
                <row><cell>Total</cell><cell>0</cell><cell>-0.625</cell></row>
              </DataGrid>
            </Stack>

        We walk the DataGrid that is closest to the 'Adjustments:' label,
        extract each row's first (label) and last (price) cells, and skip
        the 'Total' summary row.
        """
        rows_json = await page.evaluate(
            """() => {
                // Find the span/div whose text is exactly 'Adjustments:' (the label)
                const label = Array.from(document.querySelectorAll('span,div'))
                  .find(el => (el.textContent || '').trim() === 'Adjustments:'
                              && el.children.length === 0);
                if (!label) return null;
                // Walk up until we find an ancestor that contains a DataGrid
                let host = label.parentElement;
                let grid = null;
                while (host && !grid) {
                  grid = host.querySelector('.MuiDataGrid-root');
                  host = host.parentElement;
                }
                if (!grid) return null;
                // Each row contributes 3 gridcells: [Description, Rate, Price]
                const rows = Array.from(grid.querySelectorAll('[role="row"]'));
                const out = [];
                for (const r of rows) {
                  const cells = Array.from(r.querySelectorAll('[role="gridcell"]'));
                  if (cells.length < 3) continue;
                  const label = (cells[0].textContent || '').trim();
                  const price = (cells[cells.length - 1].textContent || '').trim();
                  if (!label || !price) continue;
                  out.push({label, price});
                }
                return out;
            }"""
        )
        if not rows_json:
            return []
        items: list[Adjustment] = []
        for r in rows_json:
            label = r.get("label", "").strip()
            price_str = r.get("price", "").strip()
            if not label or not price_str:
                continue
            if label.lower() == "total":
                continue
            try:
                amount = Decimal(price_str.replace(",", "").replace("$", ""))
            except (ArithmeticError, ValueError):
                continue
            items.append(Adjustment(label=label, amount=amount))
        return items
