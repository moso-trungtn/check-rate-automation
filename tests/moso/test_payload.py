from decimal import Decimal
from typing import Any

from app.models import (
    LoanType,
    Occupancy,
    PropertyType,
    Purpose,
    Scenario,
)
from app.moso.payload import scenario_to_request


def _scenario(**over: Any) -> Scenario:
    base: dict[str, Any] = dict(
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
    return Scenario(**(base | over))


def test_payload_uses_ordinals() -> None:
    p = scenario_to_request(_scenario(), lender_id=61)
    assert p["loan_amount"] == 400000
    assert p["credit_score"] == 740
    assert p["property_value"] == 500000
    assert p["loan_type"] == 0  # conventional
    assert p["alert_lender"] == 61
    assert p["alert_lenders"] == [61]
    assert p["loan_program_group"] == 2  # FIXED_30
    assert p["get_all_rates"] is True
    assert p["kind"] == "Rate"
    assert p["channel"] is None


def test_payload_purpose_mapping() -> None:
    # Verified live against /exec/GetRatesOp for AD Mortgage:
    #   0 → Refinance, 1 → Cash Out, 2 → Purchase.
    assert scenario_to_request(_scenario(purpose=Purpose.REFI), 61)["purpose"] == 0
    assert scenario_to_request(_scenario(purpose=Purpose.CASHOUT), 61)["purpose"] == 1
    assert scenario_to_request(_scenario(purpose=Purpose.PURCHASE), 61)["purpose"] == 2


def test_payload_occupancy_mapping() -> None:
    assert scenario_to_request(_scenario(occupancy=Occupancy.PRIMARY), 61)["occupancy"] == 0
    assert scenario_to_request(_scenario(occupancy=Occupancy.SECOND), 61)["occupancy"] == 1
    assert scenario_to_request(_scenario(occupancy=Occupancy.INVESTMENT), 61)["occupancy"] == 2


def test_payload_property_type_mapping() -> None:
    sfr = scenario_to_request(_scenario(property_type=PropertyType.SFR), 61)
    condo = scenario_to_request(_scenario(property_type=PropertyType.CONDO), 61)
    pud = scenario_to_request(_scenario(property_type=PropertyType.PUD), 61)
    two_four = scenario_to_request(_scenario(property_type=PropertyType.TWO_TO_FOUR), 61)
    assert sfr["property_type"] == 0
    assert condo["property_type"] == 1
    assert pud["property_type"] == 2
    assert two_four["property_type"] == 3
