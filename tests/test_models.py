from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.models import (
    Adjustment,
    ComparisonReport,
    LoanType,
    Mismatch,
    MosoResult,
    Occupancy,
    PortalResult,
    PropertyType,
    Purpose,
    Scenario,
)


def _scenario(**overrides: Any) -> Scenario:
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
    return Scenario(**(base | overrides))


def test_scenario_round_trip():
    s = _scenario()
    assert s.loan_amount == Decimal("400000")
    assert s.target_rate == Decimal("6.875")


def test_scenario_rejects_negative_loan_amount():
    with pytest.raises(ValidationError):
        _scenario(loan_amount=Decimal("-1"))


def test_scenario_rejects_fico_out_of_range():
    with pytest.raises(ValidationError):
        _scenario(credit_score=200)


def test_moso_result_final_price_relationship():
    r = MosoResult(
        base_price=Decimal("100.000"),
        adjustment_total=Decimal("-0.250"),
        final_price=Decimal("99.750"),
        adjustments=[Adjustment(label="FICO/LTV", amount=Decimal("-0.250"))],
    )
    assert r.source == "moso"


def test_portal_result_requires_snapshot_path():
    r = PortalResult(
        final_price=Decimal("99.500"),
        adjustments=[],
        raw_html_snapshot_path="/tmp/x.html",
        captured_at=datetime(2026, 5, 13, 12, 0, 0),
    )
    assert r.source == "portal"


def test_comparison_report_matches_flag():
    s = _scenario()
    moso = MosoResult(base_price=Decimal("100"), adjustment_total=Decimal("0"),
                      final_price=Decimal("100"), adjustments=[])
    portal = PortalResult(final_price=Decimal("100"), adjustments=[],
                          raw_html_snapshot_path="/tmp/x.html",
                          captured_at=datetime(2026, 5, 13))
    report = ComparisonReport(
        id="r1", scenario=s, lender="ad_mortgage",
        moso=moso, portal=portal, matches=True, mismatches=[],
        generated_at=datetime(2026, 5, 13),
    )
    assert report.matches is True


def test_mismatch_allows_none_sides():
    m = Mismatch(field="adjustment:foo", moso_value=Decimal("0.25"),
                 portal_value=None, delta=None)
    assert m.portal_value is None
