"""POST /moso/session/from-curl — paste a cURL, save MOSO headers, reload client."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.moso.curl_parser import CurlParseError, parse_curl_to_headers

router = APIRouter()


class CurlPayload(BaseModel):
    curl: str


class SessionStatus(BaseModel):
    saved_keys: list[str]
    warning: str | None = None


@router.post("/moso/session/from-curl", response_model=SessionStatus)
async def session_from_curl(payload: CurlPayload, request: Request) -> SessionStatus:
    try:
        headers = parse_curl_to_headers(payload.curl)
    except CurlParseError as e:
        raise HTTPException(400, str(e)) from e

    warning = headers.pop("__warning__", None)

    settings = request.app.state.settings
    path = settings.moso_headers_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(headers, indent=2))

    # Hot-swap the headers on the in-memory MOSO client so the next
    # /compare uses them without restarting uvicorn.
    facade = getattr(request.app.state, "moso_facade", None)
    if facade is not None and hasattr(facade, "client"):
        facade.client.headers = headers  # type: ignore[attr-defined]

    return SessionStatus(saved_keys=sorted(headers.keys()), warning=warning)


@router.get("/moso/session/status")
async def session_status(request: Request) -> dict[str, object]:
    """Lightweight check: do we currently have a headers file on disk?"""
    settings = request.app.state.settings
    path = settings.moso_headers_file
    if not path.exists():
        return {"present": False, "keys": []}
    try:
        data: object = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"present": True, "keys": [], "invalid_json": True}
    if not isinstance(data, dict):
        return {"present": True, "keys": [], "invalid_shape": True}
    keys = sorted(str(k) for k in data)  # type: ignore[reportUnknownVariableType]
    return {"present": True, "keys": keys}
