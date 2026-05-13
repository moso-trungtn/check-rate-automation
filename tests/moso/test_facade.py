from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models import (
    Adjustment,
    LoanType,
    Occupancy,
    PropertyType,
    Purpose,
    Scenario,
)
from app.moso.facade import LenderAliasNotFound, MosoFacade
from app.moso.parser import RateRow


def _scenario(rate: str = "6.875") -> Scenario:
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
        target_rate=Decimal(rate),
    )


def _row(
    alias: str = "AD Mortgage",
    rate: str = "6.875",
    base: str = "-3.070",
    pricing_total: str = "0.875",
    lender_credits: str = "-2.195",
) -> RateRow:
    return RateRow(
        alias=alias,
        loan_program="30-Yr Fixed",
        program="Fannie Mae",
        mode=None,
        interest_rate=Decimal(rate),
        base_price=Decimal(base),
        commission_total_adj=Decimal(pricing_total),
        adjusted_price_full=Decimal(lender_credits),
        pricing_adjustment_total=Decimal(pricing_total),
        lender_credits=Decimal(lender_credits),
        pricing_adjustments=[
            Adjustment(label="FICO (740 - 759) and 75 < LTV <= 80",
                       amount=Decimal(pricing_total)),
        ],
        commission_items=[],
    )


@pytest.mark.asyncio
async def test_facade_picks_matching_row() -> None:
    client: Any = AsyncMock()
    client.get_rates.return_value = [
        _row(alias="Other", rate="6.875"),
        _row(alias="AD Mortgage", rate="6.875"),
        _row(alias="AD Mortgage", rate="7.000"),
    ]
    facade = MosoFacade(
        client=client,
        lender_id_table={"ad_mortgage": 61},
        alias_table={"ad_mortgage": "AD Mortgage"},
    )

    result = await facade.quote(_scenario(), lender="ad_mortgage")

    # Facade exposes the LLPA-only ("PRICING ADJUSTMENT") view that MOSO's UI
    # shows: base + pricing total = lender credits.
    assert result.base_price == Decimal("-3.070")
    assert result.adjustment_total == Decimal("0.875")
    assert result.final_price == Decimal("-2.195")  # base + pricing total
    assert result.adjustments[0].label == "FICO (740 - 759) and 75 < LTV <= 80"
    assert result.adjustments[0].amount == Decimal("0.875")


@pytest.mark.asyncio
async def test_facade_raises_if_alias_not_found() -> None:
    client: Any = AsyncMock()
    client.get_rates.return_value = [_row(alias="Other Lender", rate="6.875")]
    facade = MosoFacade(
        client=client,
        lender_id_table={"ad_mortgage": 61},
        alias_table={"ad_mortgage": "AD Mortgage"},
    )

    with pytest.raises(LenderAliasNotFound):
        await facade.quote(_scenario(), lender="ad_mortgage")


@pytest.mark.asyncio
async def test_facade_unknown_lender_key_raises() -> None:
    client: Any = AsyncMock()
    facade = MosoFacade(client=client, lender_id_table={}, alias_table={})
    with pytest.raises(KeyError):
        await facade.quote(_scenario(), lender="ad_mortgage")
