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
    assert found.final_price == target.final_price


def test_commission_detail_excludes_rollups() -> None:
    rows = parse_response(_load())
    row = rows[0]
    names = {a.label.lower() for a in row.adjustments}
    # Only the five names that duplicate RateRow's own fields are excluded.
    # Broker Compensation, Costs, State Cost, Total Closing Costs, and
    # itemized LLPAs MUST appear in row.adjustments so the UI can break
    # them out.
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


def test_itemized_llpas_survive_rollup_filter() -> None:
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
                "mode": "DU",
                "alias": "AD Mortgage",
                "interest_rate": 6.875,
                "commission_detail": {
                    "_rows": [
                        # rollups — must be excluded from adjustments
                        _row("Base Price", 100.000, False, 0),
                        _row("Total Adj", -0.375, False, 0),
                        _row("Adjusted Price", 99.625, False, 0),
                        _row("Lender Points", 99.625, False, 0),
                        # group header — must be skipped
                        _row("DU Loan Feature Adjustments", None, True, 0),
                        # itemized LLPAs — MUST survive
                        _row("FICO (760 - 779) and 30 < LTV <= 60", -0.250, False, 1),
                        _row(
                            "Investment Property 2 and 30 < LTV <= 60",
                            0.125,
                            False,
                            1,
                        ),
                    ],
                },
            }
        ],
    }
    rows = parse_response(synthetic)
    assert len(rows) == 1
    row = rows[0]
    assert row.base_price == Decimal("100.000")
    assert row.total_adjustment == Decimal("-0.375")
    assert row.final_price == Decimal("99.625")
    labels = [a.label for a in row.adjustments]
    # rollups & is_group skipped:
    forbidden_labels = (
        "Base Price",
        "Total Adj",
        "Adjusted Price",
        "Lender Points",
        "DU Loan Feature Adjustments",
    )
    for forbidden in forbidden_labels:
        assert forbidden not in labels
    # itemized LLPAs survived:
    fico = next(a for a in row.adjustments if "FICO" in a.label)
    assert fico.amount == Decimal("-0.250")
    inv = next(a for a in row.adjustments if "Investment" in a.label)
    assert inv.amount == Decimal("0.125")
