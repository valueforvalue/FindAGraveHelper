# Python + Playwright + Userscripts — Stack Addendum

> **Audience:** every agent that lands on a slice touching
> the Python runner, the Playwright browser layer, or the
> Tampermonkey userscripts. The workflow docs in
> [`../feature-protocol.md`](../feature-protocol.md) +
> [`../tdd.md`](../tdd.md) + [`../rpci.md`](../rpci.md) +
> [`../bug-patterns.md`](../bug-patterns.md) are
> stack-agnostic. This addendum carries the per-stack rules
> that earn their keep on this repo.

This addendum is the per-stack analogue of
[`addenda/go-htmx.md`](https://github.com/valueforvalue/agent-stack/blob/main/addenda/go-htmx.md)
in the upstream agent-stack repo. It cites the same stack-
agnostic workflow docs but layers the Python + Playwright +
userscript specifics on top.

## What this repo actually is

Three runnable surfaces share one repository:

1. **Tampermonkey userscripts** (`*.user.js`) run inside the
   user's browser. They scrape FaG memorial pages and (v4.0)
   run an iterative search helper. Plain JS, no build step,
   paste-into-Tampermonkey distribution.
2. **Python harness** (`scripts/*.py`) drives a Playwright
   Chromium to search FaG programmatically. Resume-safe via
   `state.jsonl` flushing per-pensioner. Heavy IO, throttle-
   sensitive, memory-leak-prone.
3. **Browser review UI** (`scripts/view.html`) loads the
   `state.jsonl`, lets a human pick the right candidate per
   pensioner, exports decisions as CSV. Static HTML + JS,
   no build, no server.

The cross-layer contract between them lives in
[`../cross-layer-contract.md`](../cross-layer-contract.md).
The per-layer bug catalog lives in
[`../bug-catalog.md`](../bug-catalog.md).

## Stack-specific laws (Python + Playwright + userscripts)

These extend the universal laws in
[`../laws-equivalents`](../bug-catalog.md#laws-citations).
Each one cites the commit / run that earned it.

### Type hints on public surface (Python)

Every public function in `scripts/` carries a type hint for
its arguments and return. The reasoning is the same as Go's
doc-comment law: callers (including future agent sessions
that re-read the code with fresh eyes) need to know the
contract before the call. `_probe_*.py` scripts are exempt
(one-off investigations).

### No mutable default args (Python)

`def f(x=[])` is the classic Python bug factory. The lint
check is on every PR.

### Resume-safe state writes (Python)

Every per-pensioner record flushes to `state.jsonl` BEFORE
the next pensioner starts. A crash mid-run leaves the file
re-loadable by re-running with the same `--state` path. See
[`scripts/pipeline/checkpoint.py`](../../scripts/pipeline/checkpoint.py) for
the canonical flush pattern.

### Throttle is the rate limit (Playwright)

FaG's Cloudflare Turnstile detects request rates > 1
request/second sustained. The throttle (`--throttle`, default
2.5s) is the only thing between the run and a 30-minute
backoff. **Never bypass it for "speed"** — the speed-up is
zero (the backoff dwarfs the saved throttle time) and the
cost is a wedged run.

Earned by: Run #1 (2026-07-16, see
[`docs/learnings/2026-07-16-run-1-learnings.md`](../../docs/learnings/2026-07-16-run-1-learnings.md)).

### Browser reset on closed-target (Playwright)

Playwright's "Target page, context or browser has been closed"
error means the connection objects are stale. The harness
must reopen browser → context → page, drop refs to None,
then `gc.collect()` before the next request. Partial reset
(only closing Browser) leaks Context + Page refs and grows
RSS unboundedly.

Earned by: Run #2 (2026-07-16, see
[`docs/learnings/2026-07-16-run-2-learnings.md`](../../docs/learnings/2026-07-16-run-2-learnings.md)).

### Userscripts match the exact hostname (JS)

`@match` must be the literal FaG hostname (no wildcards that
include `staging.findagrave.com` or similar). Earned by a
contributor adding `@match *://*.findagrave.com/*` and
matching the dev/staging instance during a test scrape.

### Userscript edits are user-facing, not internal

A change to `FindaGraveScraper.user.js` is a change to a
file the user runs in their browser. The diff lands in their
Tampermonkey editor; an uninstall + reinstall is the
"deploy". Treat the regression net as the
`tests/` Python suite (which loads the JSON export of the
userscript + simulates the pipeline).

## Per-layer recipes

### Python (scripts/*.py)

- **Module-level state for fixtures**: use module-level
  constants for normalization tables (state abbreviations,
  phonetic codes) — they're immutable and reading them
  inside hot loops is fine.
- **Per-record flush**: write the JSONL line, then
  `f.flush(); os.fsync(f.fileno())` before moving on. The
  `os.fsync` is the only thing that survives a `kill -9`.
- **Logging**: structured key=value pairs in `run.log`. The
  per-pensioner line MUST include the pensioner_id and the
  outcome (`BOTH_MATCH`, `auto_accept`, `no_results`,
  `error`).

### Playwright (scripts/fag/fag_browser.py)

- **Stealth + warmup**: launch with
  `playwright-stealth`, then visit
  `https://www.findagrave.com/` before any search. The
  warmup establishes the Cloudflare session cookie.
- **Closed-target detection**: match a stable substring list
  against `str(exception)` — Playwright's exception text
  drifts across versions, but "target closed" / "browser has
  been closed" are stable.
- **Locator hygiene**: `await locator.all()` returns live
  refs. Drop them to a list, then `del locator_list` +
  `gc.collect()` after parsing. Same for
  `page.inner_text("body")` — the full-page string lives
  until function exit unless you `del` it.

### Userscripts (*.user.js)

- **No `eval`** — userscripts run with elevated trust; any
  `eval` is an XSS vector when the scraped memorial page
  contains attacker-controlled content.
- **`GM_setValue` for persistence, not localStorage** — the
  userscript manager scopes `GM_setValue` per-script.
  `localStorage` is shared with the host page.
- **Document the panel layout in the script header** —
  contributors editing the panel need a stable contract.
  The README points at `FindaGraveScraper.user.js` line 1.

### Static HTML (scripts/view.html)

- **No build step** — the file is opened directly in a
  browser. Any new dependency must be a single file or a
  CDN URL.
- **State file is the input contract** — `view.html` reads
  `state.jsonl`, never a transformed derivative. If you
  want a different shape, transform in Python and write a
  new `state.jsonl`.
- **Decisions export is the output contract** — the CSV
  schema is consumed by `scripts/pipeline/dd_marker_run.py` to mark
  records in the user's local dixiedata DB. Changes to the
  schema break the round-trip; treat as breaking.

## Python testing recipes

> Sibling of [`../testing-philosophy.md`](../testing-philosophy.md).
> The core doc gives the *bar* (which tests earn their place);
> this section gives the *Python/pytest recipes* that meet it.

### 1. `@pytest.mark.parametrize` over N near-duplicate tests

Per core §"Consolidation": N tests that exercise the same
function with different inputs collapse into one
parametrized test. The parametrize table IS the coverage
map.

```python
import pytest

@pytest.mark.parametrize("input,expected", [
    ("", "default"),
    ("abc", "abc"),
    ("  ", "default"),
])
def test_normalize(input, expected):
    assert normalize(input) == expected
```

Add a row per new edge case; do not write a new test
function. If you need a brand-new test function, you're
testing a different code path — that's the
"when NOT to consolidate" carve-out (core §"Consolidation").

### 2. `@pytest.mark.diag` for diagnostic probes

Per core §"Diagnostic tests that always skip":
file-existence / binary-built / env-var-gated tests live
under `@pytest.mark.diag` and are filtered out of the
default run.

```python
# In pytest.ini, add to markers:
#   markers =
#     integration: tests that need a real browser
#     diag: tests that probe manual-only fixtures

# In tests/test_leak_fix_real.py:
import pytest

@pytest.mark.diag
def test_live_browser_smoke():
    if not os.path.exists("scripts/soak_memory.py"):
        pytest.skip("soak harness not built")
    # ...
```

Run diagnostics intentionally:

```bash
pytest -m diag ./tests/                  # diag-only
pytest -m "diag or integration" ./tests/  # both gated suites
```

The default run (`pytest tests/`) skips them via the
existing `addopts = -m "not integration"` convention. Add
`not diag` if the default should also skip diag probes.

### 3. Mutation testing with `mutmut` or `cosmic-ray`

Per core §"Test-the-tests" (Tip #64): Python mutation
testing is the operational form of "is your test actually
catching the bugs it claims to catch?"

```bash
pip install mutmut
mutmut run --paths-to-mutate=scripts/
mutmut results
```

The mutation score is the complement to line coverage: a
test file at 100% line coverage with a 20% mutation score
is testing coverage inflation, not state coverage. See
`../testing-philosophy.md` §"Test state coverage, not
code coverage."

### 4. Stdlib re-test anti-pattern

Per core §"Tests of stdlib primitives → cut": cut any
test whose core assertion is "the stdlib function works
as documented." Examples specific to this repo's pytest
idioms:

- `assert len(list(iter([1,2,3]))) == 3` — testing
  `list()` and `iter()`, not your code.
- `assert dict.update({"a":1}, {"b":2}) == {"a":1,"b":2}`
  — testing dict's documented behavior.
- `assert re.match(r"\d+", "123") is not None` — testing
  `re`, not your extractor.

**Decision rule:** if you can replace the stdlib call in
the test with the literal expected value and the test
still passes, the test is testing the stdlib, not your
code. Cut it.

### 5. Brittle-test mitigation in Python

Per core §"Brittle tests": assert on structural
properties, not exact strings. In Python this usually
means:

- `assert "data-theme=high-contrast" in html` (substring)
  not `assert html == "<html lang=en ...">` (exact match).
- For JSON / state.jsonl assertions, parse and compare
  fields (`assert record["status"] == "ok"`), not full-
  text equality.
- For Playwright assertions, prefer
  `expect(page.locator(...)).to_be_visible()` (state) over
  `assert page.content() == "..."` (snapshot).

### 6. Property-based tests with `hypothesis`

Per core §"Find bugs once" (Tip #66) + the agent-stack
spine row for Tip #71 (Property-Based Tests): when a
function's doc-comment claims "handles edge cases X, Y,
Z," back the claim with a `hypothesis` property test
that enumerates the input space.

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=0, max_size=1000))
def test_normalize_never_crashes(s):
    # The doc-comment claim: "normalize handles any string
    # input without raising."
    normalize(s)  # must not raise
```

The harness already has property-test infrastructure in
`tests/test_fellegi_sunter_real.py` (uses `hypothesis`).
Follow that pattern when adding property tests for new
matchers / scorers.

### References

- [`../testing-philosophy.md`](../testing-philosophy.md) —
  the bar this section implements
- §"Per-layer recipes" above — Python / Playwright /
  userscript / view.html test-floor recipes
- `pytest.ini` — marker registration + default filter

## Cross-references

- [`../feature-protocol.md`](../feature-protocol.md) — slice
  discipline universal
- [`../tdd.md`](../tdd.md) — red-green-refactor universal
- [`../rpci.md`](../rpci.md) — flow universal
- [`../bug-catalog.md`](../bug-catalog.md) — per-layer bug
  patterns earned by real runs
- [`../cross-layer-contract.md`](../cross-layer-contract.md) —
  the wire format between Python + view.html + userscripts
- [`../../docs/learnings/`](../../docs/learnings/) — run
  logs that earned the laws above