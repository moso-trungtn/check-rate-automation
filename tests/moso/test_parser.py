import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.moso.parser import RateRow, RowNotFound, find_row, parse_response

FIX = Path(__file__).parent / "fixtures"


def _load() -> dict[str, Any]:
    return json.loads((FIX / "getratesop_sample.json").read_text())


def test_parse_response_returns_rows() -> None:
    rows = parse_response(_load())
    assert len(rows) > 0
    assert all(isinstance(r, RateRow) for r in rows)
    assert all(r.base_price is not None for r in rows)


def test_find_row_by_lender_and_rate() -> None:
    rows = parse_response(_load())
    target = rows[0]
    found = next(
        r
        for r in rows
        if r.alias == target.alias and r.interest_rate == target.interest_rate
    )
    assert found.lender_credits == target.lender_credits


def test_commission_items_excludes_rollups() -> None:
    rows = parse_response(_load())
    row = rows[0]
    names = {a.label.lower() for a in row.commission_items}
    # Only names that duplicate RateRow's own fields are excluded.
    # Broker Compensation, Costs, State Cost, Total Closing Costs MUST
    # appear in row.commission_items so the UI can break them out.
    for forbidden in (
        "base price",
        "total adj",
        "adjusted price",
        "lender points",
        "lender credits",
    ):
        assert forbidden not in names


def test_filter_helpers() -> None:
    rows = parse_response(_load())
    aliases = {r.alias for r in rows}
    rates = {r.interest_rate for r in rows}
    assert len(aliases) >= 1
    assert len(rates) >= 1


def test_row_not_found_raises() -> None:
    rows = parse_response(_load())
    with pytest.raises(RowNotFound):
        find_row(rows, alias="Nonexistent Lender", rate=Decimal("99.000"))


def test_adjustment_detail_yields_pricing_llpas() -> None:
    """adjustment_detail._rows is MOSO's per-rate PRICING ADJUSTMENT section.
    Parser should pull itemized leaf LLPAs (skip group headers + 'Total')
    and expose them as pricing_adjustments with a matching total.
    """

    def _row(name: str, value: float | None, is_group: bool, level: int) -> dict[str, Any]:
        return {
            "adjustment_name": name,
            "adjustment_value": value,
            "is_group": is_group,
            "level": level,
            "adjustment_cost": None,
        }

    synthetic = {
        "_exact": True,
        "_rows": [
            {
                "loan_program": "30-Yr Fixed",
                "program": "Fannie Mae",
                "mode": None,
                "alias": "AD Mortgage",
                "interest_rate": 6.875,
                "commission_detail": {
                    "_rows": [
                        _row("Base Price", -3.07, False, 0),
                        _row("Total Adj", 0.875, False, 0),
                        _row("Adjusted Price", -2.195, False, 0),
                        _row("Lender Credits", -2.195, False, 0),
                        _row("Broker Compensation", 1.0, True, 0),  # group
                        _row("Broker Compensation", 1.0, False, 1),  # leaf
                        _row("Total Closing Costs", 1.305, False, 0),
                    ],
                },
                "adjustment_detail": {
                    "_rows": [
                        _row("Purchase Fico Ltv Adjustments", 0.875, True, 0),
                        _row("FICO (740 - 759) and 75 < LTV <= 80", 0.875, False, 1),
                        _row("Total", 0.875, False, 0),
                    ],
                },
            }
        ],
    }
    rows = parse_response(synthetic)
    assert len(rows) == 1
    row = rows[0]
    # Rate-sheet basics
    assert row.base_price == Decimal("-3.07")
    # MOSO UI's "Total Adj" comes from adjustment_detail, not commission_detail
    assert row.pricing_adjustment_total == Decimal("0.875")
    # base + LLPA total == Lender Credits (matches MOSO UI)
    assert row.lender_credits == Decimal("-2.195")
    # commission_detail still surfaces its OWN total + adjusted_price_full
    assert row.commission_total_adj == Decimal("0.875")  # same when no costs in Total Adj
    assert row.adjusted_price_full == Decimal("-2.195")
    # Pricing adjustments: only the leaf FICO row, no group header or "Total"
    pricing_labels = [a.label for a in row.pricing_adjustments]
    assert "FICO (740 - 759) and 75 < LTV <= 80" in pricing_labels
    assert "Total" not in pricing_labels
    assert "Purchase Fico Ltv Adjustments" not in pricing_labels  # group header
    # commission_items: broker comp + closing costs, excludes the five rollups
    comm_labels = {a.label for a in row.commission_items}
    assert "Broker Compensation" in comm_labels
    assert "Total Closing Costs" in comm_labels
    assert "Base Price" not in comm_labels
    assert "Lender Credits" not in comm_labels
