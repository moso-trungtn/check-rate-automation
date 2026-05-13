"""FastAPI application factory."""
from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

import app.portals.ad_mortgage  # noqa: F401  # pyright: ignore[reportUnusedImport]  — register adapter
from app.config import Settings
from app.events.bus import EventBus
from app.mfa.bridge import MfaBridge
from app.moso.client import MosoClient
from app.moso.facade import MosoFacade
from app.moso.headers import load_headers
from app.orchestrator import Orchestrator
from app.portals.base import get_adapter
from app.routes.compare import router as compare_router
from app.routes.events import router as events_router
from app.secrets.store import CredentialsStore

LENDER_IDS: dict[str, int] = {"ad_mortgage": 61}
LENDER_ALIASES: dict[str, str] = {"ad_mortgage": "AD Mortgage"}


def create_app() -> FastAPI:
    log = structlog.get_logger("check-rate")
    settings = Settings()  # type: ignore[call-arg]

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # In tests, the harness sets this env var so we skip launching a real browser.
        if os.environ.get("CHECK_RATE_TESTING") == "1":
            app.state.settings = settings
            yield
            return
        http = httpx.AsyncClient()
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        try:
            moso_headers = load_headers(settings.moso_headers_file)
            facade = MosoFacade(
                client=MosoClient(
                    settings.moso_base_url, http, headers=moso_headers,
                ),
                lender_id_table=LENDER_IDS,
                alias_table=LENDER_ALIASES,
            )
            bus = EventBus()
            mfa = MfaBridge()
            secrets = CredentialsStore(
                path=settings.data_dir / "credentials.enc",
                passphrase=settings.check_rate_passphrase or "",
            )
            orchestrator = Orchestrator(
                moso_facade=facade,
                adapter_factory=get_adapter,
                browser=browser,
                bus=bus,
                mfa_bridge=mfa,
                secrets=secrets,
                tolerance=settings.compare_tolerance,
                reports_dir=settings.data_dir / "reports",
                sessions_dir=settings.data_dir / "sessions",
            )
            app.state.bus = bus
            app.state.mfa = mfa
            app.state.orchestrator = orchestrator
            app.state.settings = settings
            yield
        finally:
            await browser.close()
            await playwright.stop()
            await http.aclose()

    fastapi_app = FastAPI(lifespan=lifespan)
    fastapi_app.include_router(compare_router)
    fastapi_app.include_router(events_router)
    static_dir = Path(__file__).parent.parent / "static"
    template_dir = Path(__file__).parent.parent / "templates"
    if static_dir.exists():
        fastapi_app.mount(
            "/static", StaticFiles(directory=static_dir), name="static",
        )
    templates = Jinja2Templates(directory=str(template_dir))

    @fastapi_app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:  # pyright: ignore[reportUnusedFunction]
        return templates.TemplateResponse(
            request=request, name="index.html", context={},
        )

    log.info("app_created")
    return fastapi_app
