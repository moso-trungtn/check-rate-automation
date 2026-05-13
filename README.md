# check-rate

Compare MOSO's pricing against a lender's portal for a single scenario.

## v1 status

- Lender: **AD Mortgage** (`https://aim.admortgage.com`, AIM portal, requires login)
- Program: 30yr Fixed Conventional
- Compare mode: one user-chosen rate; final price only (LLPA breakdown deferred to v1.5)
- MOSO endpoint: `POST /exec/GetRatesOp` (full rate ladder + adjustments in one call)

## Setup

Requires Python 3.11+ and `uv` (`brew install uv` on macOS).

    uv sync
    uv run playwright install chromium
    cp .env.example .env       # edit values, especially MOSO_BASE_URL and CHECK_RATE_PASSPHRASE

### Populate MOSO auth

Create `data/moso-headers.json` with either an API key:

    {"Authorization": "<your-api-key>"}

or a full session (XSRF + user + Cookie). See `docs/moso-endpoint-recon.md` for the full list of headers and how to capture them from DevTools.

### Populate lender credentials

    export CHECK_RATE_PASSPHRASE='<your-passphrase>'
    uv run python -m scripts.manage_secrets \
      --path data/credentials.enc --passphrase "$CHECK_RATE_PASSPHRASE" \
      add ad_mortgage --username '<email>' --password '<password>'

The encrypted file lives in `data/` (gitignored).

## Run

    uv run uvicorn --factory app.main:create_app --reload --port 8080
    # open http://localhost:8080

Quote a scenario in the form, click Compare, watch the progress panel, see the diff against AD Mortgage's portal.

## Tests

    uv run pytest                                                # unit + snapshot
    CHECK_RATE_PASSPHRASE=... uv run pytest -m live              # hit real portal (manual)

The live test logs into AD Mortgage with stored credentials and runs the end-to-end flow.

## Capturing portal snapshots

When AD Mortgage redesigns the result grid, refresh the test snapshot:

    CHECK_RATE_PASSPHRASE=... uv run python -m scripts.capture_portal_snapshot \
      ad_mortgage --target-rate 6.875 \
      --out tests/portals/ad_mortgage/fixtures/result_30yr_fixed.html

## Adding a new lender

1. Record the portal flow: `uv run playwright codegen <url>`
2. Create `app/portals/<lender>/adapter.py` modeled on `ad_mortgage/adapter.py`. Import it in `app/portals/<lender>/__init__.py` to auto-register.
3. Add the lender to `LENDER_IDS` and `LENDER_ALIASES` in `app/main.py`.
4. Add a snapshot test in `tests/portals/<lender>/test_adapter.py` with a synthetic DOM (Playwright `set_content`).
5. Smoke-test live: `CHECK_RATE_PASSPHRASE=... uv run pytest -m live -k <lender>`.

## Design + plan

- Spec: `docs/superpowers/specs/2026-05-13-check-rate-design.md`
- Plan: `docs/superpowers/plans/2026-05-13-check-rate-v1.md`
- MOSO recon: `docs/moso-endpoint-recon.md`
- AD Mortgage recon: `docs/ad-mortgage-recon.md`
