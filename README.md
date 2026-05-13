# check-rate

Compare MOSO pricing against a lender's portal for a single scenario.

## Setup

Requires Python 3.11+ and `uv` (`brew install uv` on macOS).

    uv sync
    uv run playwright install chromium
    cp .env.example .env   # edit values

## Run

    uv run uvicorn app.main:app --reload --port 8080
    # open http://localhost:8080

## Tests

    uv run pytest           # unit + snapshot
    uv run pytest -m live   # hit live portal (manual)

See `docs/superpowers/specs/2026-05-13-check-rate-design.md` for design.
