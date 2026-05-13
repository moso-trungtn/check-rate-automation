# check-rate v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI tool that quotes a loan scenario against MOSO and AD Mortgage's public pricer, then reports whether the final price + LLPA breakdown match for a single user-chosen rate.

**Architecture:** Single Python process. FastAPI + async Playwright + Jinja/HTMX. Pluggable `PortalAdapter` per lender; AD Mortgage is the only v1 adapter. MOSO is consumed read-only via HTTP (`/execute/ComputeAdjustmentOp`) plus on-disk parsed ratesheet JSON. SSE pushes progress and MFA prompts to the UI.

**Tech Stack:** Python 3.11+, uv, FastAPI, Pydantic v2, Playwright (async), Jinja2, HTMX, structlog, cryptography, pytest + pytest-asyncio + pytest-playwright.

**Spec:** `docs/superpowers/specs/2026-05-13-check-rate-design.md`

**Repo root:** `/Users/trungthach/IdeaProjects/check-rate`

All commands below assume CWD = repo root unless otherwise noted.

---

## Phase 1 — Project Foundation

### Task 1: Bootstrap uv project + tooling

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `README.md`
- Create: `app/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`

- [ ] **Step 1: Verify uv is installed**

Run: `uv --version`
Expected: `uv 0.x.x` (any 0.4+). If missing: `brew install uv`.

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "check-rate"
version = "0.1.0"
description = "MOSO vs lender-portal pricing comparison tool"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "httpx>=0.27",
    "playwright>=1.48",
    "jinja2>=3.1",
    "python-multipart>=0.0.12",
    "sse-starlette>=2.1",
    "structlog>=24.4",
    "cryptography>=43.0",
    "click>=8.1",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-playwright>=0.5",
    "ruff>=0.7",
    "pyright>=1.1.385",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.11"
include = ["app", "tests", "scripts"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "live: tests that hit live external systems (skipped by default)",
]
addopts = "-m 'not live'"
testpaths = ["tests"]
```

- [ ] **Step 3: Sync deps + install Playwright browser**

Run: `uv sync && uv run playwright install chromium`
Expected: ends with "Installing chromium ... done".

- [ ] **Step 4: Create `.env.example`**

```bash
# MOSO server base URL (no trailing slash)
MOSO_BASE_URL=http://localhost:8080

# Path to moso-pricing parsed ratesheets root on disk
MOSO_RATESHEETS_DIR=/Users/trungthach/IdeaProjects/moso-pricing/data/parsed

# Encryption passphrase for data/credentials.enc (omit to be prompted)
CHECK_RATE_PASSPHRASE=

# Comparison tolerance in price points
COMPARE_TOLERANCE=0.001
```

- [ ] **Step 5: Create `README.md`**

```markdown
# check-rate

Compare MOSO pricing against a lender's portal for a single scenario.

## Setup

    uv sync
    uv run playwright install chromium
    cp .env.example .env   # edit values

## Run

    uv run uvicorn app.main:app --reload
    # open http://localhost:8080

## Tests

    uv run pytest           # unit + snapshot
    uv run pytest -m live   # hit live portal (manual)

See `docs/superpowers/specs/2026-05-13-check-rate-design.md` for design.
```

- [ ] **Step 6: Create `app/__init__.py` and `tests/__init__.py` (empty files)**

- [ ] **Step 7: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
from __future__ import annotations
```

- [ ] **Step 8: Verify ruff + pyright clean**

Run: `uv run ruff check . && uv run pyright`
Expected: both report 0 errors.

- [ ] **Step 9: Verify pytest discovers no tests yet**

Run: `uv run pytest`
Expected: `no tests ran in ...s`.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml uv.lock .env.example README.md app/__init__.py tests/__init__.py tests/conftest.py
git commit -m "feat: bootstrap uv project + tooling"
```

---

## Phase 2 — Data Models

### Task 2: Pydantic models

**Files:**
- Create: `app/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models.py
from decimal import Decimal
from datetime import datetime
import pytest
from pydantic import ValidationError

from app.models import (
    Scenario, Occupancy, PropertyType, Purpose, LoanType,
    Adjustment, MosoResult, PortalResult, Mismatch, ComparisonReport,
)


def _scenario(**overrides):
    base = dict(
        loan_amount=Decimal("400000"),
        credit_score=740,
        property_value=Decimal("500000"),
        ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY,
        property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE,
        loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL,
        target_rate=Decimal("6.875"),
    )
    return Scenario(**(base | overrides))


def test_scenario_round_trip():
    s = _scenario()
    assert s.loan_amount == Decimal("400000")
    assert s.target_rate == Decimal("6.875")


def test_scenario_rejects_negative_loan_amount():
    with pytest.raises(ValidationError):
        _scenario(loan_amount=Decimal("-1"))


def test_scenario_rejects_fico_out_of_range():
    with pytest.raises(ValidationError):
        _scenario(credit_score=200)


def test_moso_result_final_price_relationship():
    r = MosoResult(
        base_price=Decimal("100.000"),
        adjustment_total=Decimal("-0.250"),
        final_price=Decimal("99.750"),
        adjustments=[Adjustment(label="FICO/LTV", amount=Decimal("-0.250"))],
    )
    assert r.source == "moso"


def test_portal_result_requires_snapshot_path():
    r = PortalResult(
        final_price=Decimal("99.500"),
        adjustments=[],
        raw_html_snapshot_path="/tmp/x.html",
        captured_at=datetime(2026, 5, 13, 12, 0, 0),
    )
    assert r.source == "portal"


def test_comparison_report_matches_flag():
    s = _scenario()
    moso = MosoResult(base_price=Decimal("100"), adjustment_total=Decimal("0"),
                      final_price=Decimal("100"), adjustments=[])
    portal = PortalResult(final_price=Decimal("100"), adjustments=[],
                          raw_html_snapshot_path="/tmp/x.html",
                          captured_at=datetime(2026, 5, 13))
    report = ComparisonReport(
        id="r1", scenario=s, lender="ad_mortgage",
        moso=moso, portal=portal, matches=True, mismatches=[],
        generated_at=datetime(2026, 5, 13),
    )
    assert report.matches is True


def test_mismatch_allows_none_sides():
    m = Mismatch(field="adjustment:foo", moso_value=Decimal("0.25"),
                 portal_value=None, delta=None)
    assert m.portal_value is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: ImportError on `app.models`.

- [ ] **Step 3: Implement `app/models.py`**

```python
"""Pydantic data models for check-rate."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


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
    loan_amount: Decimal = Field(gt=0)
    credit_score: int = Field(ge=300, le=850)
    property_value: Decimal = Field(gt=0)
    ltv: Decimal = Field(gt=0, le=Decimal("200"))
    occupancy: Occupancy
    property_type: PropertyType
    purpose: Purpose
    loan_program: str
    loan_type: LoanType
    target_rate: Decimal = Field(gt=0, le=Decimal("30"))


class Adjustment(BaseModel):
    label: str
    amount: Decimal


class MosoResult(BaseModel):
    base_price: Decimal
    adjustment_total: Decimal
    final_price: Decimal
    adjustments: list[Adjustment]
    source: Literal["moso"] = "moso"


class PortalResult(BaseModel):
    final_price: Decimal
    adjustments: list[Adjustment]
    raw_html_snapshot_path: str
    captured_at: datetime
    source: Literal["portal"] = "portal"


class Mismatch(BaseModel):
    field: str
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

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_models.py -v && uv run ruff check app tests && uv run pyright`
Expected: all tests PASS, ruff and pyright clean.

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: pydantic models for scenario and comparison results"
```

---

## Phase 3 — Comparison Engine

### Task 3: Pure comparison function

**Files:**
- Create: `app/compare/__init__.py` (empty)
- Create: `app/compare/engine.py`
- Test: `tests/compare/__init__.py` (empty)
- Test: `tests/compare/test_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/compare/test_engine.py
from datetime import datetime
from decimal import Decimal

from app.compare.engine import compare, normalize_label
from app.models import (
    Adjustment, MosoResult, PortalResult, Scenario, Occupancy,
    PropertyType, Purpose, LoanType,
)


def _scenario():
    return Scenario(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=Decimal("6.875"),
    )


def _moso(final="100.000", adjs=None):
    return MosoResult(
        base_price=Decimal("100"), adjustment_total=Decimal("0"),
        final_price=Decimal(final), adjustments=adjs or [],
    )


def _portal(final="100.000", adjs=None):
    return PortalResult(
        final_price=Decimal(final), adjustments=adjs or [],
        raw_html_snapshot_path="/tmp/x.html",
        captured_at=datetime(2026, 5, 13),
    )


def test_normalize_label():
    assert normalize_label("  FICO  /  LTV  ") == "fico / ltv"
    assert normalize_label("Sub Financing") == "sub financing"


def test_exact_match():
    report = compare(_scenario(), "ad_mortgage",
                     _moso("99.500", [Adjustment(label="FICO/LTV", amount=Decimal("-0.500"))]),
                     _portal("99.500", [Adjustment(label="FICO/LTV", amount=Decimal("-0.500"))]),
                     tolerance=Decimal("0.001"))
    assert report.matches is True
    assert report.mismatches == []


def test_final_price_mismatch():
    report = compare(_scenario(), "ad_mortgage",
                     _moso("100.000"), _portal("100.250"),
                     tolerance=Decimal("0.001"))
    assert report.matches is False
    assert len(report.mismatches) == 1
    m = report.mismatches[0]
    assert m.field == "final_price"
    assert m.delta == Decimal("0.250")


def test_within_tolerance_counts_as_match():
    report = compare(_scenario(), "ad_mortgage",
                     _moso("100.000"), _portal("100.0005"),
                     tolerance=Decimal("0.001"))
    assert report.matches is True


def test_llpa_missing_on_portal_side():
    moso_adj = [Adjustment(label="Subordinate Financing", amount=Decimal("0.250"))]
    report = compare(_scenario(), "ad_mortgage",
                     _moso("100", moso_adj), _portal("100"),
                     tolerance=Decimal("0.001"))
    fields = [m.field for m in report.mismatches]
    assert "adjustment:subordinate financing" in fields
    m = next(x for x in report.mismatches if x.field == "adjustment:subordinate financing")
    assert m.moso_value == Decimal("0.250")
    assert m.portal_value is None


def test_llpa_missing_on_moso_side():
    portal_adj = [Adjustment(label="Extra Fee", amount=Decimal("0.100"))]
    report = compare(_scenario(), "ad_mortgage",
                     _moso("100"), _portal("100", portal_adj),
                     tolerance=Decimal("0.001"))
    m = next(x for x in report.mismatches if x.field == "adjustment:extra fee")
    assert m.moso_value is None
    assert m.portal_value == Decimal("0.100")


def test_llpa_value_mismatch():
    moso_adj = [Adjustment(label="FICO/LTV", amount=Decimal("-0.500"))]
    portal_adj = [Adjustment(label="FICO/LTV", amount=Decimal("-0.625"))]
    report = compare(_scenario(), "ad_mortgage",
                     _moso("100", moso_adj), _portal("100", portal_adj),
                     tolerance=Decimal("0.001"))
    m = next(x for x in report.mismatches if x.field == "adjustment:fico/ltv")
    assert m.delta == Decimal("-0.125")


def test_report_has_id_and_timestamp():
    report = compare(_scenario(), "ad_mortgage",
                     _moso(), _portal(), tolerance=Decimal("0.001"))
    assert report.id
    assert report.lender == "ad_mortgage"
    assert report.generated_at is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/compare/test_engine.py -v`
Expected: ImportError on `app.compare.engine`.

- [ ] **Step 3: Implement engine**

```python
# app/compare/engine.py
"""Pure comparison engine: MosoResult + PortalResult -> ComparisonReport."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models import (
    Adjustment, ComparisonReport, Mismatch, MosoResult, PortalResult, Scenario,
)


def normalize_label(label: str) -> str:
    return " ".join(label.lower().split())


def _index(adjustments: list[Adjustment]) -> dict[str, Decimal]:
    return {normalize_label(a.label): a.amount for a in adjustments}


def compare(
    scenario: Scenario,
    lender: str,
    moso: MosoResult,
    portal: PortalResult,
    tolerance: Decimal,
) -> ComparisonReport:
    mismatches: list[Mismatch] = []

    delta_final = portal.final_price - moso.final_price
    if abs(delta_final) > tolerance:
        mismatches.append(Mismatch(
            field="final_price",
            moso_value=moso.final_price,
            portal_value=portal.final_price,
            delta=delta_final,
        ))

    moso_idx = _index(moso.adjustments)
    portal_idx = _index(portal.adjustments)
    for label in sorted(set(moso_idx) | set(portal_idx)):
        m_val = moso_idx.get(label)
        p_val = portal_idx.get(label)
        if m_val is None or p_val is None:
            mismatches.append(Mismatch(
                field=f"adjustment:{label}",
                moso_value=m_val, portal_value=p_val,
                delta=None,
            ))
        else:
            delta = p_val - m_val
            if abs(delta) > tolerance:
                mismatches.append(Mismatch(
                    field=f"adjustment:{label}",
                    moso_value=m_val, portal_value=p_val, delta=delta,
                ))

    return ComparisonReport(
        id=uuid.uuid4().hex[:12],
        scenario=scenario,
        lender=lender,
        moso=moso,
        portal=portal,
        matches=len(mismatches) == 0,
        mismatches=mismatches,
        generated_at=datetime.now(timezone.utc),
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/compare/test_engine.py -v && uv run ruff check app/compare tests/compare && uv run pyright`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/compare tests/compare
git commit -m "feat: pure comparison engine"
```

---

## Phase 4 — MOSO Integration

### Task 4: Validate MOSO endpoint semantics (manual recon)

**Files:**
- Create: `docs/moso-endpoint-recon.md`

This task resolves the "rate-points vs price-points" open question from the spec. No code change — produces a recon doc the next tasks rely on.

- [ ] **Step 1: Start MOSO locally (or get URL of a running instance)**

The user/engineer is responsible for ensuring a MOSO server is reachable. Set `MOSO_BASE_URL` in `.env`.

- [ ] **Step 2: Pick a real scenario from the moso UI and capture its price**

Open MOSO in a browser, quote a 30yr Fixed Conv scenario for AD Mortgage with:
- loan_amount = 400000, credit_score = 740, property_value = 500000, LTV = 80
- occupancy = primary, property = SFR, purpose = purchase

Record the displayed: base price at rate 6.875, total adjustment shown, final price.

- [ ] **Step 3: Curl the endpoint with same scenario**

```bash
curl -sS -X POST "$MOSO_BASE_URL/execute/ComputeAdjustmentOp" \
  -H "Content-Type: application/json" \
  -d '{
    "loan_amount": 400000,
    "credit_score": 740,
    "property_value": 500000,
    "ltv": 80,
    "occupancy": "primary_residence",
    "property_type": "single_family",
    "loan_program": "30yr Fixed Conv",
    "loan_type": "conventional",
    "purpose": "purchase",
    "quote_lender": "AD_MORTGAGE",
    "loan_alert_rate": {"interest_rate": 6.875}
  }'
```

Expected: JSON like `{"adjustment": 0.25, "error": null}` or similar.

- [ ] **Step 4: Compare the curl `adjustment` value to the MOSO UI**

Determine which interpretation is correct:
- (A) `adjustment` is in **rate points** (added to rate to look up new base price)
- (B) `adjustment` is in **price points** (subtracted from base price directly)

Method: if the UI shows "+0.250" next to LLPAs and `adjustment` = 0.25, it's likely price points (B). If the UI shows the rate moved from 6.875 to 7.125 and `adjustment` = 0.25, it's rate points (A).

- [ ] **Step 5: Locate the parsed ratesheet JSON for AD Mortgage**

```bash
find /Users/trungthach/IdeaProjects/moso-pricing -name "*ad*mortgage*" -o -name "*AD*Mortgage*" 2>/dev/null | head
find /Users/trungthach/IdeaProjects/moso-pricing/data -type d 2>/dev/null | head -20
```

Identify the directory containing parsed rate sheets for AD Mortgage and the file format (one JSON per snapshot? a daily file?).

- [ ] **Step 6: Write `docs/moso-endpoint-recon.md`**

```markdown
# MOSO Endpoint Recon (resolved Task 4)

## ComputeAdjustmentOp

- URL: `{MOSO_BASE_URL}/execute/ComputeAdjustmentOp`
- Method: POST, Content-Type: application/json
- Request shape: <paste exact JSON used in step 3>
- Response shape: <paste exact response received>
- Adjustment semantics: <PRICE_POINTS | RATE_POINTS> (verified against UI)

## AD Mortgage parsed ratesheet

- Root path: <e.g., /Users/trungthach/IdeaProjects/moso-pricing/data/parsed/ad_mortgage/>
- File pattern: <e.g., YYYY-MM-DD.json>
- Programs key: <e.g., "30yr Fixed Conv">
- Rate row shape: <e.g., {"rate": 6.875, "price": 100.125}>

## Validation scenario (canonical for tests)

- Scenario: <paste full scenario>
- MOSO UI base_price at 6.875: <value>
- MOSO UI final_price: <value>
- ComputeAdjustmentOp adjustment value: <value>
```

- [ ] **Step 7: Commit**

```bash
git add docs/moso-endpoint-recon.md
git commit -m "docs: resolve MOSO ComputeAdjustmentOp semantics for AD Mortgage"
```

---

### Task 5: Configuration module (REVISED after Task 4 recon)

The recon (`docs/moso-endpoint-recon.md`) replaced the ratesheet-on-disk assumption with the live `GetRatesOp` endpoint. Settings now reference a JSON headers file instead of a ratesheets directory.

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
from decimal import Decimal
from pathlib import Path

from app.config import Settings


def test_settings_reads_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MOSO_BASE_URL", "https://example.com")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "moso-headers.json"))
    monkeypatch.setenv("COMPARE_TOLERANCE", "0.01")
    s = Settings()
    assert s.moso_base_url == "https://example.com"
    assert s.moso_headers_file == tmp_path / "moso-headers.json"
    assert s.compare_tolerance == Decimal("0.01")


def test_settings_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "h.json"))
    monkeypatch.delenv("COMPARE_TOLERANCE", raising=False)
    s = Settings()
    assert s.compare_tolerance == Decimal("0.001")
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `app/config.py`**

```python
"""Application settings (env-driven)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    moso_base_url: str
    moso_headers_file: Path
    compare_tolerance: Decimal = Field(default=Decimal("0.001"))
    check_rate_passphrase: str | None = None
    data_dir: Path = Path("data")
```

- [ ] **Step 4: Update `.env.example`**

Replace the `MOSO_RATESHEETS_DIR` line with:

```bash
# Path to JSON file containing MOSO session headers (XSRF, user, Cookie, ...).
# Populate by copying from DevTools when your MOSO session is logged in.
# See docs/moso-endpoint-recon.md for the required keys.
MOSO_HEADERS_FILE=data/moso-headers.json
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/config.py tests/test_config.py .env.example
git commit -m "feat: env-driven settings (moso headers file)"
```

---

### Task 6: ~~MOSO ratesheet reader~~ — DELETED

The Task 4 recon proved we do not need to read parsed ratesheets from disk. `GetRatesOp` returns the full rate ladder with base prices and itemized LLPAs in one HTTP call. The ratesheet reader is **removed** from v1; skip this task entirely.

The original specification below is preserved for archival reference only — do NOT implement.

<details>
<summary>(Archived original Task 6, do not implement)</summary>

NOTE: Adjust this task's fixture shape to match what was discovered in Task 4. The shape below is a placeholder format — replace with the real shape before writing the test.

- [ ] **Step 1: Create fixture**

`tests/moso/fixtures/ad_mortgage_sample.json`:

```json
{
  "lender": "ad_mortgage",
  "programs": {
    "30yr Fixed Conv": {
      "rates": [
        {"rate": "6.625", "price": "99.500"},
        {"rate": "6.750", "price": "99.875"},
        {"rate": "6.875", "price": "100.125"},
        {"rate": "7.000", "price": "100.500"}
      ]
    }
  }
}
```

If Task 4 revealed a different real shape, replace this fixture and the reader implementation accordingly.

- [ ] **Step 2: Write failing tests**

```python
# tests/moso/test_ratesheet.py
from decimal import Decimal
from pathlib import Path

import pytest

from app.moso.ratesheet import RatesheetReader, RateNotFound, RatesheetMissing

FIX = Path(__file__).parent / "fixtures"


def test_read_base_price_hit():
    r = RatesheetReader(FIX)
    assert r.get_base_price("ad_mortgage", "30yr Fixed Conv", Decimal("6.875")) == Decimal("100.125")


def test_read_base_price_rate_not_found():
    r = RatesheetReader(FIX)
    with pytest.raises(RateNotFound):
        r.get_base_price("ad_mortgage", "30yr Fixed Conv", Decimal("5.000"))


def test_read_base_price_lender_missing(tmp_path):
    r = RatesheetReader(tmp_path)
    with pytest.raises(RatesheetMissing):
        r.get_base_price("nope", "30yr Fixed Conv", Decimal("6.875"))
```

- [ ] **Step 3: Run tests to verify fail**

Run: `uv run pytest tests/moso/test_ratesheet.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement reader**

```python
# app/moso/ratesheet.py
"""Reader for moso-pricing parsed ratesheet JSON output."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


class RatesheetMissing(FileNotFoundError):
    pass


class RateNotFound(KeyError):
    pass


class RatesheetReader:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _load(self, lender: str) -> dict[str, object]:
        path = self.root / f"{lender}_sample.json"
        if not path.exists():
            # Allow lender-named subdir + latest file as a fallback
            subdir = self.root / lender
            if subdir.is_dir():
                files = sorted(subdir.glob("*.json"))
                if files:
                    path = files[-1]
            if not path.exists():
                raise RatesheetMissing(f"No ratesheet for lender '{lender}' under {self.root}")
        return json.loads(path.read_text())

    def get_base_price(self, lender: str, program: str, rate: Decimal) -> Decimal:
        data = self._load(lender)
        programs = data.get("programs") or {}
        prog = programs.get(program)
        if not prog:
            raise RateNotFound(f"program '{program}' not in ratesheet for {lender}")
        for row in prog.get("rates", []):
            if Decimal(str(row["rate"])) == rate:
                return Decimal(str(row["price"]))
        raise RateNotFound(f"rate {rate} not in {lender}/{program}")
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/moso/test_ratesheet.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/moso tests/moso
git commit -m "feat: moso parsed-ratesheet reader"
```

</details>

---

### Task 7: MOSO HTTP client (`GetRatesOp`) — REVISED

**Files:**
- Create: `app/moso/__init__.py` (empty)
- Create: `app/moso/headers.py` — loads `MOSO_HEADERS_FILE` JSON
- Create: `app/moso/payload.py` — translates `Scenario` → `GetRatesOp` request body
- Create: `app/moso/parser.py` — parses `GetRatesOp` response → typed rate rows
- Create: `app/moso/client.py` — async HTTP wiring of the three above
- Test: `tests/moso/__init__.py` (empty)
- Test: `tests/moso/fixtures/getratesop_sample.json` — saved live response
- Test: `tests/moso/test_headers.py`
- Test: `tests/moso/test_payload.py`
- Test: `tests/moso/test_parser.py`
- Test: `tests/moso/test_client.py`

This task is intentionally larger than the original — we split it into 4 focused modules so each has one clear responsibility.

#### Step 1 — Save a live response fixture

You will need a real `GetRatesOp` response saved as `tests/moso/fixtures/getratesop_sample.json`. Use the one captured during Task 4 recon. Trim to ≤3 rate rows + their commission_detail to keep the fixture small.

Run: `mkdir -p tests/moso/fixtures && $EDITOR tests/moso/fixtures/getratesop_sample.json`

The trimmed fixture must keep the top-level shape (`_exact`, `has_lower_rates`, `_rows`) and each row's `interest_rate`, `base_price`, `alias`, `loan_program`, `program`, and `commission_detail._rows`.

#### Step 2 — `app/moso/headers.py` (failing test → impl → commit, one micro-cycle)

- [ ] Write `tests/moso/test_headers.py`:

```python
import json
from pathlib import Path
import pytest
from app.moso.headers import load_headers, HeadersMissing


def test_load_headers(tmp_path: Path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps({"XSRF": "abc", "user": "u@x", "Cookie": "k=v"}))
    h = load_headers(p)
    assert h["XSRF"] == "abc"
    assert h["user"] == "u@x"
    assert h["Cookie"] == "k=v"


def test_load_headers_missing(tmp_path: Path):
    with pytest.raises(HeadersMissing):
        load_headers(tmp_path / "nope.json")
```

- [ ] Run: `uv run pytest tests/moso/test_headers.py -v` — fails with ImportError.

- [ ] Implement `app/moso/headers.py`:

```python
"""Load MOSO session headers from a JSON file."""
from __future__ import annotations

import json
from pathlib import Path


class HeadersMissing(FileNotFoundError):
    pass


def load_headers(path: Path) -> dict[str, str]:
    if not path.exists():
        raise HeadersMissing(
            f"MOSO headers file not found at {path}. "
            "Populate it by copying DevTools request headers — see docs/moso-endpoint-recon.md."
        )
    data = json.loads(path.read_text())
    return {str(k): str(v) for k, v in data.items()}
```

- [ ] Run tests: PASS.

#### Step 3 — `app/moso/payload.py`

- [ ] Write `tests/moso/test_payload.py`:

```python
from decimal import Decimal
from app.models import (
    LoanType, Occupancy, PropertyType, Purpose, Scenario,
)
from app.moso.payload import scenario_to_request


def _scenario(**over):
    base = dict(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=Decimal("6.875"),
    )
    return Scenario(**(base | over))


def test_payload_uses_ordinals():
    p = scenario_to_request(_scenario(), lender_id=61)
    assert p["loan_amount"] == 400000
    assert p["credit_score"] == 740
    assert p["property_value"] == 500000
    assert p["loan_type"] == 0          # conventional
    assert p["alert_lender"] == 61
    assert p["alert_lenders"] == [61]
    assert p["loan_program_group"] == 2 # FIXED_30
    assert p["get_all_rates"] is True
    assert p["kind"] == "Rate"
    assert p["channel"] is None


def test_payload_purpose_mapping():
    assert scenario_to_request(_scenario(purpose=Purpose.PURCHASE), 61)["purpose"] == 1
    assert scenario_to_request(_scenario(purpose=Purpose.REFI), 61)["purpose"] == 0
    assert scenario_to_request(_scenario(purpose=Purpose.CASHOUT), 61)["purpose"] == 2


def test_payload_occupancy_mapping():
    assert scenario_to_request(_scenario(occupancy=Occupancy.PRIMARY), 61)["occupancy"] == 0
    assert scenario_to_request(_scenario(occupancy=Occupancy.SECOND), 61)["occupancy"] == 1
    assert scenario_to_request(_scenario(occupancy=Occupancy.INVESTMENT), 61)["occupancy"] == 2


def test_payload_property_type_mapping():
    assert scenario_to_request(_scenario(property_type=PropertyType.SFR), 61)["property_type"] == 0
    assert scenario_to_request(_scenario(property_type=PropertyType.CONDO), 61)["property_type"] == 1
    assert scenario_to_request(_scenario(property_type=PropertyType.PUD), 61)["property_type"] == 2
    assert scenario_to_request(_scenario(property_type=PropertyType.TWO_TO_FOUR), 61)["property_type"] == 3
```

NOTE: The ordinal mappings above are best-effort guesses for v1 based on what we saw in the captured request. **Verify each one against the live MOSO UI before trusting test results**; tune the mapping table in `payload.py` if any mismatch is discovered.

- [ ] Run: fails with ImportError.

- [ ] Implement `app/moso/payload.py`:

```python
"""Translate a Scenario into a GetRatesOp request body."""
from __future__ import annotations

from typing import Any

from app.models import LoanType, Occupancy, PropertyType, Purpose, Scenario

_PURPOSE_ORDINAL = {Purpose.REFI: 0, Purpose.PURCHASE: 1, Purpose.CASHOUT: 2}
_OCCUPANCY_ORDINAL = {Occupancy.PRIMARY: 0, Occupancy.SECOND: 1, Occupancy.INVESTMENT: 2}
_PROPERTY_ORDINAL = {
    PropertyType.SFR: 0, PropertyType.CONDO: 1,
    PropertyType.PUD: 2, PropertyType.TWO_TO_FOUR: 3,
}
_LOAN_TYPE_ORDINAL = {LoanType.CONVENTIONAL: 0}

# v1 only handles 30yr Fixed Conv. Group ordinal 2 was observed in the live request.
_LOAN_PROGRAM_GROUP_ORDINAL: dict[str, int] = {"30yr Fixed Conv": 2}


def scenario_to_request(s: Scenario, lender_id: int) -> dict[str, Any]:
    """Build a GetRatesOp body for the given scenario and lender id.

    Many fields (state, zip, county, AMI, etc.) are not part of our v1 Scenario.
    v1 ships a fixed example county block — multi-state support is deferred.
    """
    return {
        "get_all_rates": True,
        "loan_amount": int(s.loan_amount),
        "property_value": int(s.property_value),
        "credit_score": s.credit_score,
        "impounds": True,
        "purpose": _PURPOSE_ORDINAL[s.purpose],
        "occupancy": _OCCUPANCY_ORDINAL[s.occupancy],
        "loan_type": _LOAN_TYPE_ORDINAL[s.loan_type],
        "property_type": _PROPERTY_ORDINAL[s.property_type],
        "state": "VA",
        "zip": "20155",
        "county_name": "Prince William",
        "has_equity_loan": False,
        "super_conf_limit": 1249125,
        "alert_lender": lender_id,
        "alert_lenders": [lender_id],
        "attachment_type": 1,
        "waive_lender_fee": False,
        "debt_to_income": 40,
        "total_number_properties": 3,
        "actual_number_of_units": 1,
        "borrower_paid_compensation": 1,
        "compensation_type": 1,
        "has_self_employed": False,
        "first_time_home_buyer": False,
        "income_to_ami": 0,
        "ami": 162000,
        "lock_period": 30,
        "total_loan_amount": int(s.loan_amount),
        "loan_program_group": _LOAN_PROGRAM_GROUP_ORDINAL[s.loan_program],
        "channel": None,
        "kind": "Rate",
        "is_paid_for_va_sponsorship": False,
        "transaction_id": None,
        "manual_closing_cost_adjustment": None,
        "loan_additional_adjustment": None,
        "purchase_plus_geographic_eligibility": None,
        "purchase_plus_checked_address": None,
        # county object is hardcoded in v1; deferred to a future task
        "countyLimit": None,
    }
```

- [ ] Run: tests pass.

#### Step 4 — `app/moso/parser.py`

- [ ] Write `tests/moso/test_parser.py`:

```python
import json
from decimal import Decimal
from pathlib import Path
import pytest
from app.moso.parser import RateRow, parse_response, RowNotFound

FIX = Path(__file__).parent / "fixtures"


def _load():
    return json.loads((FIX / "getratesop_sample.json").read_text())


def test_parse_response_returns_rows():
    rows = parse_response(_load())
    assert len(rows) > 0
    assert all(isinstance(r, RateRow) for r in rows)
    assert all(r.base_price is not None for r in rows)


def test_find_row_by_lender_and_rate():
    rows = parse_response(_load())
    target = rows[0]
    found = next(
        r for r in rows
        if r.alias == target.alias and r.interest_rate == target.interest_rate
    )
    assert found.final_price == target.final_price


def test_commission_detail_excludes_rollups():
    rows = parse_response(_load())
    row = rows[0]
    names = {a.label.lower() for a in row.adjustments}
    # roll-up rows are excluded from the LLPA list
    for forbidden in ("base price", "total adj", "adjusted price",
                      "lender points", "lender credits", "total closing costs"):
        assert forbidden not in names


def test_filter_helpers():
    rows = parse_response(_load())
    aliases = {r.alias for r in rows}
    rates = {r.interest_rate for r in rows}
    assert len(aliases) >= 1
    assert len(rates) >= 1


def test_row_not_found_raises():
    rows = parse_response(_load())
    with pytest.raises(RowNotFound):
        from app.moso.parser import find_row
        find_row(rows, alias="Nonexistent Lender", rate=Decimal("99.000"))
```

- [ ] Run: fails with ImportError.

- [ ] Implement `app/moso/parser.py`:

```python
"""Parse a GetRatesOp response into typed rate rows."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models import Adjustment


_ROLLUP_NAMES = frozenset({
    "base price", "total adj", "adjusted price",
    "lender points", "lender credits", "total closing costs",
    "borrower's final credits", "total cost", "investment cost", "state cost",
    "broker compensation", "costs", "estimated closing costs", "total",
})


class RowNotFound(LookupError):
    pass


@dataclass(frozen=True)
class RateRow:
    alias: str
    loan_program: str
    program: str | None
    mode: str | None
    interest_rate: Decimal
    base_price: Decimal
    total_adjustment: Decimal
    final_price: Decimal
    adjustments: list[Adjustment]


def _parse_commission(detail: dict[str, Any]) -> tuple[Decimal, Decimal, list[Adjustment]]:
    base_price = Decimal("0")
    total_adj = Decimal("0")
    final_price = Decimal("0")
    items: list[Adjustment] = []
    for row in detail.get("_rows", []):
        if row.get("is_group"):
            continue
        name = str(row.get("adjustment_name", "")).strip()
        value = row.get("adjustment_value")
        if value is None:
            continue
        amount = Decimal(str(value))
        lname = name.lower()
        if lname == "base price":
            base_price = amount
        elif lname == "total adj":
            total_adj = amount
        elif lname == "adjusted price":
            final_price = amount
        elif lname in _ROLLUP_NAMES:
            continue
        else:
            items.append(Adjustment(label=name, amount=amount))
    return base_price, total_adj, final_price, items  # type: ignore[return-value]


def parse_response(payload: dict[str, Any]) -> list[RateRow]:
    rows: list[RateRow] = []
    for raw in payload.get("_rows", []):
        base, total, final, llpas = _parse_commission(raw.get("commission_detail") or {})
        rows.append(RateRow(
            alias=str(raw.get("alias", "")),
            loan_program=str(raw.get("loan_program", "")),
            program=raw.get("program"),
            mode=raw.get("mode"),
            interest_rate=Decimal(str(raw.get("interest_rate"))),
            base_price=base,
            total_adjustment=total,
            final_price=final,
            adjustments=llpas,
        ))
    return rows


def find_row(rows: list[RateRow], alias: str, rate: Decimal) -> RateRow:
    for r in rows:
        if r.alias == alias and r.interest_rate == rate:
            return r
    raise RowNotFound(f"No row for alias={alias!r} rate={rate}")
```

NOTE: `_parse_commission` returns a 4-tuple but the type hint says 3 — fix the annotation to `tuple[Decimal, Decimal, Decimal, list[Adjustment]]` (drop the `# type: ignore`).

- [ ] Run: tests pass.

#### Step 5 — `app/moso/client.py`

- [ ] Write `tests/moso/test_client.py`:

```python
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.models import (
    LoanType, Occupancy, PropertyType, Purpose, Scenario,
)
from app.moso.client import MosoClient, MosoApiError, MosoAuthError

FIX = Path(__file__).parent / "fixtures"


def _scenario():
    return Scenario(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=Decimal("6.875"),
    )


@pytest.mark.asyncio
async def test_get_rates_success():
    sample = json.loads((FIX / "getratesop_sample.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/exec/GetRatesOp"
        assert request.headers.get("XSRF") == "abc"
        return httpx.Response(200, json=sample)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = MosoClient(
            base_url="http://x", http=http,
            headers={"XSRF": "abc", "user": "u"},
        )
        rows = await client.get_rates(_scenario(), lender_id=61)
        assert len(rows) > 0


@pytest.mark.asyncio
async def test_get_rates_401_raises_auth_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(401))
    async with httpx.AsyncClient(transport=transport) as http:
        client = MosoClient(base_url="http://x", http=http, headers={})
        with pytest.raises(MosoAuthError):
            await client.get_rates(_scenario(), lender_id=61)


@pytest.mark.asyncio
async def test_get_rates_500_raises_api_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        client = MosoClient(base_url="http://x", http=http, headers={})
        with pytest.raises(MosoApiError):
            await client.get_rates(_scenario(), lender_id=61)
```

- [ ] Run: fails with ImportError.

- [ ] Implement `app/moso/client.py`:

```python
"""Async HTTP client for MOSO's GetRatesOp."""
from __future__ import annotations

import httpx

from app.models import Scenario
from app.moso.parser import RateRow, parse_response
from app.moso.payload import scenario_to_request


class MosoApiError(RuntimeError):
    pass


class MosoAuthError(MosoApiError):
    """Raised when MOSO returns 401/403 — session likely expired."""


class MosoClient:
    def __init__(
        self, base_url: str, http: httpx.AsyncClient,
        headers: dict[str, str],
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.headers = headers

    async def get_rates(self, scenario: Scenario, lender_id: int) -> list[RateRow]:
        url = f"{self.base_url}/exec/GetRatesOp"
        body = scenario_to_request(scenario, lender_id)
        try:
            resp = await self.http.post(
                url, json=body, headers=self.headers, timeout=30.0,
            )
        except httpx.HTTPError as e:
            raise MosoApiError(f"MOSO HTTP error: {e}") from e
        if resp.status_code in (401, 403):
            raise MosoAuthError(
                f"MOSO returned {resp.status_code}. Session likely expired — "
                f"refresh the headers file."
            )
        if resp.status_code >= 400:
            raise MosoApiError(f"MOSO HTTP {resp.status_code}: {resp.text[:200]}")
        return parse_response(resp.json())
```

- [ ] Run all moso tests: `uv run pytest tests/moso/ -v` — all pass.

- [ ] Commit:

```bash
git add app/moso tests/moso
git commit -m "feat: moso GetRatesOp client (headers, payload, parser)"
```

---

### Task 8: MOSO facade — REVISED

Now a thin layer that calls `MosoClient.get_rates`, filters for `(alias, rate)`, and produces a `MosoResult`. No ratesheet reader involved.

**Files:**
- Create: `app/moso/facade.py`
- Test: `tests/moso/test_facade.py`

- [ ] **Step 1: Write failing test**

```python
# tests/moso/test_facade.py
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.models import (
    LoanType, Occupancy, PropertyType, Purpose, Scenario, Adjustment,
)
from app.moso.facade import MosoFacade, LenderAliasNotFound
from app.moso.parser import RateRow


def _scenario(rate="6.875"):
    return Scenario(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=Decimal(rate),
    )


def _row(alias="AD Mortgage", rate="6.875", base="100.000", total="-0.250", final="99.750"):
    return RateRow(
        alias=alias, loan_program="30-Yr Fixed", program="Fannie Mae", mode="DU",
        interest_rate=Decimal(rate),
        base_price=Decimal(base),
        total_adjustment=Decimal(total),
        final_price=Decimal(final),
        adjustments=[Adjustment(label="FICO/LTV", amount=Decimal(total))],
    )


@pytest.mark.asyncio
async def test_facade_picks_matching_row():
    client = AsyncMock()
    client.get_rates.return_value = [
        _row(alias="Other", rate="6.875"),
        _row(alias="AD Mortgage", rate="6.875"),
        _row(alias="AD Mortgage", rate="7.000"),
    ]
    facade = MosoFacade(client=client, lender_id_table={"ad_mortgage": 61},
                        alias_table={"ad_mortgage": "AD Mortgage"})

    result = await facade.quote(_scenario(), lender="ad_mortgage")

    assert result.base_price == Decimal("100.000")
    assert result.adjustment_total == Decimal("-0.250")
    assert result.final_price == Decimal("99.750")
    assert result.adjustments[0].label == "FICO/LTV"


@pytest.mark.asyncio
async def test_facade_raises_if_alias_not_found():
    client = AsyncMock()
    client.get_rates.return_value = [_row(alias="Other Lender", rate="6.875")]
    facade = MosoFacade(client=client, lender_id_table={"ad_mortgage": 61},
                        alias_table={"ad_mortgage": "AD Mortgage"})

    with pytest.raises(LenderAliasNotFound):
        await facade.quote(_scenario(), lender="ad_mortgage")


@pytest.mark.asyncio
async def test_facade_unknown_lender_key_raises():
    client = AsyncMock()
    facade = MosoFacade(client=client, lender_id_table={}, alias_table={})
    with pytest.raises(KeyError):
        await facade.quote(_scenario(), lender="ad_mortgage")
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/moso/test_facade.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement facade**

```python
# app/moso/facade.py
"""Thin facade that turns a Scenario into a MosoResult via GetRatesOp."""
from __future__ import annotations

from app.models import MosoResult, Scenario
from app.moso.client import MosoClient


class LenderAliasNotFound(LookupError):
    """No row with the expected alias + rate was present in the GetRatesOp response."""


class MosoFacade:
    def __init__(
        self,
        client: MosoClient,
        lender_id_table: dict[str, int],
        alias_table: dict[str, str],
    ) -> None:
        self.client = client
        self.lender_id_table = lender_id_table
        self.alias_table = alias_table

    async def quote(self, scenario: Scenario, lender: str) -> MosoResult:
        lender_id = self.lender_id_table[lender]
        expected_alias = self.alias_table[lender]
        rows = await self.client.get_rates(scenario, lender_id)
        for r in rows:
            if r.alias == expected_alias and r.interest_rate == scenario.target_rate:
                return MosoResult(
                    base_price=r.base_price,
                    adjustment_total=r.total_adjustment,
                    final_price=r.final_price,
                    adjustments=list(r.adjustments),
                )
        aliases = sorted({r.alias for r in rows})
        raise LenderAliasNotFound(
            f"No row in GetRatesOp for alias={expected_alias!r} rate={scenario.target_rate}. "
            f"Got aliases: {aliases}"
        )
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/moso/test_facade.py -v && uv run pyright`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/moso/facade.py tests/moso/test_facade.py
git commit -m "feat: moso facade producing MosoResult from GetRatesOp"
```

### NOTE on lender tables

The `lender_id_table` and `alias_table` are dependency-injected so wiring lives in the FastAPI app (Task 17) where the real values are configured:

```python
LENDER_IDS = {"ad_mortgage": 61}
LENDER_ALIASES = {"ad_mortgage": "AD Mortgage"}  # TUNE on first live call
```

The exact alias for AD Mortgage in the live response will be confirmed during Task 16/17 manual smoke. If it's `ADMortgage` or `AD Mortgage, Inc` etc., update the `LENDER_ALIASES` constant.

---

## Phase 5 — Async Infrastructure

### Task 9: MFA bridge

**Files:**
- Create: `app/mfa/__init__.py` (empty)
- Create: `app/mfa/bridge.py`
- Test: `tests/mfa/__init__.py` (empty)
- Test: `tests/mfa/test_bridge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/mfa/test_bridge.py
import asyncio

import pytest

from app.mfa.bridge import MfaBridge, MfaTimeout, MfaAlreadySubmitted, MfaUnknownSession


@pytest.mark.asyncio
async def test_request_then_submit_resolves():
    bridge = MfaBridge()

    async def submit_later():
        await asyncio.sleep(0.05)
        bridge.submit_code("sess1", "123456")

    task = asyncio.create_task(submit_later())
    code = await bridge.request_code("sess1", "Test Lender", timeout=1.0)
    await task
    assert code == "123456"


@pytest.mark.asyncio
async def test_request_times_out():
    bridge = MfaBridge()
    with pytest.raises(MfaTimeout):
        await bridge.request_code("sess2", "Test Lender", timeout=0.1)


@pytest.mark.asyncio
async def test_double_submit_rejected():
    bridge = MfaBridge()

    async def consumer():
        return await bridge.request_code("sess3", "L", timeout=1.0)

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)
    bridge.submit_code("sess3", "111111")
    with pytest.raises(MfaAlreadySubmitted):
        bridge.submit_code("sess3", "222222")
    assert await task == "111111"


def test_submit_unknown_session_raises():
    bridge = MfaBridge()
    with pytest.raises(MfaUnknownSession):
        bridge.submit_code("nope", "x")
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/mfa/test_bridge.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement bridge**

```python
# app/mfa/bridge.py
"""In-memory future-based bridge for MFA code prompts."""
from __future__ import annotations

import asyncio


class MfaTimeout(TimeoutError):
    pass


class MfaAlreadySubmitted(RuntimeError):
    pass


class MfaUnknownSession(KeyError):
    pass


class MfaBridge:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}
        # callback hook the orchestrator wires up to emit SSE
        self._on_request: "list[ object ]" = []

    def on_request(self, callback) -> None:
        """Register a callback called as `callback(session_id, label)` when a code is needed."""
        self._on_request.append(callback)

    async def request_code(self, session_id: str, label: str, timeout: float) -> str:
        if session_id in self._pending:
            raise RuntimeError(f"MFA already in flight for {session_id}")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[session_id] = fut
        for cb in self._on_request:
            cb(session_id, label)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            raise MfaTimeout(f"MFA timeout for {session_id}") from e
        finally:
            self._pending.pop(session_id, None)

    def submit_code(self, session_id: str, code: str) -> None:
        fut = self._pending.get(session_id)
        if fut is None:
            raise MfaUnknownSession(f"No MFA in flight for {session_id}")
        if fut.done():
            raise MfaAlreadySubmitted(f"MFA already submitted for {session_id}")
        fut.set_result(code)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/mfa/test_bridge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/mfa tests/mfa
git commit -m "feat: in-memory mfa bridge"
```

---

### Task 10: SSE event bus

**Files:**
- Create: `app/events/__init__.py` (empty)
- Create: `app/events/bus.py`
- Test: `tests/events/__init__.py` (empty)
- Test: `tests/events/test_bus.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/events/test_bus.py
import asyncio

import pytest

from app.events.bus import EventBus, Event


@pytest.mark.asyncio
async def test_publish_received_by_subscriber():
    bus = EventBus()
    received: list[Event] = []

    async def consume():
        async for ev in bus.subscribe("sess1"):
            received.append(ev)
            if ev.type == "done":
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    bus.publish("sess1", Event(type="progress", data={"step": "moso", "status": "started"}))
    bus.publish("sess1", Event(type="done", data={"report_id": "r1"}))
    await asyncio.wait_for(task, timeout=1)
    assert [e.type for e in received] == ["progress", "done"]


@pytest.mark.asyncio
async def test_publish_isolated_per_session():
    bus = EventBus()
    received_a: list[Event] = []
    received_b: list[Event] = []

    async def consume(sess, sink):
        async for ev in bus.subscribe(sess):
            sink.append(ev)
            if ev.type == "done":
                break

    ta = asyncio.create_task(consume("a", received_a))
    tb = asyncio.create_task(consume("b", received_b))
    await asyncio.sleep(0.01)
    bus.publish("a", Event(type="progress", data={"step": "x"}))
    bus.publish("b", Event(type="error", data={"msg": "y"}))
    bus.publish("a", Event(type="done", data={}))
    bus.publish("b", Event(type="done", data={}))
    await asyncio.gather(ta, tb)
    assert [e.type for e in received_a] == ["progress", "done"]
    assert [e.type for e in received_b] == ["error", "done"]
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/events/test_bus.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement bus**

```python
# app/events/bus.py
"""Per-session async event bus used to fan out progress + MFA prompts to SSE."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any]


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Event]] = {}

    def _queue(self, session_id: str) -> asyncio.Queue[Event]:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]

    def publish(self, session_id: str, event: Event) -> None:
        self._queue(session_id).put_nowait(event)

    async def subscribe(self, session_id: str) -> AsyncIterator[Event]:
        q = self._queue(session_id)
        while True:
            ev = await q.get()
            yield ev
            if ev.type in ("done", "error"):
                # leave queue in place briefly in case of reconnect; orchestrator decides cleanup
                pass
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/events/test_bus.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/events tests/events
git commit -m "feat: per-session async event bus"
```

---

## Phase 6 — Secrets

### Task 11: Encrypted credentials store

**Files:**
- Create: `app/secrets/__init__.py` (empty)
- Create: `app/secrets/store.py`
- Test: `tests/secrets/__init__.py` (empty)
- Test: `tests/secrets/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/secrets/test_store.py
from pathlib import Path

import pytest

from app.secrets.store import (
    Credentials, CredentialsStore, BadPassphrase, MissingStore,
)


def test_encrypt_decrypt_round_trip(tmp_path: Path):
    path = tmp_path / "creds.enc"
    store = CredentialsStore(path=path, passphrase="hunter2")
    store.save({"ad_mortgage": Credentials(username="u", password="p")})
    again = CredentialsStore(path=path, passphrase="hunter2")
    creds = again.get("ad_mortgage")
    assert creds.username == "u" and creds.password == "p"


def test_wrong_passphrase_rejected(tmp_path: Path):
    path = tmp_path / "creds.enc"
    CredentialsStore(path=path, passphrase="right").save(
        {"ad_mortgage": Credentials(username="u", password="p")}
    )
    bad = CredentialsStore(path=path, passphrase="wrong")
    with pytest.raises(BadPassphrase):
        bad.get("ad_mortgage")


def test_missing_file_raises(tmp_path: Path):
    store = CredentialsStore(path=tmp_path / "missing.enc", passphrase="x")
    with pytest.raises(MissingStore):
        store.get("anything")
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/secrets/test_store.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement store**

```python
# app/secrets/store.py
"""Encrypted credentials store (Fernet + scrypt-derived key)."""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class BadPassphrase(RuntimeError):
    pass


class MissingStore(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    notes: str | None = None


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


_SALT_BYTES = 16


class CredentialsStore:
    def __init__(self, path: Path, passphrase: str) -> None:
        self.path = path
        self._passphrase = passphrase

    def save(self, creds: dict[str, Credentials]) -> None:
        salt = os.urandom(_SALT_BYTES)
        key = _derive_key(self._passphrase, salt)
        payload = json.dumps({
            k: {"username": v.username, "password": v.password, "notes": v.notes}
            for k, v in creds.items()
        }).encode("utf-8")
        token = Fernet(key).encrypt(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(salt + token)

    def _load(self) -> dict[str, Credentials]:
        if not self.path.exists():
            raise MissingStore(f"No credentials file at {self.path}")
        raw = self.path.read_bytes()
        salt, token = raw[:_SALT_BYTES], raw[_SALT_BYTES:]
        key = _derive_key(self._passphrase, salt)
        try:
            plain = Fernet(key).decrypt(token)
        except InvalidToken as e:
            raise BadPassphrase("Wrong passphrase or corrupted store") from e
        data = json.loads(plain)
        return {
            k: Credentials(username=v["username"], password=v["password"], notes=v.get("notes"))
            for k, v in data.items()
        }

    def get(self, lender: str) -> Credentials:
        return self._load()[lender]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/secrets/test_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/secrets tests/secrets
git commit -m "feat: encrypted credentials store"
```

---

### Task 12: Secrets management CLI

**Files:**
- Create: `scripts/__init__.py` (empty)
- Create: `scripts/manage_secrets.py`
- Test: `tests/scripts/__init__.py` (empty)
- Test: `tests/scripts/test_manage_secrets.py`

- [ ] **Step 1: Write failing test**

```python
# tests/scripts/test_manage_secrets.py
from click.testing import CliRunner

from app.secrets.store import CredentialsStore
from scripts.manage_secrets import cli


def test_add_and_list(tmp_path):
    runner = CliRunner()
    path = tmp_path / "creds.enc"
    r1 = runner.invoke(cli, [
        "--path", str(path), "--passphrase", "pw",
        "add", "ad_mortgage", "--username", "u", "--password", "p",
    ])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(cli, ["--path", str(path), "--passphrase", "pw", "list"])
    assert "ad_mortgage" in r2.output

    store = CredentialsStore(path=path, passphrase="pw")
    c = store.get("ad_mortgage")
    assert c.username == "u" and c.password == "p"


def test_remove(tmp_path):
    runner = CliRunner()
    path = tmp_path / "creds.enc"
    runner.invoke(cli, ["--path", str(path), "--passphrase", "pw",
                        "add", "x", "--username", "u", "--password", "p"])
    r = runner.invoke(cli, ["--path", str(path), "--passphrase", "pw", "remove", "x"])
    assert r.exit_code == 0
    r2 = runner.invoke(cli, ["--path", str(path), "--passphrase", "pw", "list"])
    assert "x" not in r2.output
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/scripts/test_manage_secrets.py -v`
Expected: ImportError on `scripts.manage_secrets`.

- [ ] **Step 3: Implement CLI**

```python
# scripts/manage_secrets.py
"""CLI to manage data/credentials.enc."""
from __future__ import annotations

from pathlib import Path

import click

from app.secrets.store import Credentials, CredentialsStore, MissingStore


@click.group()
@click.option("--path", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--passphrase", required=True, envvar="CHECK_RATE_PASSPHRASE")
@click.pass_context
def cli(ctx: click.Context, path: Path, passphrase: str) -> None:
    ctx.obj = CredentialsStore(path=path, passphrase=passphrase)


def _load_all(store: CredentialsStore) -> dict[str, Credentials]:
    try:
        return store._load()  # noqa: SLF001 — intentional local use
    except MissingStore:
        return {}


@cli.command()
@click.argument("lender")
@click.option("--username", required=True)
@click.option("--password", required=True)
@click.option("--notes", default=None)
@click.pass_obj
def add(store: CredentialsStore, lender: str, username: str, password: str, notes: str | None) -> None:
    all_creds = _load_all(store)
    all_creds[lender] = Credentials(username=username, password=password, notes=notes)
    store.save(all_creds)
    click.echo(f"saved {lender}")


@cli.command()
@click.argument("lender")
@click.pass_obj
def remove(store: CredentialsStore, lender: str) -> None:
    all_creds = _load_all(store)
    all_creds.pop(lender, None)
    store.save(all_creds)
    click.echo(f"removed {lender}")


@cli.command(name="list")
@click.pass_obj
def list_(store: CredentialsStore) -> None:
    for name in sorted(_load_all(store)):
        click.echo(name)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/scripts/test_manage_secrets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/manage_secrets.py scripts/__init__.py tests/scripts
git commit -m "feat: secrets management CLI"
```

---

## Phase 7 — Portal Adapter Framework

### Task 13: PortalAdapter ABC + registry

**Files:**
- Create: `app/portals/__init__.py`
- Create: `app/portals/base.py`
- Test: `tests/portals/__init__.py` (empty)
- Test: `tests/portals/test_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/portals/test_registry.py
from decimal import Decimal
from datetime import datetime

import pytest

from app.models import (
    LoanType, Occupancy, PortalResult, PropertyType, Purpose, Scenario,
)
from app.portals.base import PortalAdapter, register_adapter, get_adapter, AdapterNotFound


def test_register_and_lookup():
    @register_adapter("fake_lender")
    class FakeAdapter(PortalAdapter):
        LENDER = "fake_lender"
        LOGIN_URL = "https://example.com"

        async def ensure_logged_in(self, page, creds, mfa_bridge, session_id):
            pass

        async def fill_scenario(self, page, scenario):
            pass

        async def submit(self, page):
            pass

        async def parse_result(self, page, target_rate):
            return PortalResult(
                final_price=Decimal("100"), adjustments=[],
                raw_html_snapshot_path="/tmp/x.html",
                captured_at=datetime(2026, 5, 13),
            )

    adapter = get_adapter("fake_lender")
    assert isinstance(adapter, FakeAdapter)


def test_lookup_unknown_raises():
    with pytest.raises(AdapterNotFound):
        get_adapter("does_not_exist")
```

- [ ] **Step 2: Run tests to verify fail**

Run: `uv run pytest tests/portals/test_registry.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement base + registry**

```python
# app/portals/base.py
"""PortalAdapter ABC and registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import ClassVar

from app.mfa.bridge import MfaBridge
from app.models import PortalResult, Scenario
from app.secrets.store import Credentials


class AdapterNotFound(KeyError):
    pass


class PortalAdapter(ABC):
    LENDER: ClassVar[str]
    LOGIN_URL: ClassVar[str]

    @abstractmethod
    async def ensure_logged_in(
        self, page, creds: Credentials | None, mfa_bridge: MfaBridge, session_id: str,
    ) -> None: ...

    @abstractmethod
    async def fill_scenario(self, page, scenario: Scenario) -> None: ...

    @abstractmethod
    async def submit(self, page) -> None: ...

    @abstractmethod
    async def parse_result(self, page, target_rate: Decimal) -> PortalResult: ...


_REGISTRY: dict[str, type[PortalAdapter]] = {}


def register_adapter(lender: str):
    def deco(cls: type[PortalAdapter]) -> type[PortalAdapter]:
        _REGISTRY[lender] = cls
        return cls
    return deco


def get_adapter(lender: str) -> PortalAdapter:
    cls = _REGISTRY.get(lender)
    if cls is None:
        raise AdapterNotFound(f"No adapter registered for '{lender}'")
    return cls()
```

`app/portals/__init__.py`:

```python
"""Import side-effects auto-register adapters."""
from __future__ import annotations
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/portals/test_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/portals tests/portals
git commit -m "feat: portal adapter base + registry"
```

---

## Phase 8 — AD Mortgage Adapter

### Task 14: AD Mortgage portal recon

**Files:**
- Create: `docs/ad-mortgage-recon.md`

- [ ] **Step 1: Visit the portal in a real browser**

Open `https://admortgage.com/` and find the public quick pricer. (If it's not on the landing page, look for "pricing" / "rates" / "quick pricer" / "products" links.) Document the exact URL of the pricing page.

- [ ] **Step 2: Run Playwright codegen**

```bash
uv run playwright codegen https://admortgage.com/
```

A browser window opens; click through the quick-pricer flow with a test scenario (400k loan, 740 FICO, 80 LTV, primary SFR purchase, 30yr Fixed, target rate 6.875). The Inspector window emits Python code.

- [ ] **Step 3: Save the recorded code to `docs/ad-mortgage-recon.md`**

```markdown
# AD Mortgage Portal Recon

## URLs
- Landing: https://admortgage.com/
- Quick pricer: <paste>

## Recorded Playwright flow

```python
<paste codegen output here>
```

## Result page selectors
- Rate table: <CSS selector>
- Rate-row pattern: <CSS selector>
- Price cell: <CSS selector>
- LLPA list (if shown): <CSS selector, or "n/a — only final price shown">

## Notes
- Captcha? <yes/no>
- Login required? <should be no per spec; confirm>
- Loading indicator before rate table appears? <selector or "n/a">
```

- [ ] **Step 4: Save raw HTML of the result page**

While Playwright codegen is open with the result rendered, right-click → "View page source" → save to `tests/portals/ad_mortgage/fixtures/result_30yr_fixed.html`. Strip any session-specific tokens. (Create the directory first: `mkdir -p tests/portals/ad_mortgage/fixtures`.)

- [ ] **Step 5: Commit recon**

```bash
git add docs/ad-mortgage-recon.md tests/portals/ad_mortgage/fixtures/result_30yr_fixed.html
git commit -m "docs: ad mortgage portal recon + result snapshot"
```

---

### Task 15: AD Mortgage adapter (snapshot-driven)

**Files:**
- Create: `app/portals/ad_mortgage/__init__.py`
- Create: `app/portals/ad_mortgage/adapter.py`
- Test: `tests/portals/ad_mortgage/__init__.py` (empty)
- Test: `tests/portals/ad_mortgage/test_adapter.py`

The selectors in the code below are illustrative. **Replace each `data-rate=...` / `.price` / `.llpa-row` selector with the actual selectors discovered in Task 14 before running tests.**

- [ ] **Step 1: Write failing snapshot test**

```python
# tests/portals/ad_mortgage/test_adapter.py
from decimal import Decimal
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.portals.ad_mortgage.adapter import AdMortgageAdapter

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_parse_result_from_snapshot():
    html = (FIX / "result_30yr_fixed.html").read_text()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(html)
            adapter = AdMortgageAdapter()
            result = await adapter.parse_result(page, target_rate=Decimal("6.875"))
            assert result.final_price > 0
            assert result.source == "portal"
        finally:
            await browser.close()
```

NOTE: After Task 14 reveals the real result page, refine this test to assert exact expected `final_price` and the LLPA list (or document that the portal only shows final price).

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/portals/ad_mortgage/test_adapter.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement adapter (paste selectors from Task 14)**

```python
# app/portals/ad_mortgage/adapter.py
"""AD Mortgage public quick-pricer adapter."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from app.models import Adjustment, PortalResult, Scenario
from app.portals.base import PortalAdapter, register_adapter


@register_adapter("ad_mortgage")
class AdMortgageAdapter(PortalAdapter):
    LENDER: ClassVar[str] = "ad_mortgage"
    LOGIN_URL: ClassVar[str] = "https://admortgage.com/"

    # === Selectors (REPLACE with values from docs/ad-mortgage-recon.md) ===
    QUICK_PRICER_URL: ClassVar[str] = "https://admortgage.com/"  # update
    LOAN_AMOUNT_INPUT: ClassVar[str] = "input[name='loan_amount']"
    CREDIT_SCORE_INPUT: ClassVar[str] = "input[name='credit_score']"
    PROPERTY_VALUE_INPUT: ClassVar[str] = "input[name='property_value']"
    OCCUPANCY_SELECT: ClassVar[str] = "select[name='occupancy']"
    PROPERTY_TYPE_SELECT: ClassVar[str] = "select[name='property_type']"
    PURPOSE_SELECT: ClassVar[str] = "select[name='purpose']"
    PROGRAM_SELECT: ClassVar[str] = "select[name='program']"
    SUBMIT_BUTTON: ClassVar[str] = "button[type='submit']"
    RATE_TABLE: ClassVar[str] = "table.rate-table"
    RATE_ROW: ClassVar[str] = "tr[data-rate]"
    LLPA_ROW: ClassVar[str] = "tr.llpa-row"

    async def ensure_logged_in(self, page, creds, mfa_bridge, session_id) -> None:
        # AD Mortgage public pricer has no auth wall.
        return None

    async def fill_scenario(self, page, scenario: Scenario) -> None:
        await page.goto(self.QUICK_PRICER_URL)
        await page.fill(self.LOAN_AMOUNT_INPUT, str(int(scenario.loan_amount)))
        await page.fill(self.CREDIT_SCORE_INPUT, str(scenario.credit_score))
        await page.fill(self.PROPERTY_VALUE_INPUT, str(int(scenario.property_value)))
        await page.select_option(self.OCCUPANCY_SELECT, scenario.occupancy.value)
        await page.select_option(self.PROPERTY_TYPE_SELECT, scenario.property_type.value)
        await page.select_option(self.PURPOSE_SELECT, scenario.purpose.value)
        await page.select_option(self.PROGRAM_SELECT, scenario.loan_program)

    async def submit(self, page) -> None:
        await page.click(self.SUBMIT_BUTTON)
        await page.wait_for_selector(self.RATE_TABLE, timeout=20_000)

    async def parse_result(self, page, target_rate: Decimal) -> PortalResult:
        rows = page.locator(self.RATE_ROW)
        count = await rows.count()
        final_price: Decimal | None = None
        for i in range(count):
            row = rows.nth(i)
            row_rate_str = await row.get_attribute("data-rate") or ""
            try:
                row_rate = Decimal(row_rate_str)
            except (ValueError, ArithmeticError):
                continue
            if row_rate == target_rate:
                price_text = (await row.locator(".price").text_content()) or ""
                final_price = Decimal(price_text.strip().replace(",", ""))
                break
        if final_price is None:
            raise RuntimeError(f"Rate {target_rate} not present in AD Mortgage result")

        adjustments: list[Adjustment] = []
        llpa_rows = page.locator(self.LLPA_ROW)
        llpa_count = await llpa_rows.count()
        for i in range(llpa_count):
            label = ((await llpa_rows.nth(i).locator(".label").text_content()) or "").strip()
            amount_text = ((await llpa_rows.nth(i).locator(".amount").text_content()) or "").strip()
            if label and amount_text:
                adjustments.append(Adjustment(
                    label=label, amount=Decimal(amount_text.replace(",", "")),
                ))

        snapshot_path = Path(f"data/screenshots/{uuid4().hex[:8]}_ad_mortgage.html")
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(await page.content())

        return PortalResult(
            final_price=final_price,
            adjustments=adjustments,
            raw_html_snapshot_path=str(snapshot_path),
            captured_at=datetime.now(timezone.utc),
        )
```

`app/portals/ad_mortgage/__init__.py`:

```python
"""Importing this package registers the AD Mortgage adapter."""
from app.portals.ad_mortgage.adapter import AdMortgageAdapter  # noqa: F401
```

- [ ] **Step 4: Refine selectors against the saved fixture**

Open `tests/portals/ad_mortgage/fixtures/result_30yr_fixed.html` in a browser. Use DevTools to confirm `RATE_TABLE`, `RATE_ROW`, `.price`, and `LLPA_ROW` selectors match the real DOM. Edit `adapter.py` until the snapshot test passes.

- [ ] **Step 5: Run test to verify pass**

Run: `uv run pytest tests/portals/ad_mortgage/test_adapter.py -v`
Expected: PASS.

- [ ] **Step 6: Update spec open-question status**

Edit `docs/superpowers/specs/2026-05-13-check-rate-design.md`: in the "Open Questions" section, append one line under the AD Mortgage LLPA item with the answer (does the portal show itemized LLPAs?).

- [ ] **Step 7: Commit**

```bash
git add app/portals/ad_mortgage tests/portals/ad_mortgage docs/superpowers/specs
git commit -m "feat: ad mortgage adapter + snapshot test"
```

---

## Phase 9 — Orchestrator

### Task 16: run_comparison orchestrator

**Files:**
- Create: `app/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_orchestrator.py
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.events.bus import EventBus
from app.mfa.bridge import MfaBridge
from app.models import (
    Adjustment, LoanType, MosoResult, Occupancy, PortalResult,
    PropertyType, Purpose, Scenario,
)
from app.orchestrator import Orchestrator


def _scenario():
    return Scenario(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=Decimal("6.875"),
    )


@pytest.mark.asyncio
async def test_run_comparison_happy_path(tmp_path):
    moso_facade = AsyncMock()
    moso_facade.quote.return_value = MosoResult(
        base_price=Decimal("100"), adjustment_total=Decimal("-0.25"),
        final_price=Decimal("99.75"), adjustments=[Adjustment(label="X", amount=Decimal("-0.25"))],
    )

    portal_result = PortalResult(
        final_price=Decimal("99.75"), adjustments=[Adjustment(label="X", amount=Decimal("-0.25"))],
        raw_html_snapshot_path="/tmp/x.html", captured_at=datetime(2026, 5, 13),
    )
    adapter = AsyncMock()
    adapter.ensure_logged_in = AsyncMock()
    adapter.fill_scenario = AsyncMock()
    adapter.submit = AsyncMock()
    adapter.parse_result = AsyncMock(return_value=portal_result)

    browser = MagicMock()
    ctx = MagicMock()
    ctx.new_page = AsyncMock()
    ctx.storage_state = AsyncMock()
    ctx.close = AsyncMock()
    browser.new_context = AsyncMock(return_value=ctx)

    bus = EventBus()
    mfa = MfaBridge()
    secrets = MagicMock()
    secrets.get.side_effect = FileNotFoundError("no creds file")

    orch = Orchestrator(
        moso_facade=moso_facade,
        adapter_factory=lambda lender: adapter,
        browser=browser,
        bus=bus,
        mfa_bridge=mfa,
        secrets=secrets,
        tolerance=Decimal("0.001"),
        reports_dir=tmp_path,
        sessions_dir=tmp_path / "sessions",
    )

    report = await orch.run("sess1", _scenario(), lender="ad_mortgage")
    assert report.matches is True
    moso_facade.quote.assert_awaited_once()
    adapter.fill_scenario.assert_awaited_once()
    adapter.submit.assert_awaited_once()
    adapter.parse_result.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement orchestrator**

```python
# app/orchestrator.py
"""End-to-end comparison orchestrator."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.compare.engine import compare
from app.events.bus import Event, EventBus
from app.mfa.bridge import MfaBridge
from app.models import ComparisonReport, Scenario
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

    async def _run_moso(self, sid: str, scenario: Scenario, lender: str):
        self._emit(sid, "progress", {"step": "moso_pricing", "status": "started"})
        result = await self.moso_facade.quote(scenario, lender)
        self._emit(sid, "progress", {"step": "moso_pricing", "status": "ok"})
        return result

    async def _run_portal(self, sid: str, scenario: Scenario, lender: str):
        adapter = self.adapter_factory(lender)
        try:
            creds: Credentials | None = self.secrets.get(lender)
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
            except Exception:
                pass
            await ctx.close()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_orchestrator.py -v && uv run pyright`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: comparison orchestrator wiring moso + portal + compare"
```

---

## Phase 10 — Web Layer

### Task 17: FastAPI app + dependency wiring

**Files:**
- Create: `app/main.py`
- Create: `app/deps.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_main.py
from fastapi.testclient import TestClient

from app.main import create_app


def test_app_starts_and_returns_index(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "headers.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "test")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "check-rate" in r.text.lower()
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/test_main.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement minimal app + index template**

`app/main.py`:

```python
"""FastAPI application factory."""
from __future__ import annotations

import contextlib
from pathlib import Path

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

import app.portals.ad_mortgage  # noqa: F401  — register adapter
from app.config import Settings
from app.events.bus import EventBus
from app.mfa.bridge import MfaBridge
from app.moso.client import MosoClient
from app.moso.facade import MosoFacade
from app.moso.headers import load_headers
from app.orchestrator import Orchestrator
from app.portals.base import get_adapter
from app.secrets.store import CredentialsStore


LENDER_IDS: dict[str, int] = {"ad_mortgage": 61}
LENDER_ALIASES: dict[str, str] = {"ad_mortgage": "AD Mortgage"}  # tune live


def create_app() -> FastAPI:
    log = structlog.get_logger("check-rate")
    settings = Settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # In tests, the harness pre-populates app.state and sets this env var
        # so we skip launching a real browser.
        import os
        if os.environ.get("CHECK_RATE_TESTING") == "1":
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
    static_dir = Path(__file__).parent.parent / "static"
    template_dir = Path(__file__).parent.parent / "templates"
    if static_dir.exists():
        fastapi_app.mount("/static", StaticFiles(directory=static_dir), name="static")
    templates = Jinja2Templates(directory=str(template_dir))

    @fastapi_app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="index.html", context={})

    log.info("app_created")
    return fastapi_app


app = create_app()
```

`templates/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>check-rate</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/htmx.min.js" defer></script>
</head>
<body>
  <h1>check-rate</h1>
  <p>MOSO vs lender-portal pricing comparison.</p>
  <div id="form-host"></div>
  <div id="progress"></div>
  <div id="report"></div>
</body>
</html>
```

`static/style.css`:

```css
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; }
.mismatch { color: #b00; }
.match { color: #060; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 0.4rem 0.8rem; border-bottom: 1px solid #ddd; }
```

Download htmx (one-time):
```bash
mkdir -p static
curl -sSL https://unpkg.com/htmx.org@2.0.3 -o static/htmx.min.js
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/main.py templates/index.html static/style.css static/htmx.min.js tests/test_main.py
git commit -m "feat: fastapi app with index page and lifespan wiring"
```

---

### Task 18: `/compare` endpoint

**Files:**
- Create: `app/routes/__init__.py` (empty)
- Create: `app/routes/compare.py`
- Modify: `app/main.py` (mount router)
- Test: `tests/routes/__init__.py` (empty)
- Test: `tests/routes/test_compare.py`

- [ ] **Step 1: Write failing test**

```python
# tests/routes/test_compare.py
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import create_app


def test_post_compare_returns_session_id(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "headers.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    payload = {
        "lender": "ad_mortgage",
        "scenario": {
            "loan_amount": 400000, "credit_score": 740, "property_value": 500000,
            "ltv": 80, "occupancy": "primary_residence", "property_type": "single_family",
            "purpose": "purchase", "loan_program": "30yr Fixed Conv",
            "loan_type": "conventional", "target_rate": 6.875,
        },
    }
    with TestClient(app) as c:
        # State must be set AFTER lifespan enters (inside the with block).
        app.state.orchestrator = AsyncMock()
        r = c.post("/compare", json=payload)
        assert r.status_code == 202
        body = r.json()
        assert "session_id" in body
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/routes/test_compare.py -v`
Expected: 404 on `/compare`.

- [ ] **Step 3: Implement route + mount**

`app/routes/compare.py`:

```python
"""POST /compare and GET /report/{id}."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
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
async def get_report(report_id: str, request: Request) -> dict:
    settings = request.app.state.settings
    path: Path = settings.data_dir / "reports" / f"{report_id}.json"
    if not path.exists():
        raise HTTPException(404, "report not found")
    return json.loads(path.read_text())
```

Modify `app/main.py` to mount the router. Add after `fastapi_app = FastAPI(lifespan=lifespan)`:

```python
from app.routes.compare import router as compare_router
fastapi_app.include_router(compare_router)
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/routes/test_compare.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/__init__.py app/routes/compare.py app/main.py tests/routes
git commit -m "feat: POST /compare and GET /report/{id}"
```

---

### Task 19: SSE `/events/stream` endpoint

**Files:**
- Create: `app/routes/events.py`
- Modify: `app/main.py` (mount router)
- Test: `tests/routes/test_events.py`

- [ ] **Step 1: Write failing test**

```python
# tests/routes/test_events.py
import asyncio

from fastapi.testclient import TestClient

from app.events.bus import Event
from app.main import create_app


def test_sse_streams_events(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "headers.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    with TestClient(app) as c:
        from app.events.bus import EventBus
        app.state.bus = EventBus()

        async def publisher():
            await asyncio.sleep(0.05)
            app.state.bus.publish("sess1", Event(type="progress", data={"step": "moso"}))
            app.state.bus.publish("sess1", Event(type="done", data={"report_id": "r1"}))

        loop = asyncio.new_event_loop()
        loop.call_soon_threadsafe(lambda: asyncio.create_task(publisher()))

        with c.stream("GET", "/events/stream?session_id=sess1") as r:
            body = b""
            for chunk in r.iter_raw():
                body += chunk
                if b"done" in body:
                    break
            assert b"progress" in body
            assert b"done" in body
```

NOTE: SSE testing via TestClient is finicky. If this test is flaky on your machine, mark it `@pytest.mark.flaky` and rely on manual verification + the bus unit tests for confidence.

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/routes/test_events.py -v`
Expected: 404 on `/events/stream`.

- [ ] **Step 3: Implement SSE route**

`app/routes/events.py`:

```python
"""SSE event stream."""
from __future__ import annotations

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter()


@router.get("/events/stream")
async def stream(request: Request, session_id: str) -> EventSourceResponse:
    bus = request.app.state.bus

    async def generator():
        async for ev in bus.subscribe(session_id):
            yield {"event": ev.type, "data": __import__("json").dumps(ev.data)}
            if ev.type in ("done", "error"):
                break

    return EventSourceResponse(generator())
```

Modify `app/main.py`:

```python
from app.routes.events import router as events_router
fastapi_app.include_router(events_router)
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/routes/test_events.py -v`
Expected: PASS (or manually confirm via curl: `curl -N "http://localhost:8080/events/stream?session_id=test"` while another terminal triggers an event).

- [ ] **Step 5: Commit**

```bash
git add app/routes/events.py app/main.py tests/routes/test_events.py
git commit -m "feat: SSE /events/stream endpoint"
```

---

### Task 20: `/mfa/{session_id}/code` endpoint

**Files:**
- Create: `app/routes/mfa.py`
- Modify: `app/main.py`
- Test: `tests/routes/test_mfa.py`

- [ ] **Step 1: Write failing test**

```python
# tests/routes/test_mfa.py
import asyncio

from fastapi.testclient import TestClient

from app.main import create_app


def test_post_mfa_code_resolves_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("MOSO_BASE_URL", "http://x")
    monkeypatch.setenv("MOSO_HEADERS_FILE", str(tmp_path / "headers.json"))
    monkeypatch.setenv("CHECK_RATE_PASSPHRASE", "t")
    monkeypatch.setenv("CHECK_RATE_TESTING", "1")
    app = create_app()
    with TestClient(app) as c:
        from app.mfa.bridge import MfaBridge
        app.state.mfa = MfaBridge()
        async def submit_later():
            await asyncio.sleep(0.05)
            r = c.post("/mfa/sess1/code", json={"code": "987654"})
            assert r.status_code == 200

        loop = asyncio.new_event_loop()
        future = loop.run_until_complete(asyncio.gather(
            app.state.mfa.request_code("sess1", "Lender", timeout=1.0),
            submit_later(),
        ))
        assert future[0] == "987654"
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/routes/test_mfa.py -v`
Expected: 404 on `/mfa/...`.

- [ ] **Step 3: Implement route**

`app/routes/mfa.py`:

```python
"""POST /mfa/{session_id}/code — accepts MFA code from the UI."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.mfa.bridge import MfaAlreadySubmitted, MfaUnknownSession

router = APIRouter()


class CodePayload(BaseModel):
    code: str


@router.post("/mfa/{session_id}/code")
async def submit_code(session_id: str, payload: CodePayload, request: Request) -> dict[str, str]:
    bridge = request.app.state.mfa
    try:
        bridge.submit_code(session_id, payload.code)
    except MfaUnknownSession as e:
        raise HTTPException(404, str(e)) from e
    except MfaAlreadySubmitted as e:
        raise HTTPException(409, str(e)) from e
    return {"status": "accepted"}
```

Modify `app/main.py`:

```python
from app.routes.mfa import router as mfa_router
fastapi_app.include_router(mfa_router)
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/routes/test_mfa.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/mfa.py app/main.py tests/routes/test_mfa.py
git commit -m "feat: POST /mfa/{session_id}/code"
```

---

## Phase 11 — UI

### Task 21: Scenario form + HTMX submit

**Files:**
- Modify: `templates/index.html`
- Create: `templates/partials/form.html`
- Create: `templates/partials/report.html`

- [ ] **Step 1: Replace `templates/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>check-rate</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/htmx.min.js"></script>
  <script src="/static/htmx-sse.js"></script>
</head>
<body>
  <h1>check-rate</h1>

  <form id="scenario-form">
    <label>Lender:
      <select name="lender">
        <option value="ad_mortgage">AD Mortgage</option>
      </select>
    </label>
    <label>Loan amount: <input type="number" name="loan_amount" value="400000" required></label>
    <label>Credit score: <input type="number" name="credit_score" value="740" required></label>
    <label>Property value: <input type="number" name="property_value" value="500000" required></label>
    <label>LTV: <input type="number" step="0.01" name="ltv" value="80" required></label>
    <label>Occupancy:
      <select name="occupancy">
        <option value="primary_residence">Primary</option>
        <option value="second_home">Second home</option>
        <option value="investment">Investment</option>
      </select>
    </label>
    <label>Property type:
      <select name="property_type">
        <option value="single_family">SFR</option>
        <option value="condo">Condo</option>
        <option value="pud">PUD</option>
        <option value="2_to_4_unit">2-4 unit</option>
      </select>
    </label>
    <label>Purpose:
      <select name="purpose">
        <option value="purchase">Purchase</option>
        <option value="refinance">Refi</option>
        <option value="cashout">Cash-out</option>
      </select>
    </label>
    <label>Program: <input type="text" name="loan_program" value="30yr Fixed Conv"></label>
    <input type="hidden" name="loan_type" value="conventional">
    <label>Target rate: <input type="number" step="0.001" name="target_rate" value="6.875" required></label>
    <button id="compare-btn" type="button" onclick="startCompare()">Compare</button>
  </form>

  <div id="progress"></div>
  <div id="mfa-modal" hidden>
    <p>MFA required for <span id="mfa-lender"></span></p>
    <input id="mfa-code" type="text" autocomplete="one-time-code">
    <button onclick="submitMfa()">Submit code</button>
  </div>
  <div id="report"></div>

<script>
let currentSession = null;

async function startCompare() {
  const form = document.getElementById("scenario-form");
  const data = Object.fromEntries(new FormData(form));
  const payload = {
    lender: data.lender,
    scenario: {
      loan_amount: Number(data.loan_amount),
      credit_score: Number(data.credit_score),
      property_value: Number(data.property_value),
      ltv: Number(data.ltv),
      occupancy: data.occupancy,
      property_type: data.property_type,
      purpose: data.purpose,
      loan_program: data.loan_program,
      loan_type: data.loan_type,
      target_rate: Number(data.target_rate),
    },
  };
  document.getElementById("progress").innerHTML = "Starting…";
  const r = await fetch("/compare", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    document.getElementById("progress").innerText = "Request failed: " + r.status;
    return;
  }
  currentSession = (await r.json()).session_id;
  const es = new EventSource("/events/stream?session_id=" + currentSession);
  es.addEventListener("progress", ev => {
    const d = JSON.parse(ev.data);
    document.getElementById("progress").innerHTML += "<br>" + d.step + ": " + d.status;
  });
  es.addEventListener("mfa_required", ev => {
    const d = JSON.parse(ev.data);
    document.getElementById("mfa-lender").innerText = d.lender;
    document.getElementById("mfa-modal").hidden = false;
  });
  es.addEventListener("error", ev => {
    document.getElementById("progress").innerHTML += "<br><span class=mismatch>error: " + ev.data + "</span>";
    es.close();
  });
  es.addEventListener("done", async ev => {
    const d = JSON.parse(ev.data);
    const r = await fetch("/report/" + d.report_id);
    const report = await r.json();
    renderReport(report);
    es.close();
  });
}

async function submitMfa() {
  const code = document.getElementById("mfa-code").value;
  await fetch("/mfa/" + currentSession + "/code", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({code}),
  });
  document.getElementById("mfa-modal").hidden = true;
}

function renderReport(report) {
  const rows = [];
  rows.push(`<tr><td>final_price</td><td>${report.moso.final_price}</td><td>${report.portal.final_price}</td><td>${report.matches ? "<span class=match>match</span>" : "<span class=mismatch>mismatch</span>"}</td></tr>`);
  const allLabels = new Set([
    ...report.moso.adjustments.map(a => a.label.toLowerCase().trim()),
    ...report.portal.adjustments.map(a => a.label.toLowerCase().trim()),
  ]);
  const mosoMap = Object.fromEntries(report.moso.adjustments.map(a => [a.label.toLowerCase().trim(), a.amount]));
  const portalMap = Object.fromEntries(report.portal.adjustments.map(a => [a.label.toLowerCase().trim(), a.amount]));
  const mismatchLabels = new Set(report.mismatches.map(m => m.field.replace(/^adjustment:/, "")));
  for (const label of allLabels) {
    const cls = mismatchLabels.has(label) ? "mismatch" : "match";
    rows.push(`<tr><td>${label}</td><td>${mosoMap[label] ?? "—"}</td><td>${portalMap[label] ?? "—"}</td><td class="${cls}">${mismatchLabels.has(label) ? "mismatch" : "match"}</td></tr>`);
  }
  document.getElementById("report").innerHTML =
    `<h2>Result: ${report.matches ? "<span class=match>MATCH</span>" : "<span class=mismatch>MISMATCH</span>"}</h2>
     <table><thead><tr><th>field</th><th>MOSO</th><th>Portal</th><th>status</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}
</script>
</body>
</html>
```

- [ ] **Step 2: Verify dev server boots and the form renders**

Run (in one terminal):
```bash
uv run uvicorn app.main:app --reload
```
Then in a browser open `http://localhost:8080`. Confirm the form renders. (No need to actually submit; that's covered in Task 23.)

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat: scenario form + htmx/sse client wiring"
```

---

## Phase 12 — End-to-End

### Task 22: Capture-snapshot helper

**Files:**
- Create: `scripts/capture_portal_snapshot.py`

- [ ] **Step 1: Implement**

```python
# scripts/capture_portal_snapshot.py
"""One-shot helper to record a portal's result HTML for snapshot tests.

Usage:
    uv run python scripts/capture_portal_snapshot.py ad_mortgage \
        --target-rate 6.875 --out tests/portals/ad_mortgage/fixtures/result.html
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import click
from playwright.async_api import async_playwright

from app.models import (
    LoanType, Occupancy, PropertyType, Purpose, Scenario,
)
import app.portals.ad_mortgage  # noqa: F401  — register
from app.portals.base import get_adapter


def _demo_scenario(target_rate: Decimal) -> Scenario:
    return Scenario(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=target_rate,
    )


async def _capture(lender: str, target_rate: Decimal, out: Path) -> None:
    adapter = get_adapter(lender)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await adapter.fill_scenario(page, _demo_scenario(target_rate))
        await adapter.submit(page)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(await page.content())
        await browser.close()
        click.echo(f"saved {out}")


@click.command()
@click.argument("lender")
@click.option("--target-rate", type=Decimal, default=Decimal("6.875"))
@click.option("--out", type=click.Path(path_type=Path), required=True)
def main(lender: str, target_rate: Decimal, out: Path) -> None:
    asyncio.run(_capture(lender, target_rate, out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it once for AD Mortgage**

```bash
uv run python scripts/capture_portal_snapshot.py ad_mortgage \
    --target-rate 6.875 \
    --out tests/portals/ad_mortgage/fixtures/result_30yr_fixed.html
```
Expected: file written.

- [ ] **Step 3: Re-run snapshot test against the freshly captured fixture**

Run: `uv run pytest tests/portals/ad_mortgage/test_adapter.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/capture_portal_snapshot.py tests/portals/ad_mortgage/fixtures/result_30yr_fixed.html
git commit -m "feat: portal snapshot capture helper"
```

---

### Task 23: Live smoke test for AD Mortgage

**Files:**
- Create: `tests/portals/ad_mortgage/test_live.py`

- [ ] **Step 1: Implement live test**

```python
# tests/portals/ad_mortgage/test_live.py
from decimal import Decimal

import pytest
from playwright.async_api import async_playwright

from app.models import (
    LoanType, Occupancy, PropertyType, Purpose, Scenario,
)
import app.portals.ad_mortgage  # noqa: F401
from app.portals.base import get_adapter


@pytest.mark.live
@pytest.mark.asyncio
async def test_ad_mortgage_live_end_to_end():
    scenario = Scenario(
        loan_amount=Decimal("400000"), credit_score=740,
        property_value=Decimal("500000"), ltv=Decimal("80"),
        occupancy=Occupancy.PRIMARY, property_type=PropertyType.SFR,
        purpose=Purpose.PURCHASE, loan_program="30yr Fixed Conv",
        loan_type=LoanType.CONVENTIONAL, target_rate=Decimal("6.875"),
    )
    adapter = get_adapter("ad_mortgage")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await (await browser.new_context()).new_page()
        await adapter.fill_scenario(page, scenario)
        await adapter.submit(page)
        result = await adapter.parse_result(page, scenario.target_rate)
        await browser.close()
    assert result.final_price > 0
```

- [ ] **Step 2: Run live**

Run: `uv run pytest tests/portals/ad_mortgage/test_live.py -m live -v`
Expected: PASS (a real browser opens, navigates to the AD Mortgage public pricer, fills scenario, returns a price).

- [ ] **Step 3: Commit**

```bash
git add tests/portals/ad_mortgage/test_live.py
git commit -m "test: ad mortgage live smoke (-m live)"
```

---

### Task 24: Full-stack manual smoke + README finalization

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Start everything**

```bash
uv run uvicorn app.main:app --reload
```

- [ ] **Step 2: Drive the full flow in a browser**

1. Open `http://localhost:8080`.
2. Fill the form with the canonical scenario from Task 4's recon doc.
3. Click **Compare**.
4. Watch the **progress** panel populate with `moso_pricing`, `portal_login`, `portal_quote`, `portal_parse` events.
5. Confirm the report table renders. If MOSO and AD Mortgage agree, banner is green; otherwise the mismatched rows are red.

If anything fails: check `data/logs/check-rate.log` and `data/screenshots/` for the failing run.

- [ ] **Step 3: Finalize `README.md`**

Replace the contents of `README.md` with:

```markdown
# check-rate

Compare MOSO pricing against a lender's portal for a single scenario.

## v1 status

- Lender supported: **AD Mortgage** (`https://admortgage.com/`, public pricer, no login).
- Program: 30yr Fixed Conventional.
- Compare mode: one user-chosen rate; final price + LLPA breakdown.

## Setup

    uv sync
    uv run playwright install chromium
    cp .env.example .env   # edit values; CHECK_RATE_PASSPHRASE is required

## Add credentials (when adding a login-required lender)

    uv run python scripts/manage_secrets.py \
      --path data/credentials.enc --passphrase "$CHECK_RATE_PASSPHRASE" \
      add <lender-slug> --username <u> --password <p>

## Run

    uv run uvicorn app.main:app --reload
    # open http://localhost:8080

## Tests

    uv run pytest                 # unit + snapshot
    uv run pytest -m live         # hit real portals (manual)

## Adding a new lender

1. `uv run playwright codegen <portal-url>` — record the flow.
2. Create `app/portals/<lender>/adapter.py` modeled on `ad_mortgage/adapter.py`.
3. Capture a result snapshot: `uv run python scripts/capture_portal_snapshot.py <lender> --out tests/portals/<lender>/fixtures/result.html`.
4. Write `tests/portals/<lender>/test_adapter.py` with expected values.
5. `uv run pytest -m live -k <lender>` before merging.

## Design + plan

- Spec: `docs/superpowers/specs/2026-05-13-check-rate-design.md`
- Plan: `docs/superpowers/plans/2026-05-13-check-rate-v1.md`
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: finalize README after v1 manual smoke"
```

---

## Done criteria for v1

- [ ] `uv run pytest` is green (all unit + snapshot tests).
- [ ] `uv run pytest -m live -k ad_mortgage` succeeds end-to-end against the live AD Mortgage public pricer.
- [ ] Manual UI smoke: fill the form, click Compare, see a populated diff table.
- [ ] Spec's Open Questions section has all three items resolved with answers.
- [ ] `git log --oneline | wc -l` is approximately 24 (one commit per task).

## What v1 explicitly does not do

(Recap from spec, kept here so reviewers don't think it's missing.)

- Multi-user / hosted deployment.
- Comparing more than one rate per run.
- Programs other than 30yr Fixed Conv.
- Lender-side captcha solving.
- Historical trend dashboards.
- Slack / external notifications.
