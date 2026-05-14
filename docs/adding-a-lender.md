# Adding a new lender

End-to-end checklist for plugging a second (third, fourth…) lender into
check-rate. Plan on **~30 min** of setup per lender once you've done one,
mostly Playwright codegen + recording the right field labels.

## Concepts in 30 seconds

A "lender" in check-rate has three pieces:

1. **MOSO side** — a numeric `lender_id` (e.g. `61` for AD Mortgage)
   and an `alias` string MOSO returns for that lender in
   `GetRatesOp._rows[].alias`.
2. **Portal side** — a `PortalAdapter` subclass that drives the
   lender's website with Playwright (login → fill scenario → parse
   result + adjustments).
3. **Wiring** — a slug (`"ad_mortgage"`) that ties (1) and (2)
   together and shows up in the UI lender dropdown.

All three live in code; credentials live encrypted in `data/credentials.enc`.

---

## Workflow

### 1. Collect lender data

Before writing code, gather:

| Item | How |
|---|---|
| Portal URL | From your lender spreadsheet |
| Login credentials | Same — email + password |
| MOSO `lender_id` | See "Find the MOSO lender ID" below |
| MOSO `alias` | The string MOSO returns in `_rows[].alias` for this lender |
| Portal program names | What labels their dropdowns use (Conventional / Standard / 30 Year Fixed etc.) |

### 2. Find the MOSO lender ID

The simplest way is to inspect a real MOSO request to `GetRatesOp` in
the DevTools Network tab for a quote that includes that lender. The
`alert_lender: <id>` and `quote_lender: <id>` fields in the response
rows tell you the numeric id.

For lenders that appear in MOSO's lender dropdown but not in the
default response, you can also grep the moso-pricing source:

```bash
grep -rE "ad.?mortgage|AD ?Mortgage" /Users/trungthach/IdeaProjects/moso-pricing/src \
  | grep -iE "(lender|alias|enum).*=.*[0-9]+"
```

### 3. Add credentials to the encrypted store

From the running app, click the **MOSO session** button → paste a
fresh cURL → save. For lender credentials use the CLI:

```bash
export CHECK_RATE_PASSPHRASE='<your-passphrase>'
uv run python -m scripts.manage_secrets \
  --path data/credentials.enc --passphrase "$CHECK_RATE_PASSPHRASE" \
  add <slug> --username '<email>' --password '<password>'
```

`<slug>` should be a stable identifier like `champion_funding`,
`pennymac`, `cardinal`. Use snake_case; you'll reuse this slug
throughout the codebase.

### 4. Record the portal flow with Playwright codegen

In a terminal:

```bash
cd /Users/trungthach/IdeaProjects/check-rate
uv run playwright codegen <portal-login-url>
```

A Chromium window opens with an Inspector pane. Walk through:
1. Log in (codegen captures username/password fills + login click).
2. Navigate to the rate-sheet / quick-pricer page.
3. Fill a canonical scenario (FICO 740, 30yr Fixed Conv, Primary,
   SFR, Purchase, ZIP 20155).
4. Click the rate row you want to inspect.

The Inspector window prints Python code as you click. **Copy it** —
that's your raw recording of what selectors work.

### 5. Create the adapter file

```bash
mkdir -p app/portals/<slug>
mkdir -p tests/portals/<slug>
mkdir -p tests/portals/<slug>/fixtures
```

Create `app/portals/<slug>/__init__.py`:

```python
"""Side-effect: importing this package registers the adapter."""
from app.portals.<slug>.adapter import <ClassName>  # noqa: F401
__all__ = ["<ClassName>"]
```

Create `app/portals/<slug>/adapter.py` modeled on
`app/portals/ad_mortgage/adapter.py`. Key shape:

```python
from app.models import Adjustment, Occupancy, PortalResult, PropertyType, Purpose, Scenario
from app.portals.base import PortalAdapter, register_adapter

@register_adapter("<slug>")
class <Name>Adapter(PortalAdapter):
    LENDER     = "<slug>"
    LOGIN_URL  = "https://..."

    async def ensure_logged_in(self, page, creds, mfa_bridge, session_id) -> None:
        # 1. page.goto(LOGIN_URL)
        # 2. If already logged in (storage_state cached), return early.
        # 3. Otherwise fill email + password, click submit.
        # 4. If portal does MFA: await mfa_bridge.request_code(session_id, "<Name>")
        ...

    async def fill_scenario(self, page, scenario: Scenario) -> None:
        # Translate scenario fields into portal clicks/fills.
        # Use mapping dicts like AD Mortgage's _OCCUPANCY_LABEL etc.
        ...

    async def submit(self, page) -> None:
        # Click whatever button computes pricing, then wait for the
        # rate table to render.
        ...

    async def parse_result(self, page, target_rate) -> PortalResult:
        # Find the row for target_rate, read final_price, optionally
        # read itemized adjustments. Return a PortalResult.
        ...
```

The AD Mortgage adapter has helpful patterns to copy:
- `_pick()` — open a MUI dropdown by container test_id, click option by text.
- `_fill_numeric()` — slider-paired text input with verify-and-retry.
- `_toggle_if_present()` — soft-failing checkbox setter.
- `_scrape_adjustments()` — header-anchored column lookup (don't use
  positional `cells[last]`).

### 6. Wire it in app/main.py

```python
import app.portals.<slug>  # register adapter

LENDER_IDS: dict[str, int] = {
    "ad_mortgage": 61,
    "<slug>": <id>,         # add here
}
LENDER_ALIASES: dict[str, str] = {
    "ad_mortgage": "AD Mortgage",
    "<slug>": "<MOSO alias>",  # add here
}
```

### 7. Add the lender to the UI dropdown

In `templates/index.html`, find:

```html
<select class="form-select form-select-sm" id="lender" name="lender">
  <option value="ad_mortgage">AD Mortgage</option>
</select>
```

…and add an option:

```html
<option value="<slug>"><Display Name></option>
```

### 8. Write a snapshot test

In `tests/portals/<slug>/test_adapter.py` write a test that loads
a synthetic DOM and asserts `parse_result()` returns the right
`final_price` and adjustments. Pattern from `ad_mortgage/test_adapter.py`:

```python
import pytest
from decimal import Decimal
from playwright.async_api import async_playwright
from app.portals.<slug>.adapter import <Name>Adapter

_HTML = """
<!doctype html>
<html><body>
  <div role="row">
    <div role="gridcell">6.875</div>
    <div role="gridcell">$2,650</div>
    <div role="gridcell">-2.445% / -$9,780</div>
  </div>
</body></html>
"""

@pytest.mark.asyncio
async def test_parse_result_extracts_price() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await (await browser.new_context()).new_page()
            await page.set_content(_HTML)
            r = await <Name>Adapter().parse_result(page, Decimal("6.875"))
            assert r.final_price == Decimal("-2.445")
        finally:
            await browser.close()
```

### 9. Live-test the adapter (REQUIRED before committing)

The unit test only proves your DOM-parsing logic works on synthetic
HTML. Always run the live test against the real portal before pushing:

```bash
CHECK_RATE_PASSPHRASE=... uv run pytest tests/portals/<slug>/test_live.py -m live -v -s
```

(Create `test_live.py` modeled on
`tests/portals/ad_mortgage/test_live.py` — same scenario, marked
`@pytest.mark.live`, runs Chromium headed so you can watch.)

The `-s` flag prints the `[<slug>] scrape: ...` breadcrumbs from the
adapter. Use them to spot field-label mismatches early.

### 10. Commit

Following the repo's commit convention (see `CLAUDE.md`):

```
[feat] add <Name> portal adapter

- Slug: <slug>
- MOSO lender_id: <id>, alias: '<alias>'
- Live test passes end-to-end (FICO 740 / Primary / SFR / Purchase /
  30yr Fixed Conv → rate 6.875 → final_price = ...)

Mappings verified live:
  Occupancy: PRIMARY → '<label>', SECOND → '<label>', INVESTMENT → '<label>'
  PropertyType: SFR → '<label>', ...
  Purpose: PURCHASE → '<label>', ...
```

---

## Common gotchas (learned from AD Mortgage)

| Gotcha | Symptom | Fix |
|---|---|---|
| Dropdown option labels differ from your guess | `PortalParseError: option 'X' not found. Visible options: [...]` | Update the mapping dict with the actual label from the error message. |
| MOSO Slider doesn't accept `.fill()` | Portal computes wrong FICO/LTV tier; downstream LLPAs are off | Use `_fill_numeric()` pattern: click → fill → Tab → verify → retry. |
| Rate-ladder column layout changes | Final Price reads as wrong value, off by some fixed amount | Use column-header indexing (find `"Final Price"` header → pluck that column index), not positional `cells[last]` or `cells[idx+3]`. |
| MUI Popover lingers and blocks next click | `subtree intercepts pointer events` error on the next dropdown | Wait for `.MuiPopover-root` to detach OR press Escape after option click. |
| MOSO returns variants (HomeReady, HomePossible) | Plain conventional row gets mixed with income-restricted ones | Filter in `MosoFacade.quote()`: `program` does not contain `"homeready"` or `"home possible"`. |
| Multiple AD Mortgage rows per rate | Same `alias`, different `program` | Same as above — discriminator is `program`, not `alias`. |
| Portal LLPAs have opposite sign vs MOSO | Identical magnitudes appear as huge "mismatch" | The compare engine already handles this (`_values_match` uses absolute value). Just make sure both sides go through the same normalized labels. |

---

## What if the portal has captcha?

Currently captcha-protected lenders are deferred. Options:

1. **Manual hand-off**: pause Playwright, let the human solve, resume.
2. **Use a captcha service**: 2Captcha / Anti-Captcha integration —
   requires money + secrets.
3. **Skip**: only include lenders without captcha in v1.

If the lender uses 2FA (TOTP / SMS), the existing `MfaBridge` already
supports it — the adapter calls `mfa_bridge.request_code()` and the UI
pops up a modal asking for the code.

---

## Quick reference: copy these files

```
app/portals/ad_mortgage/__init__.py   → app/portals/<slug>/__init__.py
app/portals/ad_mortgage/adapter.py    → app/portals/<slug>/adapter.py
tests/portals/ad_mortgage/test_adapter.py → tests/portals/<slug>/test_adapter.py
tests/portals/ad_mortgage/test_live.py    → tests/portals/<slug>/test_live.py
```

Then s/ad_mortgage/<slug>/g and s/AdMortgage/<Name>/g.
