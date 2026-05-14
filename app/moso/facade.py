"""Thin facade that turns a Scenario into a MosoResult via GetRatesOp."""
from __future__ import annotations

from app.models import MosoResult, Scenario
from app.moso.client import MosoClient
from app.moso.parser import RateRow

# MOSO returns multiple "AD Mortgage" rows per rate distinguished by the
# `program` field: "Fannie Mae" (plain), "HomeReady", "Home Possible
# Freddie Mac". v1 compares only the plain conventional product, so any
# program whose name contains these income-restricted keywords is filtered
# out. The list is per-lender to make it easy to override later.
_EXCLUDED_PROGRAM_KEYWORDS = (
    "homeready",
    "home ready",
    "home possible",
    "homepossible",
)


def _is_excluded_program(program: str | None) -> bool:
    if not program:
        return False
    p = program.lower()
    return any(kw in p for kw in _EXCLUDED_PROGRAM_KEYWORDS)


class LenderAliasNotFound(LookupError):
    """No row with the expected alias + rate was present in the GetRatesOp response."""


class MosoFacade:
    def __init__(
        self,
        client: MosoClient,
        lender_id_table: dict[str, int],
        alias_table: dict[str, str],
    ) -> None:
        self.client = client
        self.lender_id_table = lender_id_table
        self.alias_table = alias_table

    async def quote(self, scenario: Scenario, lender: str) -> MosoResult:
        lender_id = self.lender_id_table[lender]
        expected_alias = self.alias_table[lender]
        rows = await self.client.get_rates(scenario, lender_id)
        matching: list[RateRow] = [
            r for r in rows
            if r.alias == expected_alias
            and r.interest_rate == scenario.target_rate
            and not _is_excluded_program(r.program)
        ]
        if matching:
            r = matching[0]
            # MOSO's UI shows pricing in this hierarchy:
            #   Base Price + Total Adj (LLPAs only) = Lender Credits
            #   then Broker Comp + Costs are applied on top.
            # The portal's "Final Price" column == Lender Credits, so
            # that's what we compare. We expose:
            #   adjustment_total    → r.pricing_adjustment_total (LLPA sum,
            #                          matches MOSO UI "Total Adj")
            #   final_price         → r.lender_credits (base + LLPA total,
            #                          matches MOSO UI "Lender Credits")
            #   adjustments         → r.pricing_adjustments (itemized LLPAs
            #                          like "FICO X-Y and LTV...")
            return MosoResult(
                base_price=r.base_price,
                adjustment_total=r.pricing_adjustment_total,
                final_price=r.lender_credits,
                adjustments=list(r.pricing_adjustments),
            )
        aliases = sorted({r.alias for r in rows})
        if not aliases:
            raise LenderAliasNotFound(
                "MOSO returned 0 rows — almost certainly an expired or invalid "
                "session. Refresh data/moso-headers.json by copying a fresh "
                "GetRatesOp request from DevTools (Network tab → Copy as cURL)."
            )
        if expected_alias in aliases:
            # Alias matched but the rate didn't. Surface the available rates
            # so the caller can correct their pick.
            available = sorted(r.interest_rate for r in rows if r.alias == expected_alias)
            raise LenderAliasNotFound(
                f"Rate {scenario.target_rate} not in {expected_alias} ladder. "
                f"Available rates: {[str(r) for r in available]}"
            )
        raise LenderAliasNotFound(
            f"MOSO returned rows but none for lender {expected_alias!r}. "
            f"Got aliases: {aliases}"
        )
