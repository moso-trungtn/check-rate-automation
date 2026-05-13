"""Pure comparison engine: MosoResult + PortalResult -> ComparisonReport."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models import (
    Adjustment,
    ComparisonReport,
    Mismatch,
    MosoResult,
    PortalResult,
    Scenario,
)


def normalize_label(label: str) -> str:
    return " ".join(label.lower().split())


def _index(adjustments: list[Adjustment]) -> dict[str, Decimal]:
    return {normalize_label(a.label): a.amount for a in adjustments}


def compare(
    scenario: Scenario,
    lender: str,
    moso: MosoResult,
    portal: PortalResult,
    tolerance: Decimal,
) -> ComparisonReport:
    mismatches: list[Mismatch] = []

    delta_final = portal.final_price - moso.final_price
    if abs(delta_final) > tolerance:
        mismatches.append(
            Mismatch(
                field="final_price",
                moso_value=moso.final_price,
                portal_value=portal.final_price,
                delta=delta_final,
            )
        )

    moso_idx = _index(moso.adjustments)
    portal_idx = _index(portal.adjustments)
    for label in sorted(set(moso_idx) | set(portal_idx)):
        m_val = moso_idx.get(label)
        p_val = portal_idx.get(label)
        if m_val is None or p_val is None:
            mismatches.append(
                Mismatch(
                    field=f"adjustment:{label}",
                    moso_value=m_val,
                    portal_value=p_val,
                    delta=None,
                )
            )
        else:
            delta = p_val - m_val
            if abs(delta) > tolerance:
                mismatches.append(
                    Mismatch(
                        field=f"adjustment:{label}",
                        moso_value=m_val,
                        portal_value=p_val,
                        delta=delta,
                    )
                )

    return ComparisonReport(
        id=uuid.uuid4().hex[:12],
        scenario=scenario,
        lender=lender,
        moso=moso,
        portal=portal,
        matches=len(mismatches) == 0,
        mismatches=mismatches,
        generated_at=datetime.now(UTC),
    )
