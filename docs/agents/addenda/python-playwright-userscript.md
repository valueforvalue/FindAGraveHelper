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