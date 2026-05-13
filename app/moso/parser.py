"""Parse a GetRatesOp response into typed rate rows."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models import Adjustment

_ROLLUP_NAMES = frozenset(
    {
        "base price",
        "total adj",
        "adjusted price",
        "lender points",
        "lender credits",
        "total closing costs",
        "borrower's final credits",
        "total cost",
        "investment cost",
        "state cost",
        "broker compensation",
        "costs",
        "estimated closing costs",
        "total",
    }
)


class RowNotFound(LookupError):
    pass


@dataclass(frozen=True)
class RateRow:
    alias: str
    loan_program: str
    program: str | None
    mode: str | None
    interest_rate: Decimal
    base_price: Decimal
    total_adjustment: Decimal
    final_price: Decimal
    adjustments: list[Adjustment]


def _parse_commission(
    detail: dict[str, Any],
) -> tuple[Decimal, Decimal, Decimal, list[Adjustment]]:
    base_price = Decimal("0")
    total_adj = Decimal("0")
    final_price = Decimal("0")
    items: list[Adjustment] = []
    for row in detail.get("_rows", []):
        if row.get("is_group"):
            continue
        name = str(row.get("adjustment_name", "")).strip()
        value = row.get("adjustment_value")
        if value is None:
            continue
        amount = Decimal(str(value))
        lname = name.lower()
        if lname == "base price":
            base_price = amount
        elif lname == "total adj":
            total_adj = amount
        elif lname == "adjusted price":
            final_price = amount
        elif lname in _ROLLUP_NAMES:
            continue
        else:
            items.append(Adjustment(label=name, amount=amount))
    return base_price, total_adj, final_price, items


def parse_response(payload: dict[str, Any]) -> list[RateRow]:
    rows: list[RateRow] = []
    for raw in payload.get("_rows", []):
        base, total, final, llpas = _parse_commission(raw.get("commission_detail") or {})
        rows.append(
            RateRow(
                alias=str(raw.get("alias", "")),
                loan_program=str(raw.get("loan_program", "")),
                program=raw.get("program"),
                mode=raw.get("mode"),
                interest_rate=Decimal(str(raw.get("interest_rate"))),
                base_price=base,
                total_adjustment=total,
                final_price=final,
                adjustments=llpas,
            )
        )
    return rows


def find_row(rows: list[RateRow], alias: str, rate: Decimal) -> RateRow:
    for r in rows:
        if r.alias == alias and r.interest_rate == rate:
            return r
    raise RowNotFound(f"No row for alias={alias!r} rate={rate}")
