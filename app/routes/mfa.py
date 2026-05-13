"""POST /mfa/{session_id}/code — accepts MFA code from the UI."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.mfa.bridge import MfaAlreadySubmitted, MfaUnknownSession

router = APIRouter()


class CodePayload(BaseModel):
    code: str


@router.post("/mfa/{session_id}/code")
async def submit_code(
    session_id: str, payload: CodePayload, request: Request,
) -> dict[str, str]:
    bridge = request.app.state.mfa
    try:
        bridge.submit_code(session_id, payload.code)
    except MfaUnknownSession as e:
        raise HTTPException(404, str(e)) from e
    except MfaAlreadySubmitted as e:
        raise HTTPException(409, str(e)) from e
    return {"status": "accepted"}
