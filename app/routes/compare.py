"""POST /compare and GET /report/{id}."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.models import Scenario

router = APIRouter()

_REPORT_ID_RE = re.compile(r"^[a-f0-9]{12}$")
_log = structlog.get_logger("check-rate.routes.compare")


def _log_task_result(task: asyncio.Task[Any]) -> None:
    exc = task.exception()
    if exc:
        _log.error("orchestrator_run_failed", error=str(exc), exc_info=exc)


class CompareRequest(BaseModel):
    lender: str
    scenario: Scenario


@router.post("/compare", status_code=202)
async def post_compare(req: CompareRequest, request: Request) -> dict[str, str]:
    sid = uuid4().hex
    orchestrator = request.app.state.orchestrator
    task = asyncio.create_task(orchestrator.run(sid, req.scenario, req.lender))
    task.add_done_callback(_log_task_result)
    return {"session_id": sid}


@router.get("/report/{report_id}")
async def get_report(report_id: str, request: Request) -> dict[str, Any]:
    if not _REPORT_ID_RE.match(report_id):
        raise HTTPException(400, "invalid report id")
    settings = request.app.state.settings
    path: Path = settings.data_dir / "reports" / f"{report_id}.json"
    if not path.exists():
        raise HTTPException(404, "report not found")
    return cast(dict[str, Any], json.loads(path.read_text()))
