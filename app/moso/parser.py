"""Parse a GetRatesOp response into typed rate rows."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models import Adjustment

# Names that are 1:1 aliases of fields already on RateRow / shadowed below.
_COMMISSION_ROLLUPS = frozenset(
    {
        "base price",
        "total adj",
        "adjusted price",
        "lender points",    # same value as "Adjusted Price"
        "lender credits",   # same value as "Adjusted Price"
    }
)
# Names that mark sums inside adjustment_detail (we expose the underlying
# leaf rows, not the parent totals).
_ADJUSTMENT_DETAIL_ROLLUPS = frozenset({"total"})


class RowNotFound(LookupError):
    pass


@dataclass(frozen=True)
class RateRow:
    """A single rate offering from GetRatesOp, with both pricing and cost detail.

    MOSO's commission_detail combines lender-rate-sheet + broker comp + costs;
    its adjustment_detail is the pure pricing LLPAs (matches what MOSO's UI
    calls "Pricing Adjustment"). v1 surfaces both so the UI mirrors MOSO.
    """

    alias: str
    loan_program: str
    program: str | None
    mode: str | None
    interest_rate: Decimal
    # ----- Rate-sheet pricing (commission_detail rollups) -----
    base_price: Decimal
    # MOSO's commission_detail "Total Adj": LLPA + broker comp + costs combined
    commission_total_adj: Decimal
    # MOSO's commission_detail "Adjusted Price" / "Lender Credits": broker net
    adjusted_price_full: Decimal
    # ----- Pricing-only (adjustment_detail) -----
    # Sum of itemized pricing LLPAs (matches MOSO UI's "Total Adj" in the
    # per-rate detail view and "Total" of the Pricing Adjustment section).
    pricing_adjustment_total: Decimal
    # base_price + pricing_adjustment_total. Matches MOSO UI's
    # "Adjusted Price" / "Lender Credits" (before broker comp).
    lender_credits: Decimal
    # ----- Itemized lists -----
    # Pricing-only LLPAs from adjustment_detail (FICO/LTV-based, etc.)
    pricing_adjustments: list[Adjustment]
    # Everything else from commission_detail: Broker Comp, individual fees,
    # Total Closing Costs, etc.
    commission_items: list[Adjustment]


def _parse_commission(
    detail: dict[str, Any],
) -> tuple[Decimal, Decimal, Decimal, list[Adjustment]]:
    """Pull (base_price, total_adj, adjusted_price, leftover items) from
    commission_detail._rows. Leftover = everything that is not one of the
    five duplicate-of-RateRow-field rollups."""
    base_price = Decimal("0")
    total_adj = Decimal("0")
    adjusted_price = Decimal("0")
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
            adjusted_price = amount
        elif lname in _COMMISSION_ROLLUPS:
            continue
        else:
            items.append(Adjustment(label=name, amount=amount))
    return base_price, total_adj, adjusted_price, items


def _parse_adjustment_detail(
    detail: dict[str, Any],
) -> tuple[Decimal, list[Adjustment]]:
    """Pull (total, itemized leaf adjustments) from adjustment_detail._rows.

    Skips group headers (is_group=True) and the explicit "Total" rollup row,
    so callers see only the leaf adjustments and an authoritative total.
    """
    total = Decimal("0")
    items: list[Adjustment] = []
    for row in detail.get("_rows", []):
        name = str(row.get("adjustment_name", "")).strip()
        value = row.get("adjustment_value")
        if value is None:
            continue
        amount = Decimal(str(value))
        lname = name.lower()
        if lname in _ADJUSTMENT_DETAIL_ROLLUPS:
            # The explicit "Total" leaf is authoritative; use it if present.
            if not row.get("is_group"):
                total = amount
            continue
        if row.get("is_group"):
            continue
        items.append(Adjustment(label=name, amount=amount))
    if total == 0 and items:
        # Fall back to summing leaf items if no "Total" row appeared.
        total = sum((a.amount for a in items), start=Decimal("0"))
    return total, items


def parse_response(payload: dict[str, Any]) -> list[RateRow]:
    rows: list[RateRow] = []
    for raw in payload.get("_rows", []):
        base, c_total, c_adjusted, c_items = _parse_commission(
            raw.get("commission_detail") or {},
        )
        p_total, p_items = _parse_adjustment_detail(
            raw.get("adjustment_detail") or {},
        )
        lender_credits = base + p_total
        rows.append(
            RateRow(
                alias=str(raw.get("alias", "")),
                loan_program=str(raw.get("loan_program", "")),
                program=raw.get("program"),
                mode=raw.get("mode"),
                interest_rate=Decimal(str(raw.get("interest_rate"))),
                base_price=base,
                commission_total_adj=c_total,
                adjusted_price_full=c_adjusted,
                pricing_adjustment_total=p_total,
                lender_credits=lender_credits,
                pricing_adjustments=p_items,
                commission_items=c_items,
            )
        )
    return rows


def find_row(rows: list[RateRow], alias: str, rate: Decimal) -> RateRow:
    for r in rows:
        if r.alias == alias and r.interest_rate == rate:
            return r
    raise RowNotFound(f"No row for alias={alias!r} rate={rate}")
