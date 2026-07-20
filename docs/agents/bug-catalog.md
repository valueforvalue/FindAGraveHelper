# Bug Catalog

> **Audience:** every agent debugging a recurring class of bug
> on this repo. The pattern + `Find it:` grep is the
> diagnostic head-start; the linked run-log is the
> forensic detail. Bugs earn their way in here after a
> real run, not speculatively.

Each entry follows:

```
### <Symptom>
<one-line diagnosis>

**Find it:** `grep -n '<pattern>' scripts/`

**Earned by:** <commit hash> | <run log link>

**Fix shape:** <one or two sentences>
```

## Laws citations

These are the laws the catalog enforces. They live in
[`CONTEXT.md` §"Laws (non-negotiable)"](../../CONTEXT.md#laws-non-negotiable)
and were each earned by a real bug.

| Law | Earned by |
|---|---|
| Throttle is the rate limit (Playwright) | Run #1 DOM crash + Run #2 memory leak (2026-07-16) |
| Browser reset on closed-target (Playwright) | Run #2 (2026-07-16) |
| Resume-safe state writes (Python) | Run #1 mid-run crash (2026-07-16) |
| Stable JSON key order in `state.jsonl` | Run #1 view.html reload (2026-07-16) |
| One line per pensioner in `state.jsonl` | Run #1 mid-run crash (2026-07-16) |
| Userscript edits are user-facing | (general) |
| Doc comments on exported Python functions | (general) |

---

## Playwright layer (`scripts/fag/fag_browser.py`, `scripts/blackboard/`)

### Locator refs leak into the body string retention

**Symptom:** `page.inner_text("body")` returns a 200KB+ string
on every result-page parse. The string lives until function
exit. On a 7,709-record run, that's ~1.5 GB of dead strings
by record 4,000.

**Find it:** `grep -n 'inner_text\|link_locators' scripts/fag/ scripts/search/`

**Earned by:** Run #2 (2026-07-16) — see
[`../docs/learnings/2026-07-16-run-2-learnings.md`](../docs/learnings/2026-07-16-run-2-learnings.md).

**Fix shape:** After parsing, `del locator_list; del body_text; gc.collect()`.
Run `gc.collect()` every 25 records (not every record — too expensive).

### `_open_browser()` only closes the Browser, not Context or Page

**Symptom:** Browser reset appears to work (browser is closed),
but Context and Page refs are still held by the harness. RSS
keeps growing through resets. After 4 resets, Playwright
throws "too many open contexts".

**Find it:** `grep -n 'browser.close\|context.close\|page.close' scripts/fag/ scripts/blackboard/`

**Earned by:** Run #2 (2026-07-16) — see
[`../docs/learnings/2026-07-16-run-2-learnings.md`](../docs/learnings/2026-07-16-run-2-learnings.md).

**Fix shape:** Close in order `page → context → browser`. After close, set
all three to `None`. Run `gc.collect()` once before the next spawn.
The Blackboard provider safety layer (`scripts/blackboard/`)
does this via `BrowserSession` reverse-order teardown.

### Closed-target detection uses brittle exception strings

**Symptom:** Playwright's exception text drifts across versions.
A recovery check that matches the literal text "Target page,
context or browser has been closed" breaks on the next
Playwright release.

**Find it:** `grep -n 'target.*closed\|browser.*closed' scripts/fag/ scripts/blackboard/`

**Earned by:** Run #2 — the original check used the literal text.
After a Playwright bump the recovery stopped triggering.

**Fix shape:** Match against a stable substring list
(`["target closed", "browser has been closed", "context closed"]`).
Don't rely on the full message; rely on substrings.

### `parse_results_page()` consumes relative URLs as if absolute

**Symptom:** Zero candidate links parsed even though the result
list is visible on the page. Search "succeeds" with `no_results`.

**Find it:** `grep -n 'findagrave.com/memorial\|memorial/\${' scripts/search/`

**Earned by:** Run #0 (2026-07-15, smoke test) — first FaG scraper
implementation.

**Fix shape:** Use `page.evaluate("el => el.href", link)` or
match `/memorial/...` (relative) not `https://...` (absolute).
See finding #5 in
[`../docs/learnings/README.md`](../docs/learnings/README.md).

### Cloudflare 1015 detected only after the rate-limit page has fully loaded

**Symptom:** The harness scrapes the Cloudflare "You have been
rate-limited" page as if it were a result page. Returns 0
candidates with no error. The rate-limit is silently absorbed.

**Find it:** `grep -n 'rate.limited\|attention required\|1015' scripts/blackboard/`

**Earned by:** Run #1 — first major Cloudflare challenge mid-run.

**Fix shape:** Detect the Cloudflare page text BEFORE parsing
results. On detection, sleep 30s and retry with a fresh
navigator (or warmup page). The Blackboard `ResponseClassifier`
runs in `BrowserSession` before parsing.

### Search `body=` doesn't accept Boolean operators

**Symptom:** Search `body="Civil War" OR "CSA" OR "Confederate"`
returns zero results even when valid matches exist.

**Find it:** N/A (FaG-side behavior, not in our code)

**Earned by:** Phase 2 research validation, 2026-07-10.

**Fix shape:** Use the most specific narrowing term
(`body=Confederate States America`). See finding #8 in
[`../docs/learnings/README.md`](../docs/learnings/README.md).

### Two Playwright sessions in one process = asyncio loop error

**Symptom:** After the FaG search loop closes its
`sync_playwright` session, a post-pass step (spouse scrape,
replay, projection) tries to open a fresh `sync_playwright`
in the same Python process and fails with "Playwright Sync
API inside the asyncio loop."

**Find it:** `grep -n 'sync_playwright()' scripts/`

**Earned by:** 2026-07-16 spouse_compare pass — same
playwright session reuse in one process.

**Fix shape:** Subprocess the second Playwright use.
`scripts/pipeline/run_unified.py` invokes the spouse scrape
as a subprocess so it gets a fresh asyncio event loop.
Cost: ~300ms Python startup; negligible vs the 30-min run.

---

## Python layer (`scripts/*.py`, except `fag_browser.py`)

### State not flushed before next pensioner starts

**Symptom:** Crash mid-run loses the last 5-20 records. Resume
shows them as "already done" but the file doesn't have them.

**Find it:** `grep -n 'flush\|fsync' scripts/state/ scripts/pipeline/run_unified.py`

**Earned by:** Run #1 mid-run crash (2026-07-16) — lost ~40
records to a CTRL-C. Re-earned in issue #22 — the original
`write_unified_line` only flushed, not fsync'd.

**Fix shape:** After writing the JSONL line, call
`f.flush(); os.fsync(f.fileno())` BEFORE the next pensioner
loads. The `StateRepository.append()` method enforces this
(L10); calling code MUST NOT bypass the Repository.

### Module-level state isn't actually module-level

**Symptom:** Tests pass individually but fail when run together.
A module's `_state = {}` reset between tests but the global
shortcut `STATE = _state` retained the previous test's data.

**Find it:** `grep -nE '^[A-Z_]+\s*=\s*\{' scripts/`

**Earned by:** `test_state_names_module_level.py` existence
(see file).

**Fix shape:** Module-level state MUST be a fresh `{}` per
module load. Don't share via `from module import STATE`.

### FaG search scope leaks across pensioners

**Symptom:** A query that succeeds for pensioner A returns
results for pensioner B's name on the next iteration. The
URL parameters carry over because `page.goto()` only replaces
the path, not query params.

**Find it:** `grep -n 'page.goto\|search_url' scripts/search/fag_engine.py`

**Earned by:** Phase 2 research validation, 2026-07-10.

**Fix shape:** Build the URL with all required params explicitly.
Don't rely on `goto(url)` to overwrite the prior URL's query
string. The fix was to pass `--location-id` (US-only) and
the appropriate state ID.

### Threshold drift across modules (#37)

**Symptom:** `LOW_SCORE_THRESHOLD = 0.40` declared in
`blackboard/decision_policy.py` and `0.4` literal in
`batch_config.py` and `pipeline/leftover_investigation.py`.
A tweak to one misses the others. STATUS_* constants likewise
declared locally.

**Find it:** `grep -nE 'THRESHOLD\s*=\s*0\.' scripts/`

**Earned by:** Issue #37 audit.

**Fix shape:** Import from `scripts/pipeline/scoring_constants.py`.
Local copies are deprecated aliases (PEP 562 `__getattr__`)
that emit `DeprecationWarning`. Pinned by
`tests/test_scoring_constants_dedup.py` (L9).

### Non-deterministic observation IDs

**Symptom:** Resume re-emits the same `FaGSearchExecuted`
observation with a fresh ID; the store accumulates two
records for one logical event; downstream counts double.

**Find it:** `grep -n 'observation_id\|uuid' scripts/blackboard/`

**Earned by:** Scheduler Phase 5 smoke runs (2026-07-19).

**Fix shape:** Derive the observation ID deterministically
from the payload hash (`SHA-256(kind | pensioner_id | plan_id
| strategy_name | ts_bucket)`). The store's
`append_observation` runs the dedup; calling code SHOULD NOT
pre-assign IDs (L11).

### Stale lease never reclaimed

**Symptom:** `FaGScraperKS` hits a Cloudflare challenge
mid-invoke and crashes; the leased WorkItem stays in
`LEASED` forever; no other pensioner gets processed because
the lease holds the row.

**Find it:** `grep -n 'reclaim_stale_leases\|lease_ttl' scripts/blackboard/`

**Earned by:** Scheduler Phase 5 (2026-07-19).

**Fix shape:** Lease with TTL (default 60s). Scheduler
reclaims past-deadline leases each cycle. After 3 failed
attempts, WorkItem → `BLOCKED` for operator review (L12).
Pinned by `tests/test_blackboard_scheduler.py`.

---

## Userscript layer (`*.user.js`)

### Edit panel without bumping the version in the `@version` header

**Symptom:** User installs the new script but Tampermonkey
doesn't auto-update because the `@version` is unchanged. The
user reports "the new feature doesn't work" — they're on the
old version.

**Find it:** `grep -n '@version' FindaGraveScraper.user.js FindaGraveIterativeHelper.user.js`

**Earned by:** (general) — script distribution hazard.

**Fix shape:** Bump `@version` on every commit that changes
the script. The SemVer floor is patch-level (0.0.X).

### `GM_setValue` quota exceeded on a long scrape session

**Symptom:** After ~500 memorials, the scrape silently stops
recording. The user thinks the panel is broken.

**Find it:** `grep -n 'GM_setValue' FindaGraveScraper.user.js`

**Earned by:** (general) — Tampermonkey's `GM_setValue` has a
~5MB cap by default.

**Fix shape:** Periodically flush to a data URI and trigger
`GM_download` to archive. The current panel does this on
"Export Data (N)" click; the bug is when the user keeps
scraping past the cap.

---

## Review UI layer (`scripts/view/v2.html`, legacy `scripts/view.html`)

### Decisions sidecar schema drift breaks `scripts/state_normalize.py`

**Symptom:** v2 view's "Save decisions" button writes a sidecar
JSON with `decided_choice` + `decided_choice_slug` +
`decided_choice_url`; a downstream normalizer reads the old
schema (`decided_choice_slug` missing) and KeyErrors.

**Find it:** `grep -n 'decided_choice\|decided_at' scripts/state_normalize.py scripts/view/v2.html`

**Earned by:** v2 view export shape migration (2026-07-19).

**Fix shape:** Sidecar schema is owned by `buildDecisionsBlob()`
in v2. Any schema change MUST land with a matching
`scripts/state_normalize.py` change. Pinned by
`tests/test_view_html_v2_export.py`.

### Loading 7,709 records freezes the v1 view.html tab

**Symptom:** Open the legacy `scripts/view.html` with the full
run output, the tab becomes unresponsive for 30+ seconds.

**Find it:** N/A (browser-side perf)

**Earned by:** Run #1 view.html review (2026-07-16).

**Fix shape:** v2 view chunks rendering: first 50 sync, rest
via `requestAnimationFrame`. The legacy view stays lazy-loaded
in chunks of 500. Default to v2 for new runs.

### Embed detection by comment-substring silently skips second pass

**Symptom:** The second-pass embed check uses
`'id="embedded-results-jsonl"' not in text` to detect whether
to embed. The source has the literal in JS comments; the
check returns True even when no real `<script>` tag exists;
the page renders 0 cards.

**Find it:** `grep -n 'id="embedded' scripts/pipeline/run_unified.py`

**Earned by:** J11–J15 burst (2026-07-16), found in THREE places
(J9 results, J14 dd_match, J15-S2 spouse_match).

**Fix shape:** Match a structural regex
(`<script ... id="...">[^>]*>\s*\{`) — comments never have
both adjacent. When fixing, search the codebase for the same
pattern elsewhere. One bug = three copies.

---

## Cross-cutting

### `findagrave.com/memorial/search` rate-limit returns 200 OK

**Symptom:** `requests.get()` returns 200 OK but the body is
the Cloudflare Turnstile challenge page. The script thinks
the search succeeded.

**Find it:** `grep -n 'requests.get\|requests.post' scripts/`

**Earned by:** Phase 1 research, 2026-07-08.

**Fix shape:** Don't use `requests` for FaG — always go
through Playwright + stealth. The
[`scripts/fag/fag_browser.py`](../../scripts/fag/fag_browser.py)
module is the only sanctioned path.

### A state abbreviation match grabs "Co."

**Symptom:** Unit string `Co. I, 4th TN Cav. Rgmnt., C.S.A.`
parses as "Colorado" (CO) because the regex matches "Co.".

**Find it:** `grep -n 'state\|CO\|Colorado' scripts/state/state_check.py scripts/state_normalize.py`

**Earned by:** Phase 1 research, 2026-07-08.

**Fix shape:** Skip "CO" in the abbreviation match. Normalize
"Co." → "Co" before matching. Or use full state names.

---

## When to add to this catalog

After a real bug fix lands, add an entry. The discipline:
the entry must cite the commit hash + a run-log link. No
speculative entries; no "watch out for this" without a
fingerprint.