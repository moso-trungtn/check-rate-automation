"""AD Mortgage AIM portal adapter (login + Quick Pricer Pro)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from app.mfa.bridge import MfaBridge
from app.models import PortalResult, Scenario
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
        # AD Mortgage's Quick Pricer Pro is reactive — no submit button.
        # Wait for the rate grid to render.
        await page.wait_for_selector(".MuiDataGrid-row", timeout=20_000)

    async def parse_result(self, page: Any, target_rate: Decimal) -> PortalResult:
        rate_text = format(target_rate.normalize(), "f")  # "6.875"
        cell = page.get_by_role("gridcell", name=rate_text)
        if await cell.count() == 0:
            raise PortalParseError(f"Rate {target_rate} not in AD Mortgage result grid")
        await cell.first.click()

        # The 4th div of the now-selected row contains the price text.
        price_locator = page.locator(".MuiDataGrid-row.Mui-selected > div:nth-child(4)")
        if await price_locator.count() == 0:
            raise PortalParseError("Selected row has no 4th column")
        price_text = (await price_locator.first.text_content()) or ""

        match = _PRICE_PATTERN.search(price_text)
        if not match:
            raise PortalParseError(f"Could not parse final price from {price_text!r}")
        final_price = Decimal(match.group(1))

        # v1: skip LLPA scraping. To enable in v1.5, click `getByTestId("show-rate-stack")`
        # and read the expanded rows here.

        snapshot_dir = Path("data/screenshots")
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{uuid4().hex[:8]}_ad_mortgage.html"
        snapshot_path.write_text(await page.content())

        return PortalResult(
            final_price=final_price,
            adjustments=[],  # not scraped in v1; see recon doc
            raw_html_snapshot_path=str(snapshot_path),
            captured_at=datetime.now(UTC),
        )
