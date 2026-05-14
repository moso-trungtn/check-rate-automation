from decimal import Decimal
from typing import Any

from app.models import (
    AttachmentType,
    CompensationType,
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


def test_payload_includes_new_fields() -> None:
    p = scenario_to_request(
        _scenario(
            state="CA", zip="95132", county_name="Santa Clara",
            debt_to_income=42,
            first_time_home_buyer=True,
            has_self_employed=True,
            total_number_properties=2, financed_properties=2,
            actual_number_of_units=3,
            attachment_type=AttachmentType.ATTACHED,
            lock_period=45,
            impounds=False,
            has_equity_loan=True,
            waive_lender_fee=True,
            compensation_type=CompensationType.LENDER_PAID,
            borrower_paid_compensation=Decimal("1.5"),
        ),
        lender_id=61,
    )
    assert p["state"] == "CA"
    assert p["zip"] == "95132"
    assert p["county_name"] == "Santa Clara"
    assert p["debt_to_income"] == 42
    assert p["first_time_home_buyer"] is True
    assert p["has_self_employed"] is True
    assert p["total_number_properties"] == 2
    assert p["financed_properties"] == 2
    assert p["actual_number_of_units"] == 3
    assert p["attachment_type"] == 0  # ATTACHED → 0
    assert p["lock_period"] == 45
    assert p["impounds"] is False
    assert p["has_equity_loan"] is True
    assert p["waive_lender_fee"] is True
    assert p["compensation_type"] == 0  # LENDER_PAID → 0
    assert p["borrower_paid_compensation"] == 1.5


def test_payload_defaults_preserve_compat() -> None:
    """A Scenario built with only the legacy required fields should still
    produce a valid GetRatesOp body via the new defaults."""
    p = scenario_to_request(_scenario(), lender_id=61)
    assert p["state"] == "VA"
    assert p["zip"] == "20155"
    assert p["county_name"] == "Prince William"
    assert p["debt_to_income"] == 40
    assert p["first_time_home_buyer"] is False
    assert p["has_self_employed"] is False
    assert p["actual_number_of_units"] == 1
    assert p["lock_period"] == 30
    assert p["impounds"] is True
    assert p["has_equity_loan"] is False
    assert p["waive_lender_fee"] is False
    assert p["compensation_type"] == 1  # BORROWER_PAID
    assert p["borrower_paid_compensation"] == 1.0


def test_payload_property_type_mapping() -> None:
    sfr = scenario_to_request(_scenario(property_type=PropertyType.SFR), 61)
    condo = scenario_to_request(_scenario(property_type=PropertyType.CONDO), 61)
    pud = scenario_to_request(_scenario(property_type=PropertyType.PUD), 61)
    two_four = scenario_to_request(_scenario(property_type=PropertyType.TWO_TO_FOUR), 61)
    assert sfr["property_type"] == 0
    assert condo["property_type"] == 1
    assert pud["property_type"] == 2
    assert two_four["property_type"] == 3
