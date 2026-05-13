from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from app.mfa.bridge import MfaBridge
from app.models import PortalResult, Scenario
from app.portals.base import (
    AdapterNotFound,
    PortalAdapter,
    get_adapter,
    register_adapter,
)
from app.secrets.store import Credentials


def test_register_and_lookup() -> None:
    @register_adapter("fake_lender")
    class FakeAdapter(PortalAdapter):
        LENDER = "fake_lender"
        LOGIN_URL = "https://example.com"

        async def ensure_logged_in(
            self,
            page: Any,
            creds: Credentials | None,
            mfa_bridge: MfaBridge,
            session_id: str,
        ) -> None:
            pass

        async def fill_scenario(self, page: Any, scenario: Scenario) -> None:
            pass

        async def submit(self, page: Any) -> None:
            pass

        async def parse_result(self, page: Any, target_rate: Decimal) -> PortalResult:
            return PortalResult(
                final_price=Decimal("100"),
                adjustments=[],
                raw_html_snapshot_path="/tmp/x.html",
                captured_at=datetime(2026, 5, 13),
            )

    adapter = get_adapter("fake_lender")
    assert isinstance(adapter, FakeAdapter)


def test_lookup_unknown_raises() -> None:
    with pytest.raises(AdapterNotFound):
        get_adapter("does_not_exist")
