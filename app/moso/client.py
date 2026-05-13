"""Async HTTP client for MOSO's GetRatesOp."""
from __future__ import annotations

import httpx

from app.models import Scenario
from app.moso.parser import RateRow, parse_response
from app.moso.payload import scenario_to_request


class MosoApiError(RuntimeError):
    pass


class MosoAuthError(MosoApiError):
    """Raised when MOSO returns 401/403 — session likely expired."""


class MosoClient:
    def __init__(
        self,
        base_url: str,
        http: httpx.AsyncClient,
        headers: dict[str, str],
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.headers = headers

    async def get_rates(self, scenario: Scenario, lender_id: int) -> list[RateRow]:
        url = f"{self.base_url}/exec/GetRatesOp"
        body = scenario_to_request(scenario, lender_id)
        try:
            resp = await self.http.post(
                url, json=body, headers=self.headers, timeout=30.0,
            )
        except httpx.HTTPError as e:
            raise MosoApiError(f"MOSO HTTP error: {e}") from e
        if resp.status_code in (401, 403):
            raise MosoAuthError(
                f"MOSO returned {resp.status_code}. Session likely expired — "
                f"refresh the headers file."
            )
        if resp.status_code >= 400:
            raise MosoApiError(f"MOSO HTTP {resp.status_code}: {resp.text[:200]}")
        return parse_response(resp.json())
