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
                return MosoResult(
                    base_price=r.base_price,
                    adjustment_total=r.total_adjustment,
                    final_price=r.final_price,
                    adjustments=list(r.adjustments),
                )
        aliases = sorted({r.alias for r in rows})
        raise LenderAliasNotFound(
            f"No row in GetRatesOp for alias={expected_alias!r} rate={scenario.target_rate}. "
            f"Got aliases: {aliases}"
        )
