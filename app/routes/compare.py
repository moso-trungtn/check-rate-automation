"""POST /compare and GET /report/{id}."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.models import Scenario

router = APIRouter()


class CompareRequest(BaseModel):
    lender: str
    scenario: Scenario


@router.post("/compare", status_code=202)
async def post_compare(req: CompareRequest, request: Request) -> dict[str, str]:
    sid = uuid4().hex
    orchestrator = request.app.state.orchestrator
    asyncio.create_task(orchestrator.run(sid, req.scenario, req.lender))
    return {"session_id": sid}


@router.get("/report/{report_id}")
async def get_report(report_id: str, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    path: Path = settings.data_dir / "reports" / f"{report_id}.json"
    if not path.exists():
        raise HTTPException(404, "report not found")
    return cast(dict[str, Any], json.loads(path.read_text()))
