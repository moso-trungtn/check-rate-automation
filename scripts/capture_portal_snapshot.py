"""One-shot helper to record a portal's result page for snapshot tests.

Usage:
    CHECK_RATE_PASSPHRASE=... uv run python -m scripts.capture_portal_snapshot ad_mortgage \
        --target-rate 6.875 \
        --out tests/portals/ad_mortgage/fixtures/result.html
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import click
from playwright.async_api import async_playwright

import app.portals.ad_mortgage  # noqa: F401  # pyright: ignore[reportUnusedImport]  — register adapter
from app.mfa.bridge import MfaBridge
from app.models import (
    LoanType,
    Occupancy,
    PropertyType,
    Purpose,
    Scenario,
)
from app.portals.base import get_adapter
from app.secrets.store import CredentialsStore, MissingStore


def _demo_scenario(target_rate: Decimal) -> Scenario:
    return Scenario(
        loan_amount=Decimal("400000"),
        credit_score=740,
        property_value=Decimal("500000"),
        ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY,
        property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE,
        loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL,
        target_rate=target_rate,
    )


async def _capture(
    lender: str,
    target_rate: Decimal,
    out: Path,
    creds_path: Path,
    passphrase: str,
) -> None:
    adapter = get_adapter(lender)
    store = CredentialsStore(path=creds_path, passphrase=passphrase)
    try:
        creds = store.get(lender)
    except (MissingStore, KeyError):
        creds = None

    mfa_bridge = MfaBridge()
    session_id = uuid4().hex
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await adapter.ensure_logged_in(page, creds, mfa_bridge, session_id)
        await adapter.fill_scenario(page, _demo_scenario(target_rate))
        await adapter.submit(page)
        result = await adapter.parse_result(page, target_rate)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(await page.content())
        click.echo(f"saved {out}")
        click.echo(f"parsed final_price={result.final_price}")
        await browser.close()


@click.command()
@click.argument("lender")
@click.option(
    "--target-rate",
    type=str,
    default="6.875",
    help="Target rate as a Decimal-compatible string (e.g. 6.875).",
)
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    required=True,
    help="Output path for the page HTML snapshot.",
)
@click.option(
    "--credentials",
    "credentials_path",
    type=click.Path(path_type=Path),
    default=Path("data/credentials.enc"),
)
@click.option(
    "--passphrase",
    default=lambda: os.environ.get("CHECK_RATE_PASSPHRASE", ""),
    help="Passphrase for the encrypted credentials store.",
)
def main(
    lender: str,
    target_rate: str,
    out: Path,
    credentials_path: Path,
    passphrase: str,
) -> None:
    if not passphrase:
        raise click.UsageError("Pass --passphrase or set CHECK_RATE_PASSPHRASE")
    asyncio.run(_capture(lender, Decimal(target_rate), out, credentials_path, passphrase))


if __name__ == "__main__":
    main()
