"""AD Mortgage AIM portal adapter (login + Quick Pricer Pro)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from app.mfa.bridge import MfaBridge
from app.models import (
    Adjustment,
    Occupancy,
    PortalResult,
    PropertyType,
    Purpose,
    Scenario,
)
from app.portals.base import PortalAdapter, register_adapter
from app.secrets.store import Credentials

# Stable container test_ids for each dropdown FIELD (verified via codegen).
# Option ids inside each dropdown ("6-175" etc.) are NOT stable, so we open
# the field by container then click the option by visible text.
_FIELD_TESTID_OCCUPANCY = "6"
_FIELD_TESTID_PURPOSE = "7"
_FIELD_TESTID_PROPERTY_TYPE = "8"
_FIELD_TESTID_UNITS = "13"
_FIELD_TESTID_PROGRAM_TYPE = "19"  # Standard / Hi-Bal / etc.
_FIELD_TESTID_LOAN_TERM = "2"      # Year Fixed / ARM


# Scenario enum → visible option text inside each portal dropdown.
# "Verified" entries were captured by codegen; "guess" entries need a
# live trial run to confirm the exact label text.
_OCCUPANCY_LABEL: dict[Occupancy, str] = {
    Occupancy.PRIMARY:    "Primary Residence",   # verified
    Occupancy.SECOND:     "Second Home",         # guess
    Occupancy.INVESTMENT: "Investment",          # guess
}

_PURPOSE_LABEL: dict[Purpose, str] = {
    Purpose.PURCHASE: "Purchase",                # verified
    Purpose.REFI:     "Refinance",               # guess
    Purpose.CASHOUT:  "Cash Out",                # guess
}

_PROPERTY_TYPE_LABEL: dict[PropertyType, str] = {
    PropertyType.SFR:         "1 Unit SFR",       # verified live
    PropertyType.CONDO:       "Condo",            # verified live
    PropertyType.PUD:         "PUD",              # verified live
    PropertyType.TWO_TO_FOUR: "2-4 Units",        # verified live
}

_UNITS_LABEL: dict[int, str] = {
    1: "1 Unit",   # verified
    2: "2 Units",  # guess
    3: "3 Units",  # guess
    4: "4 Units",  # guess
}

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
        """Drive the AIM Quick Pricer Pro form using values from `scenario`.

        Each dropdown is filled by opening its container (stable test_id)
        and clicking the option by visible text from the corresponding
        mapping table. This is robust against MUI's session-varying option
        ids while still scenario-driven.
        """
        # Open Quick Pricer Pro from the banner menu.
        await page.get_by_role("banner").get_by_role("button").click()
        await page.get_by_text("Quick Pricer Pro").click()
        await page.get_by_role("tab", name="Conventional").click()

        # ----- Dropdowns from scenario -----
        await self._pick(
            page, _FIELD_TESTID_OCCUPANCY,
            _OCCUPANCY_LABEL[scenario.occupancy],
        )
        await self._pick(
            page, _FIELD_TESTID_PROPERTY_TYPE,
            _PROPERTY_TYPE_LABEL[scenario.property_type],
        )
        await self._pick(
            page, _FIELD_TESTID_UNITS,
            _UNITS_LABEL[scenario.actual_number_of_units],
        )
        # ----- ZIP from scenario -----
        await page.get_by_role("textbox", name="ZIP").fill(scenario.zip)
        # ----- More dropdowns -----
        await self._pick(
            page, _FIELD_TESTID_PURPOSE,
            _PURPOSE_LABEL[scenario.purpose],
        )
        # Program / term are fixed for v1 (Standard 30-yr Fixed Conv).
        await self._pick(page, _FIELD_TESTID_PROGRAM_TYPE, "Standard")
        await self._pick(page, _FIELD_TESTID_LOAN_TERM, "30 Year Fixed")

        # DTI is a separate slider-paired input.
        await self._fill_numeric(page, "DTI", str(scenario.debt_to_income))

        # ----- Checkboxes from scenario (BEFORE numeric inputs so the
        #       final FICO/Loan/CLTV fill triggers exactly one recalc) -----
        # Portal label    | Scenario field          | Direction
        # ----------------|-------------------------|-----------------
        # Escrow Waiver   | not scenario.impounds   | inverted
        # FTHB            | first_time_home_buyer   | direct
        # Sub Financing   | has_equity_loan         | direct
        # Admin Fee Buyout| waive_lender_fee        | direct
        await self._toggle_if_present(page, "Escrow Waiver", not scenario.impounds)
        await self._toggle_if_present(page, "FTHB", scenario.first_time_home_buyer)
        await self._toggle_if_present(page, "Sub Financing", scenario.has_equity_loan)
        await self._toggle_if_present(page, "Admin Fee Buyout", scenario.waive_lender_fee)
        # self_employed has no portal equivalent on the Conventional QPP form.

        # ----- Numeric inputs LAST so the final recalc is the only one
        #       that has to settle before submit() waits for the rate panel.
        # Each field is paired with a slider; the displayed text input
        # only commits its value to the slider on blur. Sequence: click
        # the box, fill, Tab to blur, then verify the input actually
        # holds the value we wanted. If it reverts (slider step rounded
        # us), re-fill and blur once more before giving up — this is
        # what was causing FICO 740 to read back as the 720-739 LLPA
        # tier in earlier runs.
        await self._fill_numeric(page, "FICO", str(scenario.credit_score))
        await self._fill_numeric(page, "Loan Amount", str(int(scenario.loan_amount)))
        await self._fill_numeric(page, "CLTV", str(int(scenario.ltv)))

    async def _fill_if_present(self, page: Any, label: str, value: str) -> None:
        """Fill a textbox by accessible name, no-op if not on the page."""
        box = page.get_by_role("textbox", name=label)
        if await box.count() > 0:
            try:
                await box.first.fill(value)
            except Exception:  # noqa: BLE001
                pass  # field exists but is disabled / read-only

    async def _fill_numeric(self, page: Any, label: str, value: str) -> None:
        """Fill a slider-paired numeric input and verify the value sticks.

        The Quick Pricer Pro pairs each numeric field (FICO, Loan Amount,
        CLTV, DTI) with a MUI Slider. Typing into the text box doesn't
        always commit the value to the slider on the first try; pressing
        Tab forces blur which fires MUI's onChange. We then read back
        the input.value and retry once if it didn't take.
        """
        box = page.get_by_role("textbox", name=label).first
        for attempt in range(2):
            await box.click()
            await box.fill(value)
            await box.press("Tab")
            # Brief settle so the slider's onChange has time to fire.
            await page.wait_for_timeout(150)
            try:
                current = await box.input_value()
            except Exception:  # noqa: BLE001
                current = ""
            if current == value:
                return
            if attempt == 0:
                print(
                    f"[ad_mortgage] {label} fill read back {current!r} "
                    f"(expected {value!r}) — retrying"
                )
        # Last resort: dispatch a synthetic input + change event so React
        # treats the value as user-entered even if .fill didn't trigger it.
        await box.evaluate(
            """(el, v) => {
                const native = Object.getOwnPropertyDescriptor(
                  window.HTMLInputElement.prototype, 'value'
                ).set;
                native.call(el, v);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""",
            value,
        )
        await box.press("Tab")
        await page.wait_for_timeout(200)

    async def _toggle_if_present(
        self, page: Any, label: str, desired_checked: bool,
    ) -> None:
        """Set a checkbox to the desired state by its accessible label.

        Soft-fail: if the label can't be found, we just skip — different
        loan-type tabs surface different checkboxes, so it's normal for
        some toggles to be absent. The compare flow will still produce
        a usable delta.
        """
        box = page.get_by_role("checkbox", name=label)
        if await box.count() == 0:
            return
        try:
            await box.first.set_checked(desired_checked)
        except Exception:  # noqa: BLE001
            # Fallback: read state and toggle by click if it differs.
            try:
                current = await box.first.is_checked()
                if current != desired_checked:
                    await box.first.click()
            except Exception:  # noqa: BLE001
                pass

    async def _pick(self, page: Any, field_testid: str, option_text: str) -> None:
        """Open a Quick Pricer Pro dropdown and click an option by text.

        MUI Select needs the inner element with `role="combobox"` clicked
        (the displayed-value div), not the outer testid wrapper. After
        opening, the option list lives inside the popover modal — MUI
        may use role=listbox+option or role=menu+menuitem depending on
        the control variant, so we try both plus a plain-text fallback.
        """
        # Open the menu. Prefer the inner combobox if MUI wraps one;
        # fall back to clicking the outer testid container.
        field = page.get_by_test_id(field_testid)
        combobox = field.locator('[role="combobox"]')
        if await combobox.count() > 0:
            await combobox.first.click()
        else:
            await field.click()

        # Wait for the option to appear anywhere on the page — works
        # regardless of which MUI variant rendered the menu.
        option = page.get_by_role("option", name=option_text, exact=True)
        try:
            await option.first.wait_for(state="visible", timeout=5_000)
        except Exception:  # noqa: BLE001
            # Try the Menu variant (role=menuitem) or any text in popper.
            option = page.get_by_role("menuitem", name=option_text, exact=True)
            try:
                await option.first.wait_for(state="visible", timeout=2_000)
            except Exception:  # noqa: BLE001
                option = page.locator(
                    ".MuiPopover-root, .MuiPopper-root"
                ).locator(f'text="{option_text}"').first
                try:
                    await option.wait_for(state="visible", timeout=2_000)
                except Exception as e:  # noqa: BLE001
                    # Dump what IS in the open popover so we know the
                    # actual label text and can tune the mapping table.
                    visible = await page.locator(
                        '.MuiPopover-root, .MuiPopper-root'
                    ).locator(
                        'li, [role="option"], [role="menuitem"]'
                    ).all_text_contents()
                    visible = [v.strip() for v in visible if v.strip()]
                    await page.keyboard.press("Escape")  # cleanup
                    raise PortalParseError(
                        f"AD Mortgage dropdown (test_id={field_testid!r}) "
                        f"has no option {option_text!r}. "
                        f"Visible options: {visible}"
                    ) from e

        await option.first.click()

        # Wait for the modal backdrop to fully detach so the next _pick()
        # click isn't intercepted by a stale popover.
        try:
            await page.locator(
                ".MuiBackdrop-root.MuiModal-backdrop"
            ).first.wait_for(state="detached", timeout=3_000)
        except Exception:  # noqa: BLE001
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)

    async def submit(self, page: Any) -> None:
        # Quick Pricer Pro is reactive — no submit button.
        # Wait for the result panel to compute; show-rate-stack appears when ready.
        await page.wait_for_selector(
            '[data-testid="show-rate-stack"]', timeout=60_000,
        )
        # Expand the rate ladder so gridcells become visible. Retry the
        # click + wait once because checkbox-driven recalcs can collapse
        # the stack mid-flight.
        for attempt in range(2):
            await page.get_by_test_id("show-rate-stack").first.click()
            try:
                await page.wait_for_selector(
                    '[role="gridcell"]', timeout=30_000,
                )
                break
            except Exception:  # noqa: BLE001
                if attempt == 1:
                    raise
                await page.wait_for_timeout(1500)
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

        # Locate the price cell by COLUMN HEADER ("Final Price"), not by
        # positional sibling offset. The rate ladder DataGrid sometimes
        # carries an extra "Compare" checkbox column on the left; when it
        # does, idx+3 from the rate cell lands one column shy of Price
        # (the original cells[idx+3] approach produced values off by ~0.75
        # because we picked the MI / credits column instead). Header
        # indexing handles any number of layout variants.
        price_scrape: dict[str, Any] = await rate_locator.first.evaluate(  # pyright: ignore[reportAny]
            """el => {
                const grid = el.closest('.MuiDataGrid-root');
                if (!grid) return {error: 'rate cell not inside a DataGrid'};
                // Find the column index for 'Final Price' via column header.
                const headers = Array.from(grid.querySelectorAll('[role="columnheader"]'));
                let priceIdx = headers
                    .map(h => (h.textContent || '').trim())
                    .findIndex(t => /final\\s*price/i.test(t));
                // Fallback: first row may carry header role 'columnheader'
                // on its cells or use the same role as data cells.
                if (priceIdx < 0) {
                  const firstRow = grid.querySelector('[role="row"]');
                  if (firstRow) {
                    const htexts = Array.from(firstRow.children)
                      .map(c => (c.textContent || '').trim());
                    priceIdx = htexts.findIndex(t => /final\\s*price/i.test(t));
                  }
                }
                const row = el.closest('[role="row"]') || el.parentElement;
                if (!row) return {error: 'rate cell has no row parent'};
                const cells = Array.from(row.querySelectorAll('[role="gridcell"]'));
                const cellTexts = cells.map(c => (c.textContent || '').trim());
                if (priceIdx >= 0 && priceIdx < cells.length) {
                  return {
                    text: cellTexts[priceIdx],
                    priceIdx,
                    headers: headers.map(h => (h.textContent || '').trim()),
                    cells: cellTexts,
                  };
                }
                // Last-resort positional fallback (4-col layout).
                const rateIdx = cells.indexOf(el);
                if (rateIdx >= 0 && rateIdx + 3 < cells.length) {
                  return {text: cellTexts[rateIdx + 3], fallback: 'positional', cells: cellTexts};
                }
                return {error: 'no Final Price column found', cells: cellTexts};
            }"""
        )
        price_text: str = str(price_scrape.get("text") or "")
        # Breadcrumb so future column shifts surface immediately.
        print(
            f"[ad_mortgage] rate-ladder scrape: rate={rate_text!r} "
            f"price_idx={price_scrape.get('priceIdx')} "
            f"headers={price_scrape.get('headers')} "
            f"row_cells={price_scrape.get('cells')}"
        )
        if not price_text:
            err = price_scrape.get("error") or "unknown"
            raise PortalParseError(
                f"Could not locate price cell for rate {target_rate}: {err}"
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
        """Read the Adjustments DataGrid that appears below the rate ladder.

        We must index by COLUMN HEADER ("Description" / "Price"), not by
        cell position, because the DataGrid may carry extra slots
        (selection checkbox, expand toggle, action button) on either end
        of the visible row. cells[last] used to be the price column when
        the grid had 3 visible columns; once a 4th slot appeared the
        scrape silently picked up the wrong value (e.g., -0.125 instead
        of -0.875, a 0.750 mismatch the user spotted).

        Returns a structured list with full debug context so callers can
        log what the DOM actually looked like if a future schema change
        breaks indexing.
        """
        scrape: dict[str, Any] = await page.evaluate(  # pyright: ignore[reportAny]
            """() => {
                // Locate the 'Adjustments:' label cell.
                const label = Array.from(document.querySelectorAll('span,div'))
                  .find(el => (el.textContent || '').trim() === 'Adjustments:'
                              && el.children.length === 0);
                if (!label) return {error: "no Adjustments: label found"};

                // Walk up until we find the nearest MUI DataGrid descendant.
                let host = label.parentElement;
                let grid = null;
                while (host && !grid) {
                  grid = host.querySelector('.MuiDataGrid-root');
                  host = host.parentElement;
                }
                if (!grid) return {error: "no MuiDataGrid-root near Adjustments:"};

                // Find the column index for 'Description' and 'Price' by
                // reading the column headers (role=columnheader).
                const headers = Array.from(grid.querySelectorAll('[role="columnheader"]'));
                const headerTexts = headers.map(h => (h.textContent || '').trim());
                let descIdx = headerTexts.findIndex(t => /^description$/i.test(t));
                let priceIdx = headerTexts.findIndex(t => /^price$/i.test(t));
                // Fallback: if columnheader role isn't used, look for
                // a header row inside row[aria-rowindex=1].
                if (descIdx < 0 || priceIdx < 0) {
                  const headerRow = grid.querySelector('[role="row"][aria-rowindex="1"]')
                    || grid.querySelector('[role="row"]');
                  if (headerRow) {
                    const hcells = Array.from(
                      headerRow.querySelectorAll('[role="columnheader"], [role="gridcell"]')
                    );
                    const htexts = hcells.map(h => (h.textContent || '').trim());
                    if (descIdx < 0)  descIdx = htexts.findIndex(t => /^description$/i.test(t));
                    if (priceIdx < 0) priceIdx = htexts.findIndex(t => /^price$/i.test(t));
                  }
                }

                // Collect every data row (skipping the header row).
                const rows = Array.from(grid.querySelectorAll('[role="row"]'))
                  .filter(r => r.getAttribute('aria-rowindex') !== '1');
                const out = [];
                const dumps = [];
                for (const r of rows) {
                  const cells = Array.from(r.querySelectorAll('[role="gridcell"]'));
                  const texts = cells.map(c => (c.textContent || '').trim());
                  dumps.push(texts);
                  if (cells.length === 0) continue;
                  let labelText, priceText;
                  if (descIdx >= 0 && priceIdx >= 0
                      && descIdx < cells.length && priceIdx < cells.length) {
                    labelText = texts[descIdx];
                    priceText = texts[priceIdx];
                  } else {
                    // Last-resort positional fallback: assume 3-col layout
                    // (Description, Rate, Price). Better than nothing.
                    labelText = texts[0] || '';
                    priceText = texts[texts.length - 1] || '';
                  }
                  if (!labelText || !priceText) continue;
                  out.push({label: labelText, price: priceText});
                }
                return {rows: out, headerTexts, descIdx, priceIdx, rowDumps: dumps};
            }"""
        )
        if not scrape or scrape.get("error"):
            return []
        # One-line breadcrumb for live debugging.
        print(
            f"[ad_mortgage] adjustments scrape: headers={scrape.get('headerTexts')} "
            f"desc_idx={scrape.get('descIdx')} price_idx={scrape.get('priceIdx')} "
            f"rows={scrape.get('rowDumps')}"
        )
        rows_json: list[dict[str, str]] = scrape.get("rows") or []
        if not rows_json:
            return []
        items: list[Adjustment] = []
        for r in rows_json:
            label = str(r.get("label") or "").strip()
            price_str = str(r.get("price") or "").strip()
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
