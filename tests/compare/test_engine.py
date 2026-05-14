from datetime import datetime
from decimal import Decimal

from app.compare.engine import compare, normalize_label
from app.models import (
    Adjustment,
    LoanType,
    MosoResult,
    Occupancy,
    PortalResult,
    PropertyType,
    Purpose,
    Scenario,
)


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


def _moso(final: str = "100.000", adjs: list[Adjustment] | None = None) -> MosoResult:
    return MosoResult(
        base_price=Decimal("100"),
        adjustment_total=Decimal("0"),
        final_price=Decimal(final),
        adjustments=adjs or [],
    )


def _portal(final: str = "100.000", adjs: list[Adjustment] | None = None) -> PortalResult:
    return PortalResult(
        final_price=Decimal(final),
        adjustments=adjs or [],
        raw_html_snapshot_path="/tmp/x.html",
        captured_at=datetime(2026, 5, 13),
    )


def test_normalize_label() -> None:
    # Plain labels collapse whitespace + lowercase.
    assert normalize_label("Sub Financing") == "sub financing"
    assert normalize_label("  FICO  /  LTV  ") == "fico / ltv"


def test_normalize_label_extracts_fico_range() -> None:
    """MOSO and portal use different surrounding context for the same FICO
    LLPA. Both should normalize to the same key."""
    moso_label = "FICO (740 - 759) and 75 < LTV <= 80"
    portal_label = "FICO 740 - 759 and Purchase"
    assert normalize_label(moso_label) == normalize_label(portal_label)
    assert normalize_label(moso_label) == "fico 740-759"


def test_llpa_match_ignoring_sign_convention() -> None:
    """MOSO writes a debit as +0.875; the portal writes the same as -0.875.
    Magnitudes match → no mismatch reported."""
    moso_adj = [Adjustment(label="FICO (740 - 759) and 75 < LTV <= 80",
                           amount=Decimal("0.875"))]
    portal_adj = [Adjustment(label="FICO 740 - 759 and Purchase",
                             amount=Decimal("-0.875"))]
    report = compare(
        _scenario(), "ad_mortgage",
        _moso("100", moso_adj), _portal("100", portal_adj),
        tolerance=Decimal("0.001"),
    )
    # FICO LLPA matched (same magnitude, opposite sign) — no mismatch on it.
    fico_mismatches = [
        m for m in report.mismatches if m.field.startswith("adjustment:fico")
    ]
    assert fico_mismatches == []


def test_real_world_only_promo_is_missing() -> None:
    """User's scenario: MOSO has just the FICO LLPA (positive), the portal
    has the same FICO LLPA (negative) plus a 'Conventional Purchase promo'.
    Expectation: report ONE LLPA mismatch — the missing promo, not three
    rows of confusion."""
    moso_adj = [
        Adjustment(label="FICO (740 - 759) and 75 < LTV <= 80",
                   amount=Decimal("0.875")),
    ]
    portal_adj = [
        Adjustment(label="FICO 740 - 759 and Purchase",
                   amount=Decimal("-0.875")),
        Adjustment(label="Conventional Purchase promo",
                   amount=Decimal("0.250")),
    ]
    report = compare(
        _scenario(), "ad_mortgage",
        _moso("100", moso_adj), _portal("100", portal_adj),
        tolerance=Decimal("0.001"),
    )
    adj_fields = [m.field for m in report.mismatches if m.field.startswith("adjustment:")]
    assert adj_fields == ["adjustment:conventional purchase promo"]
    promo = next(m for m in report.mismatches
                 if m.field == "adjustment:conventional purchase promo")
    assert promo.moso_value is None
    assert promo.portal_value == Decimal("0.250")


def test_exact_match() -> None:
    report = compare(
        _scenario(),
        "ad_mortgage",
        _moso("99.500", [Adjustment(label="FICO/LTV", amount=Decimal("-0.500"))]),
        _portal("99.500", [Adjustment(label="FICO/LTV", amount=Decimal("-0.500"))]),
        tolerance=Decimal("0.001"),
    )
    assert report.matches is True
    assert report.mismatches == []


def test_final_price_mismatch() -> None:
    report = compare(
        _scenario(),
        "ad_mortgage",
        _moso("100.000"),
        _portal("100.250"),
        tolerance=Decimal("0.001"),
    )
    assert report.matches is False
    assert len(report.mismatches) == 1
    m = report.mismatches[0]
    assert m.field == "final_price"
    assert m.delta == Decimal("0.250")


def test_within_tolerance_counts_as_match() -> None:
    report = compare(
        _scenario(),
        "ad_mortgage",
        _moso("100.000"),
        _portal("100.0005"),
        tolerance=Decimal("0.001"),
    )
    assert report.matches is True


def test_llpa_missing_on_portal_side() -> None:
    moso_adj = [Adjustment(label="Subordinate Financing", amount=Decimal("0.250"))]
    report = compare(
        _scenario(),
        "ad_mortgage",
        _moso("100", moso_adj),
        _portal("100"),
        tolerance=Decimal("0.001"),
    )
    fields = [m.field for m in report.mismatches]
    assert "adjustment:subordinate financing" in fields
    m = next(x for x in report.mismatches if x.field == "adjustment:subordinate financing")
    assert m.moso_value == Decimal("0.250")
    assert m.portal_value is None


def test_llpa_missing_on_moso_side() -> None:
    portal_adj = [Adjustment(label="Extra Fee", amount=Decimal("0.100"))]
    report = compare(
        _scenario(),
        "ad_mortgage",
        _moso("100"),
        _portal("100", portal_adj),
        tolerance=Decimal("0.001"),
    )
    m = next(x for x in report.mismatches if x.field == "adjustment:extra fee")
    assert m.moso_value is None
    assert m.portal_value == Decimal("0.100")


def test_llpa_value_mismatch_when_magnitudes_differ() -> None:
    """Magnitudes really differ (not just sign): flag as mismatch."""
    moso_adj = [Adjustment(label="FICO/LTV", amount=Decimal("-0.500"))]
    portal_adj = [Adjustment(label="FICO/LTV", amount=Decimal("-0.625"))]
    report = compare(
        _scenario(),
        "ad_mortgage",
        _moso("100", moso_adj),
        _portal("100", portal_adj),
        tolerance=Decimal("0.001"),
    )
    m = next(x for x in report.mismatches if x.field == "adjustment:fico/ltv")
    assert m.delta == Decimal("-0.125")


def test_report_has_id_and_timestamp() -> None:
    report = compare(
        _scenario(),
        "ad_mortgage",
        _moso(),
        _portal(),
        tolerance=Decimal("0.001"),
    )
    assert report.id
    assert report.lender == "ad_mortgage"
    assert report.generated_at is not None
