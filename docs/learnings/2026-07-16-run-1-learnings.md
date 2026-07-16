# 7,758 Run #1 — Learnings

Run started 2026-07-16 04:10:41, killed ~5h later.

## What happened

| Phase | Records | Status |
|---|---|---|
| Records 0–2,907 | 100% success | Clean run; 0 errors, BOTH MATCH ~26% |
| Records 2,908+ | Errors spike | DOM materialization crash |
| Killed at record 3,499 (45.4%) | — | Resume from here was tested and works |

## Root cause of the error spike

After ~3 hours (record ~2,900), the rate of `fag_status="error"` records
abruptly rose from 0% to 100%. The error messages were empty.

Investigation:

1. **Standalone repro** of the same pensioner (#3616 Louisa Barnes) in
   a fresh browser session works fine — `status='too_many'`. So it's not
   the data.
2. Strategy logs showed B4-fuzzy-last returning **236,702 results** for
   "Louisa Barnes" (super-common names). The next locator query
   `page.locator('a[href*="/memorial/"]').all()` tried to materialize all
   the locator refs in the DOM at once, which crashed the page context.
3. Once the browser context was broken, **all subsequent strategies
   failed silently** — the parser caught the exception, marked
   `any_error=True`, and returned `status='error'`.

### Fix (committed alongside this run)

`parse_results_page()` in `scripts/search_fag.py`: cap the locator
materialization to `MAX_FAG_RESULTS_TO_PARSE` (20) using the lazy
`.nth(i)` API instead of `.all()`:

```python
# Old (crashes on 200K-result queries):
link_locators = page.locator('a[href*="/memorial/"]').all()

# New (lazy, capped):
locator = page.locator('a[href*="/memorial/"]')
n_locator = min(locator.count(), MAX_FAG_RESULTS_TO_PARSE)
link_locators = [locator.nth(i) for i in range(n_locator)]
```

Also added a defensive cap log when `total > 2000`.

## Defensive measures for future runs

1. **Browser reset every N records** — `scripts/fag_browser.py` now
   refreshes the Playwright browser context every 500 records. This
   prevents cumulative state issues like the one we hit.

2. **Better error reporting** — when `status='error'` from FaG, the
   runner logs `strategies_run` for that pensioner. Future runs will
   have visibility into which strategy failed.

3. **Threading lock around the FaG search fn** — so the periodic
   browser reset doesn't race with in-flight requests.

## What worked well

- **Resume safety** — `ResumeTracker` correctly picked up at record
  3,654 when we re-ran. Zero duplicates in state.jsonl.
- **CGR blocking lookup** —<1s per pensioner for the CGR side.
- **BOTH MATCH corroboration** ran at 26.7% of processed records
  (matches the predicted 26% in the run plan).
- **Heartbeat** caught the issue while we still had good data.
- **Per-pensioner flush** means records 0–2,907 are safe and usable.

## What was unfinished

- Records 2,908–3,499 are tainted (errors). We have to decide whether
  to fix them in place or just accept the gaps in the report.
- The pipeline never got to the post-run `dd_marker_run` step.

## Plan for Run #2

Since Run #1 produced ~3,400 valid records but failed for ~1,000 + 
all the remaining ~4,300 records, Run #2 should:

1. Resume from record 3,654 (the run we just restarted after the fix).
2. **Expected to complete** with the locator fix in place.
3. If records 2,908–3,654 have errors (the bad segment from Run #1),
   we need a separate pass or just accept them.

## Decision tree for the remaining 3,654 records with errors

| State of record 3,654+ after resume | Action |
|---|---|
| All new records succeed | Resume Run #2 covers all gaps; no fix-up needed |
| Errors persist on some records | Document them as known failures; report says "~3,500 valid + 1,000 untested" |
| Errors stay bad for the resume | Identify specific pensioners that crash; report them as exceptions |

We'll monitor heartbeats over the next few hours.
