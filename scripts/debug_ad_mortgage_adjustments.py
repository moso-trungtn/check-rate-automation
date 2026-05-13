# pyright: basic
import asyncio, os
from decimal import Decimal
from pathlib import Path
from playwright.async_api import async_playwright
import app.portals.ad_mortgage  # noqa: F401
from app.mfa.bridge import MfaBridge
from app.models import LoanType, Occupancy, PropertyType, Purpose, Scenario
from app.portals.ad_mortgage.adapter import AdMortgageAdapter
from app.secrets.store import CredentialsStore

SCREENSHOT_DIR = Path("data/screenshots/debug-adj")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

async def main():
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
        browser = await pw.chromium.launch(headless=False, slow_mo=200)
        page = await (await browser.new_context()).new_page()
        await adapter.ensure_logged_in(page, creds, MfaBridge(), "dbg")
        await adapter.fill_scenario(page, scenario)
        await adapter.submit(page)
        # Click the rate row (this should open adjustments panel)
        rate_cell = page.get_by_role("gridcell", name="6.875", exact=True)
        await rate_cell.first.scroll_into_view_if_needed()
        await rate_cell.first.click()
        print("Clicked rate cell. Waiting 4s for adjustments to render...")
        await page.wait_for_timeout(4000)
        await page.screenshot(path=str(SCREENSHOT_DIR/"01_after_rate_click.png"), full_page=True)
        print(f"  📸 {SCREENSHOT_DIR}/01_after_rate_click.png")

        # Look for the adjustments table — try multiple strategies
        text_content = await page.evaluate("""() => {
          // Find anything mentioning 'Adjustments' header followed by a table-like structure
          const headings = Array.from(document.querySelectorAll('*'))
            .filter(el => el.children.length === 0 && /Adjustments?:?$/i.test((el.textContent||'').trim()));
          return headings.map(h => ({
            text: h.textContent.trim(),
            tag: h.tagName,
            following: h.parentElement ? h.parentElement.outerHTML.slice(0, 800) : null
          }));
        }""")
        print(f"Found {len(text_content)} 'Adjustments' headings")
        for i, t in enumerate(text_content[:3]):
            print(f"  [{i}] {t['tag']!r}: {t['text']!r}")
            print(f"      parent: {t['following'][:200]}...")

        # Dump everything that looks like a row with FICO / Purchase / Promo text
        relevant = await page.evaluate("""() => {
          const out = [];
          for (const el of document.querySelectorAll('*')) {
            if (el.children.length === 0) {
              const t = (el.textContent||'').trim();
              if (/FICO|Purchase promo|Conventional Purchase|^Total$/i.test(t) && t.length < 80) {
                let parent = el;
                for (let depth = 0; depth < 4; depth++) {
                  parent = parent.parentElement || parent;
                  if (parent.tagName === 'TR' || parent.getAttribute('role') === 'row') break;
                }
                out.push({
                  text: t,
                  selector_path: parent.outerHTML.slice(0, 300)
                });
              }
            }
          }
          return out.slice(0, 20);
        }""")
        print(f"\nFound {len(relevant)} potential adjustment cells:")
        for r in relevant:
            print(f"  {r['text']!r}")
            print(f"    container: {r['selector_path'][:120]}...")

        # Save full DOM for offline inspection
        html = await page.content()
        (SCREENSHOT_DIR/"01_page.html").write_text(html)
        print(f"\n  📄 {SCREENSHOT_DIR}/01_page.html ({len(html)} bytes)")

        await page.wait_for_timeout(15000)
        await browser.close()

asyncio.run(main())
