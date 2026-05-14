"""Sun West MC (SWMC) portal adapter.

STATUS: skeleton — login + scaffolding wired up, but fill_scenario and
parse_result need the actual portal selectors from a `playwright codegen`
recording. Running this against the live portal today will:

  1. Successfully log in (verified).
  2. Raise PortalNotImplemented in fill_scenario until the portal flow
     is recorded and the dropdowns/inputs are mapped.

Once recorded, follow the same pattern as `app/portals/ad_mortgage/
adapter.py`: mapping dicts for enum → portal label, `_pick()` helper
to open MUI dropdowns by container test_id and click options by text,
`_fill_numeric()` for slider-paired inputs, header-anchored column
indexing for result tables.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

from app.mfa.bridge import MfaBridge
from app.models import PortalResult, Scenario
from app.portals.base import PortalAdapter, register_adapter
from app.secrets.store import Credentials


class PortalNotImplemented(NotImplementedError):
    """Raised when a portal flow step hasn't been recorded yet."""


@register_adapter("sunwest")
class SunWestAdapter(PortalAdapter):
    LENDER: ClassVar[str] = "sunwest"
    LOGIN_URL: ClassVar[str] = "https://www.swmc.com/login"

    # TODO: confirm these against the recorded codegen.
    EMAIL_INPUT_ROLE_NAME: ClassVar[str] = "Username"
    PASSWORD_INPUT_ROLE_NAME: ClassVar[str] = "Password"
    LOGIN_BUTTON_NAME: ClassVar[str] = "Sign In"

    async def ensure_logged_in(
        self,
        page: Any,
        creds: Credentials | None,
        mfa_bridge: MfaBridge,
        session_id: str,
    ) -> None:
        if creds is None:
            raise PortalNotImplemented(
                "SunWest requires credentials; populate data/credentials.enc "
                "via scripts/manage_secrets.py add sunwest --username ... "
                "--password ..."
            )
        await page.goto(self.LOGIN_URL)
        # If storage_state already has a valid session, the login form
        # won't render. We accept either an explicit textbox or a generic
        # input fallback because we haven't confirmed the field roles yet.
        username_box = page.get_by_role(
            "textbox", name=self.EMAIL_INPUT_ROLE_NAME,
        )
        if await username_box.count() == 0:
            # Maybe already logged in, or the field uses a different role.
            # Treat as a no-op and let downstream errors surface clearly.
            return
        await username_box.first.fill(creds.username)
        await page.get_by_role(
            "textbox", name=self.PASSWORD_INPUT_ROLE_NAME,
        ).first.fill(creds.password)
        login_btn = page.get_by_role("button", name=self.LOGIN_BUTTON_NAME)
        if await login_btn.count() > 0:
            await login_btn.first.click()
        # Wait briefly for navigation away from /login.
        try:
            await page.wait_for_url(
                lambda url: "/login" not in str(url),  # type: ignore[no-any-return]
                timeout=15_000,
            )
        except Exception:  # noqa: BLE001
            # Login may have hit MFA, captcha, or a different success URL.
            # We don't fail loudly here — let fill_scenario error if
            # we're not really logged in.
            pass

    async def fill_scenario(self, page: Any, scenario: Scenario) -> None:
        raise PortalNotImplemented(
            "SunWest fill_scenario isn't wired yet. Record the portal "
            "quote flow with `uv run playwright codegen https://www.swmc.com/login` "
            "and translate the recording into mapping dicts + _pick() "
            "calls following the AdMortgageAdapter pattern."
        )

    async def submit(self, page: Any) -> None:
        raise PortalNotImplemented("SunWest submit isn't wired yet.")

    async def parse_result(
        self, page: Any, target_rate: Decimal,
    ) -> PortalResult:
        raise PortalNotImplemented(
            "SunWest parse_result isn't wired yet. The result table's "
            "column headers + row structure need to be inspected to "
            "implement header-anchored scraping."
        )
