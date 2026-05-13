# check-rate: MOSO vs Lender Portal Pricing Comparison — Design

**Date:** 2026-05-13
**Author:** trung.thach@loanfactory.com
**Status:** Draft

## Goal

Build a standalone local tool that lets the user quote a loan scenario, then click "Compare" to drive a lender's portal with the same scenario and report whether the lender's price + LLPA breakdown matches MOSO's pricing for one chosen rate.

## Non-Goals (v1)

- Multi-user / hosted deployment. Runs locally on the user's machine.
- Comparing more than one rate per run.
- Programs other than 30yr Fixed Conventional.
- Captcha-solving. A portal with hard captcha is deferred to a later phase.
- Historical trend dashboards or analytics.
- Modifying MOSO's source tree. The tool calls MOSO over HTTP only.

## Decision Summary

| Topic | Decision |
|---|---|
| Deployment | Standalone product, separate repo at `/Users/trungthach/IdeaProjects/check-rate` |
| Scenario input | Manual entry in the tool's UI (v1) |
| Lender scope (v1) | One lender end-to-end — **AD Mortgage** (`https://admortgage.com/`, public pricing, no login) |
| MOSO pricing source | Existing `POST /execute/ComputeAdjustmentOp` for LLPA + read parsed ratesheet JSON for base price |
| MFA handling | Portal hits MFA → tool emits SSE event → UI prompts user → user submits code → Playwright continues |
| Credentials | Local encrypted file (`data/credentials.enc`) |
| Compare fields | Final price (price/points) + LLPA breakdown |
| Match strategy | One user-chosen target rate |
| Tech stack | Python 3.11 + FastAPI + Playwright (async) + Jinja/HTMX + SSE |
| Architecture | Single FastAPI process, in-process Playwright, pluggable `PortalAdapter` per lender |

## Architecture

Single Python process running `uvicorn` on `localhost:8080`. FastAPI handles HTTP and SSE. Playwright runs in async mode within the same process; chromium browser stays warm between comparison runs. Each lender's portal interaction is encapsulated in a `PortalAdapter` subclass — a hand-coded Python file with that portal's selectors and flow. Session state (cookies) is persisted per lender to `data/sessions/<lender>.json` and reused until the portal forces a re-login.

The tool calls MOSO **read-only** via HTTP:
- `POST {moso_base_url}/execute/ComputeAdjustmentOp` — returns the LLPA adjustment for a scenario.
- Reads parsed ratesheet JSON output from `moso-pricing` on local disk to obtain the base price at the chosen rate.

## Repo Layout

```
check-rate/
├── app/
│   ├── main.py                 # FastAPI entrypoint, lifecycle, browser bootstrapping
│   ├── config.py               # Settings (env-driven)
│   ├── models.py               # Pydantic: Scenario, MosoResult, PortalResult, ComparisonReport, Mismatch, Adjustment
│   ├── routes/
│   │   ├── compare.py          # POST /compare, GET /report/{id}
│   │   ├── events.py           # GET /events/stream (SSE)
│   │   └── mfa.py              # POST /mfa/{session_id}/code
│   ├── moso/
│   │   ├── client.py           # ComputeAdjustmentOp HTTP client
│   │   └── ratesheet.py        # Parsed-ratesheet JSON reader
│   ├── portals/
│   │   ├── base.py             # PortalAdapter ABC, register_adapter decorator, AdapterRegistry
│   │   └── ad_mortgage/
│   │       └── adapter.py      # First lender adapter
│   ├── compare/
│   │   └── engine.py           # compare(MosoResult, PortalResult) -> ComparisonReport
│   ├── mfa/
│   │   └── bridge.py           # MfaBridge: futures keyed by session_id
│   ├── secrets/
│   │   └── store.py            # Encrypted credentials loader
│   └── orchestrator.py         # run_comparison() async task
├── templates/
│   ├── index.html              # Scenario form + results panel
│   └── partials/
│       ├── mfa_modal.html
│       ├── progress.html
│       └── report.html
├── static/
│   ├── htmx.min.js
│   └── style.css
├── tests/
│   ├── compare/
│   ├── moso/
│   ├── mfa/
│   ├── secrets/
│   ├── portals/
│   │   └── ad_mortgage/
│   │       ├── fixtures/       # Snapshotted HTML
│   │       └── test_adapter.py
│   └── conftest.py
├── scripts/
│   └── capture_portal_snapshot.py
├── data/                       # gitignored
│   ├── sessions/
│   ├── credentials.enc
│   ├── reports/
│   ├── screenshots/
│   └── logs/
├── .env.example
├── .gitignore
├── pyproject.toml
├── uv.lock
└── README.md
```

## Data Models

```python
class Occupancy(str, Enum):
    PRIMARY = "primary_residence"
    SECOND = "second_home"
    INVESTMENT = "investment"

class PropertyType(str, Enum):
    SFR = "single_family"
    CONDO = "condo"
    PUD = "pud"
    TWO_TO_FOUR = "2_to_4_unit"

class Purpose(str, Enum):
    PURCHASE = "purchase"
    REFI = "refinance"
    CASHOUT = "cashout"

class LoanType(str, Enum):
    CONVENTIONAL = "conventional"

class Scenario(BaseModel):
    loan_amount: Decimal
    credit_score: int
    property_value: Decimal
    ltv: Decimal
    occupancy: Occupancy
    property_type: PropertyType
    purpose: Purpose
    loan_program: str            # v1: "30yr Fixed Conv"
    loan_type: LoanType
    target_rate: Decimal

class Adjustment(BaseModel):
    label: str
    amount: Decimal              # price points; cost positive, rebate negative

class MosoResult(BaseModel):
    base_price: Decimal
    adjustment_total: Decimal    # in price points
    final_price: Decimal
    adjustments: list[Adjustment]
    source: Literal["moso"] = "moso"

class PortalResult(BaseModel):
    final_price: Decimal
    adjustments: list[Adjustment]
    raw_html_snapshot_path: str
    source: Literal["portal"] = "portal"
    captured_at: datetime

class Mismatch(BaseModel):
    field: str                   # "final_price" or "adjustment:<label>"
    moso_value: Decimal | None
    portal_value: Decimal | None
    delta: Decimal | None

class ComparisonReport(BaseModel):
    id: str
    scenario: Scenario
    lender: str
    moso: MosoResult
    portal: PortalResult
    matches: bool
    mismatches: list[Mismatch]
    generated_at: datetime
```

All monetary and rate math uses `Decimal`. No `float`.

## End-to-End Flow

```
1. User opens UI → fills Scenario form → picks target_rate → clicks "Compare"

2. POST /compare {scenario, lender, target_rate}
   - session_id = uuid4()
   - Spawn async task run_comparison(session_id, ...)
   - Return 202 + {session_id}
   - UI opens SSE stream at /events/stream?session_id=...

3. run_comparison():
   A. MOSO side (parallel with B):
      moso_result = MosoClient.quote(scenario, lender, target_rate)
        - base_price ← ratesheet.read(lender, program, target_rate)
        - adj ← HTTP POST /execute/ComputeAdjustmentOp with Quote-shaped JSON
        - final_price = base_price + price_from_rate_adj(adj.adjustment)

   B. Portal side:
      adapter = AdapterRegistry.get(lender)
      browser context loaded with stored session for lender
      try:
        await adapter.ensure_logged_in(page, creds, mfa_bridge, session_id)
            (on MFA challenge: bridge.request_code(session_id, lender) → SSE
             "mfa_required" → UI modal → POST /mfa/{session_id}/code → future
             resolves → adapter types code → continues)
        await adapter.fill_scenario(page, scenario)
        await adapter.submit(page)
        portal_result = await adapter.parse_result(page, target_rate)
      finally:
        save context.storage_state → data/sessions/<lender>.json

   C. Compare:
      report = compare(moso_result, portal_result, tolerance=Decimal("0.001"))
      persist report → data/reports/{timestamp}_{lender}.json
      SSE emit "done" {report_id}

4. UI fetches /report/{id} → renders diff table.
```

## SSE Event Types

| Event | Data |
|---|---|
| `progress` | `{step: "moso_pricing"\|"portal_login"\|"portal_quote"\|"portal_parse", status: "started"\|"ok"\|"failed"}` |
| `mfa_required` | `{lender, prompt_label}` |
| `error` | `{step, message, screenshot_path?}` |
| `done` | `{report_id}` |

## Comparison Logic

`compare(moso: MosoResult, portal: PortalResult, tolerance: Decimal) -> ComparisonReport`:

1. Compute `delta_final = portal.final_price - moso.final_price`. If `abs(delta_final) > tolerance`, add `Mismatch(field="final_price", ...)`.
2. Build a dict keyed by normalized LLPA label on both sides. For each label:
   - Present on both: compare amounts with tolerance. Mismatch if outside tolerance.
   - On MOSO only: mismatch with `portal_value=None`.
   - On Portal only: mismatch with `moso_value=None`.
3. `matches = len(mismatches) == 0`.

Label normalization: lowercase, strip whitespace, collapse internal spaces. Future enhancement (post-v1): a `label_aliases.json` per adapter for portals whose labels diverge from MOSO's.

Default tolerance: `Decimal("0.001")` price points. Configurable via `.env`.

## Portal Adapter Contract

```python
class PortalAdapter(ABC):
    LENDER: ClassVar[str]
    LOGIN_URL: ClassVar[str]

    @abstractmethod
    async def ensure_logged_in(self, page, creds, mfa_bridge, session_id) -> None: ...

    @abstractmethod
    async def fill_scenario(self, page, scenario: Scenario) -> None: ...

    @abstractmethod
    async def submit(self, page) -> None: ...

    @abstractmethod
    async def parse_result(self, page, target_rate: Decimal) -> PortalResult: ...
```

Selectors live as class constants near the top of each adapter file (easier diffs when the portal changes). Adapters call `mfa_bridge.request_code(session_id, label)` inside `ensure_logged_in` if they detect an MFA wall — that's the only coupling to the SSE/MFA layer.

### Onboarding a New Lender

1. `playwright codegen <portal_url>` — record the manual flow.
2. Create `app/portals/<lender>/adapter.py` from a template; paste recorded selectors into class constants.
3. Capture HTML snapshots: `python scripts/capture_portal_snapshot.py <lender> --scenario <path>`.
4. Write snapshot test in `tests/portals/<lender>/test_adapter.py`.
5. Register the adapter via `@register_adapter("<lender>")` decorator.
6. Run live smoke: `pytest -m live -k <lender>`.

Estimated time per lender: half a day to one day, plus iteration when the portal changes.

## MFA Bridge

`MfaBridge` is an in-memory `dict[str, asyncio.Future]` keyed by `session_id`.

- `request_code(session_id, label, timeout=300s)` — creates future, emits SSE `mfa_required`, awaits future, returns code (or raises `MfaTimeout`).
- `submit_code(session_id, code)` — resolves the future. Idempotent guard: rejects second submission.

The future lives only in memory for the duration of one comparison run. If the FastAPI process restarts, in-flight comparisons are lost (acceptable — single-user local tool).

## Secrets

`data/credentials.enc` is a Fernet-encrypted JSON file. Key derived from a passphrase via `scrypt` (n=2^15, r=8, p=1). On startup the app reads `CHECK_RATE_PASSPHRASE` from env; if absent, it prompts in the terminal once and caches in memory.

Shape:
```json
{
  "lender_x": {"username": "...", "password": "...", "notes": "MFA via SMS"},
  "lender_y": {"username": "...", "password": "..."}
}
```

`app/secrets/store.py` exposes `get_credentials(lender) -> Credentials`. Never logs the decrypted values.

A small CLI (`scripts/manage_secrets.py`) supports `add`, `update`, `remove`, `list` operations on the encrypted file. The user's existing Excel sheet of lender URLs/credentials is imported once via `scripts/import_from_excel.py` (provided as a one-off, not a long-term API).

## Failure Modes

| Failure | Behavior |
|---|---|
| MOSO endpoint down | SSE `error` with `step="moso_pricing"`; comparison fails. |
| Ratesheet missing for lender | SSE `error` with `step="moso_pricing"`, message points at expected path. |
| Portal login fails (bad credentials) | Save screenshot to `data/screenshots/{correlation_id}/`; SSE `error`. |
| MFA timeout (5 min default) | Tear down browser context; SSE `error`. |
| Portal selector not found | Save screenshot + the failing selector in error message; SSE `error`. |
| Rate not present in portal result | `Mismatch` with `portal_value=None`. Comparison still completes. |
| Crash inside adapter | Browser context is always closed in `finally`; storage_state still saved if login succeeded; error surfaces to SSE. |

## Testing Strategy

**Unit (fast, pure):** pytest + pytest-asyncio. No browser, no network.
- `tests/compare/test_compare.py` — match, within-tolerance, outside-tolerance, missing LLPA both sides.
- `tests/moso/test_ratesheet_reader.py` — fixtures for known sheets.
- `tests/moso/test_client.py` — `httpx.MockTransport` for ComputeAdjustmentOp.
- `tests/mfa/test_bridge.py` — resolution, timeout, double-submit rejected.
- `tests/secrets/test_store.py` — encrypt/decrypt round-trip, wrong passphrase.

**Adapter snapshot tests (fast, no live portal):**
For each adapter: HTML fixtures under `tests/portals/<lender>/fixtures/`, loaded via `page.set_content(html)`. Tests assert `parse_result()` returns expected `PortalResult`. DOM changes break tests immediately without hitting the portal.

**Live smoke (manual / opt-in):**
`@pytest.mark.live` per adapter. Excluded from default run; required before merging adapter changes. `pytest -m live -k <lender>`.

**TDD discipline:** every implementation task follows failing test → red → minimal code → green → commit.

## Project Conventions

- **Python:** 3.11+, `uv` for deps, `ruff` (line 100, ruleset `E,F,I,B,UP`), `pyright` strict, `pytest` + `pytest-asyncio` + `pytest-playwright`.
- **Types:** All public functions typed; Pydantic models cross module boundaries. No untyped `dict[str, Any]`.
- **Money:** Decimal everywhere. Never float.
- **Async:** Default for I/O. No blocking calls in route handlers.
- **Adapters:** One per file, named `<lender>_adapter.py`. Selectors as class constants at top.
- **Logging:** `structlog` JSON to `data/logs/check-rate.log` (rotating). Every comparison gets a `correlation_id` carried on every log line. Playwright errors capture screenshot + page HTML before re-raise.
- **Secrets:** `data/credentials.enc`, never committed. `.env` for non-secret config.
- **Commits:** One per plan task. Short imperative subject. No `Co-Authored-By` trailer (per user preference for parser-style work).
- **Branching:** `main` is deployable. Feature work on `feat/<short-name>`. v1 ships as one PR.

## Local Dev

```bash
uv sync
playwright install chromium          # one-time
uv run pytest                        # unit + snapshot
uv run pytest -m live -k <lender>    # live smoke
uv run uvicorn app.main:app --reload # dev server, http://localhost:8080
```

## Open Questions (to resolve during implementation)

- The exact moso-pricing parsed ratesheet path on disk for AD Mortgage (validated during Task 1 of implementation).
- Whether AD Mortgage's public quick-pricer exposes itemized LLPAs or just a final price — if only final price, v1 LLPA comparison is degraded to a single-field check.
- Whether parsed ratesheet JSON for that lender already contains itemized LLPA labels matching the portal's labels (drives whether per-LLPA comparison is meaningful in v1 or just final-price).
- Whether `ComputeAdjustmentOp`'s return shape needs a Quote field we haven't enumerated (validate against the live MOSO instance during Task 1 of implementation).
- `ComputeAdjustmentOp` returns `{"adjustment": <decimal>}` described as "percent adjustment to rate". v1 needs to confirm whether this is a **rate-points** adjustment (e.g. +0.25% to the rate) or a **price-points** adjustment (e.g. +0.25 to the price). If the former, the tool computes `final_price` by looking up the parsed ratesheet at `target_rate + adjustment` instead of adding to base price. Task 1 of the implementation plan validates this against a live scenario.

## Future Work (not v1)

- Full rate-ladder comparison (every rate, not just one).
- Cross-lender batch run from a saved scenario.
- Comparison history dashboard.
- Slack notification when a portal-side mismatch exceeds a configurable threshold.
- Lender-side captcha solving / human-handoff for captchas.
- Hosted multi-user deployment (would require auth, multi-tenant secrets, and a real database).
