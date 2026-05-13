# AD Mortgage Portal Recon (Task 14)

## URLs

- Login: `https://aim.admortgage.com/login`
- After login → click banner button → click "Quick Pricer Pro" link

## Auth

- Email + password form. No MFA, no captcha.
- Credentials live in `data/credentials.enc` (encrypted; gitignored). Populate via `scripts/manage_secrets.py add ad_mortgage --username ... --password ...`.
- Storage state is persisted to `data/sessions/ad_mortgage.json` after a successful login so subsequent runs skip re-login until cookies expire.

## Login flow

1. `page.goto("https://aim.admortgage.com/login")`
2. Fill `getByRole("textbox", {name: "Email"})` with the stored username.
3. Fill `getByRole("textbox", {name: "Password"})` with the stored password.
4. Click `getByTestId("login-page__login-button")`.
5. After login, click the banner button to open the side menu, then click text "Quick Pricer Pro" to load the pricer.

## Quote flow (Conventional, 30yr Fixed, Purchase)

Triggered by a series of dropdown-style clicks (each option has a `data-testid`). From codegen, the canonical sequence is:

| Field | Trigger | Option click |
|---|---|---|
| Loan type tab | `getByRole("tab", {name: "Conventional"})` | — |
| Occupancy | text "Primary Residence" → opens menu | `getByTestId("6-175")` |
| Property type | text "Unit SFR" → menu | `getByTestId("8-183")` |
| Units | inside `getByTestId("13")` text "1 Unit" | `getByTestId("13-257")` |
| ZIP | textbox "ZIP" | fill `"95132"` |
| Purpose | text "Purchase" → menu | `getByTestId("7-178")` |
| Doc type | inside `getByTestId("19")` text "Standard" | `getByTestId("19-370")` |
| Program | inside `getByTestId("2")` text "Year Fixed" | `getByTestId("2-3")` |
| FICO | textbox "FICO" | fill `"740"` then Enter |
| Loan Amount | textbox "Loan Amount" | fill `"400000"` |
| CLTV | textbox "CLTV" | fill `"80"` |

There is no explicit "Submit" — the result grid populates as fields are filled. After filling all fields, the adapter waits for the rate grid to populate.

**Important — the dropdown option test-ids look position-dependent.** Values like `6-175`, `8-183` look like `<group>-<option>` ordinals: `6` is the field group, `175` is the specific option. These may shift if AD Mortgage reorders dropdown items. The adapter will need to be re-recorded if it breaks.

## Result page structure

- The rate ladder is a Material-UI DataGrid.
- Each rate is selectable by `getByRole("gridcell", {name: "<rate>"})` — e.g., `"6.875"`.
- Clicking a gridcell selects the whole row (`.MuiDataGrid-row.Mui-selected`).
- The selected row's price is shown in the 4th column (`.MuiDataGrid-row.Mui-selected > div:nth-child(4)`) and matches text pattern like `-2.445% / -$<amount>`.
- A `getByTestId("show-rate-stack")` button toggles an expanded LLPA breakdown view per row.

### v1 parsing strategy

For v1 we extract **final_price only** (percent value from the `-X.XXX%` prefix). LLPA itemized comparison is deferred to v1.5.

### v1.5 LLPA itemization path (verified live)

To expose itemized LLPAs:

1. After form fill + show-rate-stack click, the rate ladder is visible but no LLPA panel yet.
2. **Click the rate gridcell** (e.g. `getByRole('gridcell', {name: '6.875', exact: true})`).
3. An LLPA dropdown opens beneath/beside the row. Cells appear as triples in gridcell document order: `[label, ?, amount]`. Observed examples:
   - `FICO 740 - 759 and Purchase`, ``, `-0.125`
   - `Conventional Purchase promo`, ``, `0.250`
4. Walk the gridcells after the rate row (or use a more specific container selector) and pair label+amount.

Note: MOSO's `commission_detail` for AD Mortgage only contains rollup rows (Base Price, Total Adj, Adjusted Price, etc.) — no itemized LLPAs. So even with portal-side itemization, MOSO-side comparison only has the aggregate `Total Adj`. v1.5 should compare total adj on MOSO vs the SUM of itemized portal LLPAs.

Regex to extract: `^\s*([-+]?\d+\.\d+)%\s*/\s*[-+]?\$.*$`

The `MosoResult` LLPA list will still be populated (from `GetRatesOp.commission_detail._rows`) but the `PortalResult.adjustments` list will be **empty** in v1. The compare engine treats label-only-on-MOSO as a mismatch with `portal_value=None` — that's exactly what we want until the portal-side LLPAs are wired.

## Snapshot test approach

The saved page-source HTML (`tests/portals/ad_mortgage/fixtures/result_30yr_fixed.html`) is the un-hydrated SPA shell — not the rendered DataGrid. For unit tests we use a **synthetic DOM** mimicking the production structure (rows with `role="gridcell"` containing the rate text, sibling cell containing the `-X.XXX%` price). The live smoke test (Task 23) validates against the real portal.

## Captcha / MFA

None on this portal. If that changes, the adapter falls back to `mfa_bridge.request_code()` which is already wired in the base class.

## Recorded codegen (raw)

```python
import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://aim.admortgage.com/login")
    page.get_by_role("textbox", name="Email").fill("giau.nguyen@loanfactory.com")
    page.get_by_role("textbox", name="Password").fill("Welcome1@")
    page.get_by_test_id("login-page__login-button").click()
    page.get_by_role("banner").get_by_role("button").click()
    page.get_by_text("Quick Pricer Pro").click()
    page.get_by_role("tab", name="Conventional").click()
    page.get_by_text("Primary Residence").click()
    page.get_by_test_id("6-175").click()
    page.get_by_text("Unit SFR").click()
    page.get_by_test_id("8-183").click()
    page.get_by_test_id("13").get_by_text("1 Unit").click()
    page.get_by_test_id("13-257").click()
    page.get_by_role("textbox", name="ZIP").fill("95132")
    page.get_by_text("Purchase").click()
    page.get_by_test_id("7-178").click()
    page.get_by_test_id("19").get_by_text("Standard").click()
    page.get_by_test_id("19-370").click()
    page.get_by_test_id("2").get_by_text("Year Fixed").click()
    page.get_by_test_id("2-3").click()
    page.get_by_role("textbox", name="FICO").fill("740")
    page.get_by_role("textbox", name="FICO").press("Enter")
    page.get_by_role("textbox", name="Loan Amount").fill("400000")
    page.get_by_role("textbox", name="CLTV").fill("80")
    page.get_by_role("gridcell", name="6.875").click()
    # 4th div of selected row shows price as "-X.XXX% / -$amt"
    context.close()
    browser.close()
```

## Open questions deferred to live test (Task 23)

- Are the dropdown option test-ids (`6-175`, `8-183` etc.) deterministic across users + sessions, or session-specific? If session-specific, we'll switch to text-based selectors.
- Does the rate grid include both `gridcell` for rate AND a separate gridcell for price, or only one composite cell? Codegen suggests separate columns.
- After Enter on FICO, does the grid auto-refresh, or do we need a `wait_for_selector` on the new grid?
