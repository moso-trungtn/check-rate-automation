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
                # The portal's "Final Price" column shows the lender's rate-sheet
                # price (== MOSO's base_price). MOSO's RateRow.final_price bakes
                # in broker compensation + costs from commission_detail, which the
                # lender portal does NOT show. To align apples-to-apples for v1
                # we use base_price as the comparison value. adjustment_total +
                # adjustments are kept for v1.5 LLPA work.
                return MosoResult(
                    base_price=r.base_price,
                    adjustment_total=r.total_adjustment,
                    final_price=r.base_price,
                    adjustments=list(r.adjustments),
                )
        aliases = sorted({r.alias for r in rows})
        raise LenderAliasNotFound(
            f"No row in GetRatesOp for alias={expected_alias!r} rate={scenario.target_rate}. "
            f"Got aliases: {aliases}"
        )
