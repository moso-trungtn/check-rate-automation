"""Pure comparison engine: MosoResult + PortalResult -> ComparisonReport."""

from __future__ import annotations

import re
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

# MOSO and portals describe the same LLPA with different label wording —
# MOSO has full context: "FICO (740 - 759) and 75 < LTV <= 80"
# Portal has shorter form: "FICO 740 - 759 and Purchase"
# Both are the SAME adjustment for FICO bucket 740-759, but the surrounding
# context (LTV/Purpose) appears on opposite sides. The most reliable signal
# of equality is the FICO range itself.
_FICO_RANGE_RE = re.compile(r"fico\s*\(?\s*(\d{3})\s*-\s*(\d{3})\s*\)?", re.IGNORECASE)


def normalize_label(label: str) -> str:
    """Reduce a label to a comparison-stable key.

    If the label contains a FICO range, we collapse to just that range
    ("fico 740-759") so MOSO-style and portal-style FICO LLPA labels
    match each other. Otherwise we just lowercase + collapse whitespace.
    """
    s = " ".join(label.lower().split())
    fico = _FICO_RANGE_RE.search(s)
    if fico:
        return f"fico {fico.group(1)}-{fico.group(2)}"
    return s


def _index(adjustments: list[Adjustment]) -> dict[str, tuple[str, Decimal]]:
    """Map normalized-key → (display_label, amount).

    Keeps the original label for display purposes when multiple raw labels
    normalize to the same key (we keep the first one we see).
    """
    out: dict[str, tuple[str, Decimal]] = {}
    for a in adjustments:
        key = normalize_label(a.label)
        if key not in out:
            out[key] = (a.label, a.amount)
    return out


def _values_match(
    m_val: Decimal, p_val: Decimal, tolerance: Decimal,
) -> bool:
    """Two adjustment values are considered equal when their MAGNITUDES
    agree within tolerance. MOSO and lender portals often use opposite
    sign conventions for the same LLPA (MOSO writes a debit as +0.875
    while the portal writes the same as -0.875), so the absolute values
    are what's economically meaningful for "is this adjustment present
    with the right magnitude?".
    """
    if abs(abs(m_val) - abs(p_val)) <= tolerance:
        return True
    return False


def compare(
    scenario: Scenario,
    lender: str,
    moso: MosoResult,
    portal: PortalResult,
    tolerance: Decimal,
) -> ComparisonReport:
    mismatches: list[Mismatch] = []

    # Final-price comparison stays signed (sign convention is consistent
    # for the rate-sheet price column on both sides — both are negative
    # for lender credits, both positive for points).
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
        m_entry = moso_idx.get(label)
        p_entry = portal_idx.get(label)
        m_val = m_entry[1] if m_entry else None
        p_val = p_entry[1] if p_entry else None
        if m_val is None or p_val is None:
            # One side has this adjustment, the other doesn't → real
            # missing-on-one-side mismatch (e.g. "conventional purchase
            # promo" is on the portal but MOSO's model lacks it).
            mismatches.append(
                Mismatch(
                    field=f"adjustment:{label}",
                    moso_value=m_val,
                    portal_value=p_val,
                    delta=None,
                )
            )
        else:
            # Both sides have it — compare by absolute value because of
            # opposite sign conventions. Only flag a mismatch if the
            # magnitudes actually differ.
            if not _values_match(m_val, p_val, tolerance):
                mismatches.append(
                    Mismatch(
                        field=f"adjustment:{label}",
                        moso_value=m_val,
                        portal_value=p_val,
                        delta=p_val - m_val,
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
