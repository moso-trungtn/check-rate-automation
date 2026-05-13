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
    # roll-up rows are excluded from the LLPA list
    for forbidden in (
        "base price",
        "total adj",
        "adjusted price",
        "lender points",
        "lender credits",
        "total closing costs",
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
