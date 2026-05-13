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
    base: str = "100.000",
    total: str = "-0.250",
    final: str = "99.750",
) -> RateRow:
    return RateRow(
        alias=alias,
        loan_program="30-Yr Fixed",
        program="Fannie Mae",
        mode="DU",
        interest_rate=Decimal(rate),
        base_price=Decimal(base),
        total_adjustment=Decimal(total),
        final_price=Decimal(final),
        adjustments=[Adjustment(label="FICO/LTV", amount=Decimal(total))],
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

    assert result.base_price == Decimal("100.000")
    assert result.adjustment_total == Decimal("-0.250")
    # v1: facade exposes RateRow.final_price (the "Adjusted Price" /
    # "Lender Credits" / "Lender Points" value from MOSO's commission_detail)
    # as MosoResult.final_price, since that's what we compare with the
    # portal's "Final Price" column.
    assert result.final_price == Decimal("99.750")
    assert result.adjustments[0].label == "FICO/LTV"


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
