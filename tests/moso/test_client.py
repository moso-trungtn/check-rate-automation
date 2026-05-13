import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.models import (
    LoanType,
    Occupancy,
    PropertyType,
    Purpose,
    Scenario,
)
from app.moso.client import MosoApiError, MosoAuthError, MosoClient

FIX = Path(__file__).parent / "fixtures"


def _scenario() -> Scenario:
    return Scenario(
        loan_amount=Decimal("400000"),
        credit_score=740,
        property_value=Decimal("500000"),
        ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY,
        property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE,
        loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL,
        target_rate=Decimal("6.875"),
    )


@pytest.mark.asyncio
async def test_get_rates_success() -> None:
    sample = json.loads((FIX / "getratesop_sample.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/exec/GetRatesOp"
        assert request.headers.get("XSRF") == "abc"
        return httpx.Response(200, json=sample)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = MosoClient(
            base_url="http://x",
            http=http,
            headers={"XSRF": "abc", "user": "u"},
        )
        rows = await client.get_rates(_scenario(), lender_id=61)
        assert len(rows) > 0


@pytest.mark.asyncio
async def test_get_rates_401_raises_auth_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(401))
    async with httpx.AsyncClient(transport=transport) as http:
        client = MosoClient(base_url="http://x", http=http, headers={})
        with pytest.raises(MosoAuthError):
            await client.get_rates(_scenario(), lender_id=61)


@pytest.mark.asyncio
async def test_get_rates_500_raises_api_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        client = MosoClient(base_url="http://x", http=http, headers={})
        with pytest.raises(MosoApiError):
            await client.get_rates(_scenario(), lender_id=61)
