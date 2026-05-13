# MOSO Endpoint Recon (Task 4)

## Decision: use `GetRatesOp`, not `ComputeAdjustmentOp`

Original plan assumed `POST /execute/ComputeAdjustmentOp` (adjustment only) plus reading parsed ratesheet JSON from disk for base price. Live testing showed the actual operational endpoint is:

- **URL:** `POST {MOSO_BASE_URL}/exec/GetRatesOp`
- **Returns:** full rate ladder for the scenario, each rate with base price, total adjustment, adjusted price, **and itemized LLPA breakdown** — everything we need in one call.

This **eliminates Task 6** (ratesheet reader) entirely.

## Base URL

- Staging (v1 target): `https://www.viet18.com`
- Local development: optional; the tool defaults to staging via `MOSO_BASE_URL` in `.env`.

## Adjustment semantics — PRICE POINTS confirmed

UI showed:
- base price: -3.07%
- total adjustment: +1.125%
- final price: -1.945%

Math: `-3.07 + 1.125 = -1.945`. The adjustment is added directly to the base price → **price points**, not rate points. No rate-shift translation needed.

## Request payload

The full request is rich (state, county, zip, debt_to_income, AMI, etc.). For v1 we send a fixed payload built from a `Scenario`. Reference request (verified):

```json
{
  "get_all_rates": true,
  "loan_amount": 400000,
  "property_value": 500000,
  "credit_score": 759,
  "ltv_implicit": "computed",
  "property_type": 0,            // 0 = Single
  "impounds": true,
  "purpose": 0,                   // 0 = Refinance, 1 = Purchase (TBD verify)
  "occupancy": 0,                 // 0 = Owner
  "loan_type": 0,                 // 0 = Conventional
  "state": "VA",
  "zip": "20155",
  "county_name": "Prince William",
  "has_equity_loan": false,
  "super_conf_limit": 1249125,
  "alert_lender": 61,             // 61 = AD Mortgage (per the request URL)
  "alert_lenders": [61],
  "attachment_type": 1,
  "waive_lender_fee": false,
  "debt_to_income": 40,
  "total_number_properties": 3,
  "actual_number_of_units": 1,
  "borrower_paid_compensation": 1,
  "compensation_type": 1,
  "has_self_employed": false,
  "first_time_home_buyer": false,
  "income_to_ami": 0,
  "ami": 162000,
  "lock_period": 30,
  "total_loan_amount": 400000,
  "loan_program_group": 2,        // 2 = FIXED_30
  "channel": null,
  "kind": "Rate",
  "is_paid_for_va_sponsorship": false,
  "countyLimit": { ... }          // full county object, see live request
}
```

Several of these fields use **MOSO enum ordinals** rather than the string enum values our pydantic `Scenario` uses. The MOSO client must translate.

### Enum ordinal mapping (from the captured request — VERIFY each in Task 7 impl)

| Field | Ordinal | String |
|---|---|---|
| `purpose` | 0 | Refinance (so 1 = Purchase, 2 = Cashout — TBD verify) |
| `occupancy` | 0 | Owner (Primary) |
| `loan_type` | 0 | Conventional |
| `property_type` | 0 | Single (single-family) |
| `loan_program_group` | 2 | FIXED_30 |

`alert_lender = 61` = AD Mortgage. (Full lender ID table TBD — to be added as we onboard more lenders.)

`countyLimit` is a giant object; if MOSO requires it, the v1 client will hardcode a single canonical example (Prince William VA) and treat scenario "state/zip/county" as fixed in v1. Multi-state support deferred.

## Response shape

Top-level:
```json
{
  "_exact": true,
  "has_lower_rates": false,
  "_rows": [ <rate row>, <rate row>, ... ]
}
```

Each `<rate row>`:
```json
{
  "loan_program": "30-Yr Fixed",
  "program": "Fannie Mae",
  "loan_type": 0,
  "mode": "DU Investment",
  "interest_rate": 5.0,           // the rate (decimal percent)
  "base_price": 6.17975,           // price points
  "alias": "Kind Lending",         // lender display name — filter on this
  "p_and_i": 2308.33,
  "payment": 2308.33,
  "borrower_paid_compensation": 1.0,
  "lender_fee": 6.17975,
  "total_cost": 34779.4,
  "adjusted_cost": 26035.4,
  "commission_detail": {
    "_exact": true,
    "_rows": [
      {"adjustment_name": "Base Price",          "adjustment_value": 6.17975,  "adjustment_cost": null,  "is_group": false, "level": 0},
      {"adjustment_name": "FICO (760 - 779) and 30 < LTV <= 60",  "adjustment_value": -0.250, ...},
      {"adjustment_name": "Investment Property 2 and 30 < LTV <= 60", "adjustment_value": 0.125, ...},
      {"adjustment_name": "DU Rate/Term LLPAs Adjustment", "adjustment_value": ..., "is_group": true},
      {"adjustment_name": "Total Adj",           "adjustment_value": -0.125,   ...},
      {"adjustment_name": "Adjusted Price",      "adjustment_value": 6.05475,  ...},
      {"adjustment_name": "Lender Points",       "adjustment_value": 6.05475,  ...},
      {"adjustment_name": "Lender Credits",      "adjustment_value": ...,      ...},
      {"adjustment_name": "Total Closing Costs", "adjustment_value": ...,      ...},
      ...
    ]
  }
}
```

**Key facts for the parser:**

- `_rows` contains every rate in the ladder; v1 picks the one row where `interest_rate == scenario.target_rate` AND `alias == <expected lender alias>` (for AD Mortgage: TBD — likely `"AD Mortgage"`, `"ADMortgage"`, or `"ADM"`; verify on first live call).
- The response in this recon contained only `alias: "Kind Lending"` — that's the lender MOSO returned for this scenario. The `alert_lender` field in the request is a HINT for highlighting, not a strict filter. Multiple lenders may be present in `_rows`; we filter by alias.
- `commission_detail._rows` is the LLPA breakdown. The roll-up rows ("Base Price", "Total Adj", "Adjusted Price", "Lender Points", "Lender Credits", "Total Closing Costs") are not LLPAs — exclude them. The remaining rows ARE the itemized LLPAs.
- Some rows have `"is_group": true` — these are headers, not values. Skip them.

## Auth

MOSO's `AbstractOp.java:362` shows two auth paths to `GetRatesOp`:

1. **API key in `Authorization` header** — simplest. Bypasses XSRF + ATTR_USER; namespace derived from the API key's owner. Recommended for v1.
2. **Full session** — needs `XSRF`, `user` (ATTR_USER), `X-SDK-Namespace`, and a valid session cookie. Captured request used:
   - `XSRF: <uuid>`
   - `user: <email>`
   - `X-SDK-Namespace: 5716104026521600`
   - `x-property: version=...;guid=...;tz=...;locale=en;location=US;X-Use-Enum-Ordinal=1;theme=color`

There is also a dev-mode bypass: `Server.isDev() && apiKey=="dev"` triggers `loginAsOwner()`. Useful for local testing if MOSO is running in dev mode.

**v1 strategy — single headers file**

The tool reads `data/moso-headers.json` (gitignored) containing whatever headers MOSO needs. The user populates it with:

```json
{ "Authorization": "<api-key>" }
```

OR (if no API key):

```json
{
  "XSRF": "<uuid>",
  "user": "<email>",
  "X-SDK-Namespace": "5716104026521600",
  "x-property": "version=...;X-Use-Enum-Ordinal=1",
  "Cookie": "<cookie string>"
}
```

The MosoClient just forwards whatever is in the file — no branching on auth flavor in code. If MOSO returns 401/403, the tool raises `MosoAuthError` and the UI prompts the user to refresh the file.

## Parsers in `moso-pricing` (for context only)

AD Mortgage has two parser sets in `moso-pricing`:
- **Conventional:** `ADMortgageTables.java`, `ADMortgageParser.java`, `ADMortgagePdfParser.java`
- **Non-QM:** `ADMortgageNonQMTables.java`, `ADMortgageNonQMParser.java`, `ADMortgageNonQMPdfParser.java`

Test PDFs: `src/test/resources/ratesheets/adMortgage0612.pdf`, `adMortgage0911.pdf`.

These parsers feed MOSO's Datastore at runtime — **the tool does not read them**. Pricing comes via `GetRatesOp` only.

## Captured response stats (from recon run)

- 48 rate rows total
- Loan programs: `"30-Yr Fixed"` only
- Programs: `"Fannie Mae"`, `"Freddie Mac"`
- Modes: `"DU Investment"`, `"LP Investment"`
- **Aliases in response: `["Kind Lending"]` only — no AD Mortgage row present.**

The lack of AD Mortgage in this particular scenario means we still need to:
- (a) capture a response from a scenario where MOSO returns AD Mortgage, OR
- (b) confirm during live testing what `alias` string AD Mortgage uses when present.

The trimmed fixture for tests is saved at `tests/moso/fixtures/getratesop_sample.json` (3 rows, Kind Lending). The parser logic is alias-agnostic, so this is fine for unit tests. The lender-alias table in `app/main.py` (Task 17) must be tuned with the real AD Mortgage alias the first time we see one live.

## Canonical validation scenario

For tests + fixtures, freeze this scenario as the v1 golden case:

| Field | Value |
|---|---|
| loan_amount | 400000 |
| property_value | 500000 |
| credit_score | 759 |
| state | VA |
| zip | 20155 |
| county_name | Prince William |
| occupancy | Owner / Primary |
| property_type | Single |
| purpose | Refinance |
| loan_type | Conventional |
| loan_program_group | 30-Yr Fixed |
| target_rate | (pick one from the response) |

The user's recorded MOSO-side numbers (base -3.07, adjustment +1.125, final -1.945) appear to be for AD Mortgage specifically — but the recon response only contained Kind Lending rows. **Open: confirm the AD Mortgage `alias` string in the first live test run; if needed, capture a new response that includes AD Mortgage.**

## Open items deferred to implementation

- The exact `alias` string for AD Mortgage in `GetRatesOp` responses.
- Whether `countyLimit` can be omitted from the request (preferred) or must be sent in full.
- Mapping table for MOSO ordinals → our `Scenario` enums (start small; expand as needed).
- Whether MOSO's pricing for AD Mortgage in this VA refi scenario matches `-3.07 / +1.125 / -1.945` exactly when we call `GetRatesOp` from our tool.
