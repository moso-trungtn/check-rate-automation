# check-rate — contributor rules

Conventions for everyone working in this repo, including AI assistants.

## Commit message format

```
[type] short subject in imperative mood (max ~72 chars)

Optional body. Wrap at ~72 chars. Explain WHY, not WHAT — the diff already
shows what changed. Include the why if it's non-obvious: a bug being fixed,
a constraint that forced a choice, a tradeoff that was considered.

Multiple paragraphs are fine. Bullet lists for grouped changes are fine.
```

**The subject line is the only required part.**

### Allowed types

Use exactly one of these, lowercase, inside square brackets at the start:

| Type | When to use |
|---|---|
| `[feat]` | A new user-visible feature or capability |
| `[fix]` | A bug fix |
| `[refactor]` | Code restructure with **no behavior change** (rename, split, simplify) |
| `[perf]` | Performance improvement |
| `[test]` | Adding or modifying tests only |
| `[docs]` | Documentation only (README, comments, this file, recon notes) |
| `[style]` | Formatting/whitespace/import-order only — no logic change |
| `[chore]` | Build, deps, tooling, gitignore, CI config |
| `[revert]` | Reverting a previous commit (reference the SHA being reverted) |

If a commit honestly does two things, **split it** into two commits.
If you can't split it, pick the type that describes the user-visible
impact (usually `feat` or `fix`).

### Subject rules

- **Imperative mood**: `add login button`, not `added` or `adds`.
- **Lowercase first word** after the `[type]`.
- **No trailing period.**
- **≤ 72 characters** including the `[type]` prefix.
- **No emojis** in commit messages.

### Body rules

- Empty line between subject and body.
- Wrap at ~72 chars.
- Focus on *why* this change exists. The diff shows *what*.
- Bulleted lists are fine for grouped changes.
- Reference an issue / report / past commit by SHA if relevant.

### Never include

- `Co-Authored-By: ...` trailers — **never**. No Claude, no AI branding.
- `🤖 Generated with ...` footers — **never**.
- File names in the subject (`fix x.py: ...`) — the diff already shows files.
- Vague messages: `update`, `wip`, `fixes`, `misc`.

### Good examples

```
[feat] add cURL → MOSO headers parser route

Lets non-tech users refresh the staging session by pasting a fresh
GetRatesOp cURL from DevTools. The server extracts XSRF/user/Cookie/
etc. via an allowlist and hot-swaps them onto the in-memory MosoClient
so the next /compare uses them without a uvicorn restart.
```

```
[fix] drive AD Mortgage form from scenario instead of hardcoded values

The adapter was hardcoding occupancy/property type/units/purpose/ZIP
and only sending FICO/loan amount/LTV from the scenario. When the user
changed Purpose to Cash-out, MOSO computed cash-out but the portal
stayed on Purchase — the resulting "mismatch" was meaningless.

Use mapping dicts (Scenario enum → portal label) and open dropdowns by
their stable container test_id, then click the option by visible text.
```

```
[refactor] split parser into commission_detail + adjustment_detail readers
```

```
[test] cover purpose ordinal mapping (Refi=0, CashOut=1, Purchase=2)
```

```
[docs] note that adjustment_detail is MOSO's pricing-only LLPA path
```

### Bad examples

| ❌ Don't | ✓ Do |
|---|---|
| `Fix bug` | `[fix] reject zero-length cURL in /moso/session/from-curl` |
| `WIP: refactor adapter` | (don't commit WIP; squash before pushing) |
| `Added FICO slider 🎨` | `[feat] replace FICO number input with range slider` |
| `[feat] Added new feature` | `[feat] add report-id validation to GET /report` |
| `[feat] update adapter and parser` | Two commits: `[feat]` for parser, `[fix]` for adapter |
| commit with `Co-Authored-By: Claude` trailer | (drop the trailer) |

---

## Other house rules

### Code

- Python 3.11+, strict `pyright`, `ruff` clean.
- `Decimal` for any money or pricing math — never `float`.
- Async by default for anything that does I/O.
- Adapters: one per file, named `<lender>_adapter.py`. Selectors as
  module-level constants near the top.

### Files / paths

- Never commit `data/` (it holds secrets + cached state).
- Never commit `.env` (keep `.env.example` current though).
- Run `uv run ruff check . && uv run pyright && uv run pytest`
  before committing.

### Branching

- `main` is the deployable branch.
- For substantial work create a `feat/short-name` branch; merge via PR
  or fast-forward when green.
- Don't push to `main` if tests fail.
