"""End-to-end comparison orchestrator."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.compare.engine import compare
from app.events.bus import Event, EventBus
from app.mfa.bridge import MfaBridge
from app.models import ComparisonReport, MosoResult, PortalResult, Scenario
from app.moso.facade import MosoFacade
from app.portals.base import PortalAdapter
from app.secrets.store import Credentials, CredentialsStore


class Orchestrator:
    def __init__(
        self,
        moso_facade: MosoFacade,
        adapter_factory: Callable[[str], PortalAdapter],
        browser: Any,
        bus: EventBus,
        mfa_bridge: MfaBridge,
        secrets: CredentialsStore,
        tolerance: Decimal,
        reports_dir: Path,
        sessions_dir: Path,
    ) -> None:
        self.moso_facade = moso_facade
        self.adapter_factory = adapter_factory
        self.browser = browser
        self.bus = bus
        self.mfa_bridge = mfa_bridge
        self.secrets = secrets
        self.tolerance = tolerance
        self.reports_dir = reports_dir
        self.sessions_dir = sessions_dir

    def _emit(self, sid: str, type_: str, data: dict[str, Any]) -> None:
        self.bus.publish(sid, Event(type=type_, data=data))

    async def run(self, session_id: str, scenario: Scenario, lender: str) -> ComparisonReport:
        try:
            moso_task = asyncio.create_task(self._run_moso(session_id, scenario, lender))
            portal_task = asyncio.create_task(self._run_portal(session_id, scenario, lender))
            moso_result, portal_result = await asyncio.gather(moso_task, portal_task)
        except Exception as e:
            self._emit(session_id, "error", {"step": "run", "message": str(e)})
            raise

        report = compare(scenario, lender, moso_result, portal_result, self.tolerance)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        (self.reports_dir / f"{report.id}.json").write_text(
            report.model_dump_json(indent=2),
        )
        self._emit(session_id, "done", {"report_id": report.id})
        return report

    async def _run_moso(self, sid: str, scenario: Scenario, lender: str) -> MosoResult:
        self._emit(sid, "progress", {"step": "moso_pricing", "status": "started"})
        result = await self.moso_facade.quote(scenario, lender)
        self._emit(sid, "progress", {"step": "moso_pricing", "status": "ok"})
        return result

    async def _run_portal(self, sid: str, scenario: Scenario, lender: str) -> PortalResult:
        adapter = self.adapter_factory(lender)
        creds: Credentials | None
        try:
            creds = self.secrets.get(lender)
        except FileNotFoundError:
            creds = None
        except KeyError:
            creds = None

        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        session_path = self.sessions_dir / f"{lender}.json"
        kwargs: dict[str, Any] = {}
        if session_path.exists():
            kwargs["storage_state"] = str(session_path)

        ctx = await self.browser.new_context(**kwargs)
        try:
            page = await ctx.new_page()
            self._emit(sid, "progress", {"step": "portal_login", "status": "started"})
            await adapter.ensure_logged_in(page, creds, self.mfa_bridge, sid)
            self._emit(sid, "progress", {"step": "portal_login", "status": "ok"})
            self._emit(sid, "progress", {"step": "portal_quote", "status": "started"})
            await adapter.fill_scenario(page, scenario)
            await adapter.submit(page)
            self._emit(sid, "progress", {"step": "portal_quote", "status": "ok"})
            self._emit(sid, "progress", {"step": "portal_parse", "status": "started"})
            result = await adapter.parse_result(page, scenario.target_rate)
            self._emit(sid, "progress", {"step": "portal_parse", "status": "ok"})
            return result
        finally:
            try:
                await ctx.storage_state(path=str(session_path))
            except Exception:  # noqa: BLE001
                pass
            await ctx.close()
