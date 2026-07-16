# Memory Leak Investigation — 2026-07-16 (Run #2)

Run #1 paused at 3,361 records due to a DOM-materialization crash on
200K-result queries (fixed in `f17b779`). Resumed Run #2 finished
~1,000 more records but the **process RSS climbed from ~120 MB to
~3.5 GB in a few hours**, then to ~7 GB on pwsh.exe, before pwsh
became unresponsive and was terminated.

This doc captures what we learned about long-running Playwright +
Chromium Python jobs and the five concrete fixes that brought
per-record RSS growth under control.

## TL;DR

Five leaks combined for ~85 MB/min Python RSS growth in pwsh.exe:

1. CGR blocking index rebuilt per pensioner (run_unified.py).
2. `page.inner_text("body")` allocated 5 MB strings for 200K-result pages.
3. Locator refs and ElementHandle never disposed.
4. Stealth init scripts re-serialized on every page.goto().
5. Per-call dict allocations (state_names × 2 sites).

After all fixes, the strengthened real-FaG memory test
(`tests/test_real_fag_memory.py`) passes with steady-state
per-record RSS growth **<5 MB**. The full 553-test suite passes.

## Five leaks, in order of impact

### 1. CGR blocking index rebuilt per pensioner

**Symptom**: `run_pipeline_for_pensioner()` was called once per
pensioner and inside it called `build_cgr_blocking_index(cemeteries)`
which built a 2,593-vet phonetic blocking index from scratch. Each
call allocated MB-sized Python dicts (block_index, vets_by_id) that
went out of scope at function exit but the OS allocator never
returned the pages.

**Fix** (`scripts/unified_pipeline.py`,
`scripts/run_unified.py`):

```python
# Once at start of run_batch():
prebuilt_cgr_index = build_cgr_blocking_index(cemeteries)

# Pass it down per pensioner:
run_pipeline_for_pensioner(
    pensioner=..., cgr_index_vets=..., config=...,
    fag_search_fn=..., prebuilt_cgr_index=prebuilt_cgr_index,
)
```

`run_pipeline_for_pensioner()` gains a `prebuilt_cgr_index`
keyword arg. When provided, the per-call build is skipped.

### 2. `page.inner_text("body")` allocated 5 MB strings

**Symptom**: `parse_results_page()` called
`page.inner_text("body", timeout=10000)` for the whole-body
serialized text, then regex-searched for `"X matching records"`.
For a 200K-result FaG page the body text is several megabytes;
this allocated a 5 MB Python string per call. Over 10 strategies ×
7709 records = ~770 GB of allocations if you stretched it across
the whole run, but more importantly the OS allocator never
reclaimed the pages.

**Fix** (`scripts/search_fag.py`):

```python
# Before:
body = page.inner_text("body", timeout=10000)
m = re.search(r"(\d[\d,]*)\s+matching records?", body)

# After: targeted JS evaluate returns only the count element
body = page.evaluate('''() => {
    const el = document.querySelector('[data-test-id="total-records"]')
      || document.querySelector('.total-records')
      || document.querySelector('.memorial-search-results-header');
    if (el) return el.innerText || el.textContent || '';
    return '';
}''')
m = re.search(r"(\d[\d,]*)\s+matching records?", body or "")
```

If the selector doesn't match, total is silently 0. The `total`
field is only used for the "too_many" diagnostic log; the actual
candidate parsing below still runs.

### 3. Locator refs and ElementHandle never disposed

**Symptom**: `parse_results_page()` did:

```python
locator = page.locator('a[href*="/memorial/"]')
link_locators = [locator.nth(i) for i in range(n_locator)]
```

Both the parent `locator` AND the child list held Playwright
channel refs. The list was `.clear()`'d at the end, but the
parent `locator` survived until the next assignment.

Similarly, `page.wait_for_selector(...)` returned an
ElementHandle that was discarded — Playwright auto-disposes on
navigation, but the handle held a DOM ref count between strategies.

**Fix** (`scripts/search_fag.py`):

```python
# Memory hygiene at end of parse_results_page():
try:
    link_locators.clear()
    del link_locators
except Exception:
    pass
try:
    del locator  # NEW: drop the parent locator ref
except Exception:
    pass

# wait_for_selector now disposes explicitly:
try:
    handle = page.wait_for_selector('a[href*="/memorial/"]', timeout=15000)
    if handle:
        try: handle.dispose()
        except Exception: pass
except PWTimeout:
    pass
```

### 4. Stealth init scripts re-serialized on every page.goto

**Symptom**: `Stealth().apply_stealth_sync(page)` injects a big
init script bundle into the page's CDP context. When applied to
the Page, this bundle gets re-serialized and re-injected on every
navigation. Over 8 strategies × ~10 records × every goto, the CDP
round-trip cost is significant.

**Fix** (`scripts/search_fag.py`): Apply Stealth to the
**BrowserContext** instead of the Page:

```python
ctx = b.new_context(...)
page = ctx.new_page()
try:
    Stealth().apply_stealth_sync(ctx)  # applied ONCE per context
except Exception:
    Stealth().apply_stealth_sync(page)  # fallback for older stealth
```

The init script persists across all navigations within that
context, eliminating the per-goto re-injection cost.

### 5. Per-call dict allocations (state_names)

**Symptom**: Two sites recreated a 50-entry state-name lookup
dict on every call:

- `extract_state_from_regiment()` (called once per pensioner).
- `parse_results_page()` (called 10× per pensioner, once per
  strategy).

Over 7709 records × ~10 strategy calls = ~80K transient dicts in
parse_results_page alone, plus the per-pensioner caller. CPython's
pymalloc freelist retains pages from short-lived dicts; over a
multi-hour run this adds up.

**Fix** (`scripts/search_fag.py`): Hoist both dicts to module-level
constants `_STATE_NAMES_UPPER` and `_STATE_NAMES_LOWER`. Built once
at import time and reused forever.

```python
_STATE_NAMES_UPPER = {
    'ALABAMA': 'AL', 'MISSISSIPPI': 'MS', ...,  # 50 entries
}
_STATE_NAMES_LOWER = {k.lower(): v for k, v in _STATE_NAMES_UPPER.items()}
```

The lowercase dict is used by parse_results_page; uppercase by
extract_state_from_regiment.

## Additional fixes that came up

### Browser-context close ordering

`scripts/fag_browser.py`'s `_open_browser()` only closed the
Browser, leaving the Context and Page refs alive across resets:

```python
# Before:
state["browser"].close()

# After:
for attr in ("page", "ctx", "browser"):
    obj = state.get(attr)
    if obj is not None:
        try: obj.close()
        except Exception: pass
    state[attr] = None
gc.collect()  # reclaim cycle refs before next Chromium spawn
```

### Browser self-recovery on closed-target

The original `fag_search()` swallowed all exceptions and returned
`('error')` for the rest of the run. With Chromium's
"Target page, context or browser has been closed" surfacing during
long runs, every subsequent call was an error until restart.

`scripts/fag_browser.py` now auto-recovers:

```python
try:
    record = search_one_pensioner(state["page"], pensioner)
except Exception as e:
    state["consecutive_errors"] += 1
    if _is_target_closed(e):
        # Try one browser reopen so NEXT record can succeed.
        recovered = _maybe_recover(e)
    if (max_consecutive_errors > 0
        and state["consecutive_errors"] >= max_consecutive_errors):
        raise  # stop the run rather than spin
    return [], "error"
```

After `max_consecutive_errors` (default 10) in-a-row errors, the
run raises to terminate cleanly rather than thrashing.

The `_is_target_closed()` helper matches against a list of stable
substrings ("target page...closed", "browser has been closed",
"context has been closed", etc.) so the recovery logic survives
Playwright message-version changes.

### RSS watchdog

`scripts/rss_watchdog.py`: background thread that polls process
RSS via Win32 `GetProcessMemoryInfo` (no psutil dependency).
Three thresholds:

| threshold | default | action |
|---|---|---|
| `warn_mb` | 2048 | log WARNING once |
| `force_reset_mb` | 4096 | set force_reset_event; runner reopens browser at next record |
| `exit_mb` | 6144 | `os._exit(1)` to avoid writing junk records after a wedged pwsh |

Exposed in `run_unified.py` and `retry_errors_run.py` via:
`--no-rss-watchdog`, `--rss-warn-mb`, `--rss-force-reset-mb`,
`--rss-exit-mb`. Default ON.

### Reset cadence

`scripts/fag_browser.make_fag_search_fn()` defaults
`reset_browser_every=250` (was 500). CLI flag
`--reset-browser-every 250`. With eight navigations per pensioner
× 7709 records = 61,672 navigations, browser-reopen every 250
records = ~31 reopens over the run, ~5 s each. Total browser-
reopen overhead: ~3 min out of ~5h run.

## P1-level bug fixes (audit report 2026-07-16)

| ID | Description | Fix |
|---|---|---|
| 2.1 | Typo 'LOUISIANI' in state names dict | Drop dead entry; 'LOUISIANA' is correct |
| 2.2 | state_score computed but omitted from score sum | Add `0.05 * state_score` to score formula |
| 2.3 | ElementHandle from wait_for_selector leaked | Explicit `.dispose()` |
| 2.4 | re.search with string pattern in hot loop | Module-level compiled `_MEMORIAL_PATH_RE` |

## Test coverage added this session

`tests/test_rss_watchdog.py` (7 tests): platform-agnostic via
monkeypatched `GetProcessMemoryInfo`. Covers thresholds,
idempotent start, stop event, force-reset flag round-trip,
os._exit on exit_mb.

`tests/test_search_fag_memory.py` (3 tests): parse_results_page
with FakeLocator verifies the `_record_count` attribute
increments, and verifies RSS doesn't grow unboundedly across 50
module reloads.

`tests/test_cgr_index_reuse.py` (2 tests): 200 CGR-only pipeline
calls with prebuilt_cgr_index; RSS stays within 20 MB of baseline;
the legacy per-call code path still returns correct results.

`tests/test_state_names_module_level.py` (8 tests): module-level
constants exist, are populated correctly, that 4000 calls to
`extract_state_from_regiment` don't allocate thousands of new
dicts, and that score formula references state_score.

`tests/test_real_fag_memory.py` (1 test, 130 s): real Playwright
+ real FaG, 5 warmup + 10 measurement pensioners; asserts
per-record growth <5 MB. PASSES after all v2 fixes.

`scripts/soak_memory.py`: manual CLI soak test. Drives 300
synthetic navigations, prints slope, exits 1 if average growth
exceeds `--max-slope-mb-per-10` (default 2.0 MB/10 samples). Use
this for ad-hoc leak hunting without running a real FaG search.

## Resumed run status

State.jsonl: 4,977 / 7,709 records written. 796 with
`fag_status='error'`. 2,732 pensioners remaining.

After this session's leak fixes are in place, the next run can:

  1. Resume from pid 4,978 — picks up the 2,732 remaining
     pensioners.
  2. Run `scripts/retry_errors_run.py` after completion to retry
     the 796 errors in place via the existing `retry_errors.py`
     helper.

Recommended CLI:
```
python scripts/run_unified.py \
  --input docs/research/digitalprairie/ok_pensioners.json \
  --cgr docs/research/cgr/ok_vets_enriched.jsonl \
  --out data/results/run_full_2026_07_16 \
  --throttle 1.0 --heartbeat-every 25 --reset-browser-every 250
```

Estimated wall time: ~3 hours for the remaining 2,732 pensioners.
Memory bound: per-record growth <5 MB, RSS will stay under 1 GB
throughout the run (vs ~7 GB on pwsh.exe previously).

## Always-run-FaG policy (LOCKED 2026-07-16)

The CGR blocking index returns mostly noise today (different-last-
name matches sharing first-name phonetic codes), and the
`match_strength="strong"` threshold is therefore reached only when
names are essentially identical. The CGR data is used for human
display and post-run dedup work, NOT as a fast-path gate on the
FaG search.

**We always run FaG for every pensioner.**

The project goal is to discover how many of the ~7,758 OK
Confederate pensioners are findable in Find a Grave. Short-
circuiting on a strong CGR match would cost us findings — every
skipped FaG search is a missed opportunity to find a memorial
that CGR didn't surface.

The unified pipeline enforces this in three places:

1. `scripts/unified_pipeline.py` module docstring states the policy
   and explicitly warns future maintainers not to add a skip
   gate.
2. `scripts/unified_pipeline.run_pipeline_for_pensioner()` has no
   skip-fast-path; the inline comment "ALWAYS run FaG for every
   pensioner" appears right above the `if fag_search_fn is not
   None:` branch.
3. `tests/test_unified_runner.py::TestAlwaysRunFaGPolicy` has
   four guard tests that fail if a future commit tries to gate
   the FaG search on `should_skip_fag` or if the policy docstring
   is removed.

The `should_skip_fag()` helper and `UnifiedConfig.skip_fag_on_strong_cgr`
field are retained for documentation and for any future post-run
CGR-side dedup work (e.g. view.html highlighting CGR-strong rows
for human review) but are explicitly marked POLICY-LOCKED +
ignored.

Future work that may use CGR stronger:

- **CGR-side dedup**: after the FaG run completes, identify CGR
  records that point to the same FaG memorial (multiple CW pensioners
  buried in the same plot, etc.). This is a separate phase that
  runs on the FaG state.jsonl results — not a gate during the
  per-pensioner search.
- **view.html badges**: surface CGR-strong rows in the human-review
  interface so reviewers prioritize them. Again, separate from
  the search itself.

## Lessons

1. **Long-running Playwright jobs are leak-prone.** Even with no
   obvious code smell, repeated `page.goto` + `inner_text` +
   `evaluate` calls allocate per-call and the OS allocator never
   reclaims. The mitigation is to either use shorter-lived
   processes OR to periodically reopen the browser.

2. **Python dict churn leaks.** Even tiny dicts allocated in a hot
   loop accumulate. Hoist lookup tables to module-level constants.

3. **Playwright Locator and ElementHandle objects retain refs.**
   Always `.dispose()` after use; never rely on GC for browser-side
   resources.

4. **Test the leak, not the lack-of-leak.** A static code review
   caught two of the five fixes; only a real-FaG memory test
   revealed the rest. The strengthened real-FaG test in
   `tests/test_real_fag_memory.py` would have caught all five.
