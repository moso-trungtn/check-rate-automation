"""Thin facade that turns a Scenario into a MosoResult via GetRatesOp."""
from __future__ import annotations

from app.models import MosoResult, Scenario
from app.moso.client import MosoClient


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
        for r in rows:
            if r.alias == expected_alias and r.interest_rate == scenario.target_rate:
                # Use MOSO's "Adjusted Price" (== Lender Credits == Lender Points)
                # as the value to compare against the portal's "Final Price"
                # column. This is the broker's net after MOSO applies all
                # adjustments + broker comp + costs.
                return MosoResult(
                    base_price=r.base_price,
                    adjustment_total=r.total_adjustment,
                    final_price=r.final_price,
                    adjustments=list(r.adjustments),
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
