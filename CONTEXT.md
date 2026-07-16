# Find a Grave Helper

A pair of Tampermonkey/Greasemonkey userscripts for working with
[Find a Grave](https://www.findagrave.com) memorials, plus a
Python harness that batch-searches FaG for Confederate soldiers
associated with Oklahoma, plus a static-HTML review UI that lets a
human pick the right candidate per soldier.

**Project goal:** find Confederate soldiers associated with
Oklahoma who are not yet in Find a Grave. The 1915 Oklahoma
Confederate Pension Act created a Board of Pension Commissioners
that documented every Confederate veteran (or widow) who applied
for a state pension — a canonical list of ~7,758 OK-associated CW
soldiers. We use this list as input, and FaG's `/memorial/search`
as the lookup target.

## Language

**Pensioner**:
A Confederate veteran (or widow) who applied for an Oklahoma
state pension under the 1915 act. The canonical input record
from `digitalprairie/ok_pensioners.json`. Each pensioner has a
`pensioner_id` (stable across runs) plus name, unit, and metadata.
_Avoid_: applicant, claimant, file (the file is the source
artifact, not the person).

**Candidate**:
A FaG memorial page returned by the search harness for a given
pensioner. Each candidate has a `memorial_id`, `slug`, `name`,
`score`, and `match_strength`. Multiple candidates may be
returned for one pensioner; the goal is to find the *right* one.
_Avoid_: result, match (a match is the decision, a candidate is
the data).

**Match**:
The decision that a candidate is the same person as the pensioner.
A match has `match_strength` ∈ {`high`, `medium`, `low`} and is
made either by the auto-accept threshold (score ≥ 0.85) or by
human review in `view.html`.
_Avoid_: pair (a pair is the (soldier, widow) concept from
spouse cross-ref, not a candidate ↔ pensioner decision).

**Slug**:
The hyphenated trailing component of a FaG memorial URL:
`findagrave.com/memorial/<id>/<slug>`. Most slugs are
`first_middle-last` (~82% of the local 575 set), not
`first_last`. Sending only first + last to the search misses
the middle component entirely.
_Avoid_: name component, URL tail.

**Outcome**:
The categorical result of a single pensioner's search run.
Enum: `BOTH_MATCH` (FaG + CGR corroboration), `auto_accept`
(score ≥ 0.85, no review needed), `too_many` (>20 candidates,
human review), `ambiguous` (top 2 candidates within 0.05 score),
`no_results`, `error`.
_Avoid_: result, status (the harness has multiple status fields
— `outcome` is one of them, distinct from `decided`).

**Throttle**:
The minimum delay between consecutive FaG requests. Default
2.5s. The throttle is the only thing between the run and a
30-minute Cloudflare backoff. Never bypass it.
_Avoid_: rate limit (the throttle enforces a rate limit; the
terms are not interchangeable — the throttle is the *mechanism*,
the rate limit is the *constraint*).

**State file**:
The `state.jsonl` file written by the Python harness and read
by `view.html`. One JSON object per line, flushed per-pensioner.
Resume-safe by design — re-running with the same `--state`
path skips already-done pensioners.
_Avoid_: log (the log is `run.log`; the state file is the
structured per-pensioner record).

**Ranked candidate**:
A candidate with a computed score in [0, 1]. Score combines
name match (Double Metaphone + Jaro-Winkler + Damerau-
Levenshtein), state match, death-year match, and OK-burial
match. Auto-accept threshold is 0.85.
_Avoid_: scored candidate (the candidate is always ranked; the
attribute is `score`, not `ranked`).

**Strategy**:
One query shape in the v5 strategy ladder. There are 13
strategies in execution order, from "exact sniper" (Strategy
1, name-only, no metadata) through "broadened surname" (the
fallback). See [`docs/v5-design/strategy-ladder.md`](docs/v5-design/strategy-ladder.md).
_Avoid_: step, query (a strategy is the conceptual shape; a
query is the URL instance).

**Pension card**:
The source artifact on digitalprairie.ok.gov. Has both the
soldier's name and (if the applicant is a widow) the widow's
name, plus regiment/company metadata. The ok_pensioners.json
record combines the application file with the pension card.
_Avoid_: index card (the pension card is the *front*; the
application file is the *back*).

## Relationships

- A **Pensioner** has zero or one **Match** (per FaG candidate).
- A **Pensioner** has zero or more **Candidates** (FaG search results).
- A **Candidate** is a **Ranked candidate** iff it has a `score`.
- A **Pensioner** has one **Outcome** (the harness's verdict).
- A **Pension card** has zero or one **Spouse cross-reference**
  (planned future work; see
  [`docs/learnings/future-work.md`](docs/learnings/future-work.md) §1).
- A **Slug** has one of four shapes (1-part, 2-part, 3-part,
  hyphenated); the `first_middle-last` shape is the canonical
  3-part form.
- The **State file** has one record per **Pensioner**.

## Example dialogue

> "Run #2 hit 1,000 records before the Playwright memory leak
> wedged the browser. The `view.html` reload showed the
> already-flushed records but the harness was still hung. I
> added the `gc.collect()` + locator cleanup, and Run #3 hit
> 4,000 records before the next leak."

> "The slug for William Pickney Looney is
> `william_pickney-looney` — three parts. Sending only
> `Looney, William` misses the middle. That's why Strategy 2
> (middlename-initial fuzzy) recovers 24 of the 41 exact-sniper
> failures."

> "The pension card has both the soldier's name and the widow's
> name on the same line. When we cross-reference FaG's spouse
> section against the pension card's widow name, we get a
> near-perfect match."

## Historical

- **`memorials_archive.json`** — original schema (v1.0), flat
  array of memorial objects. Renamed conceptually to **state
  file** when we introduced `state.jsonl` (one object per line,
  per-pensioner) for resume-safety. The terms are not
  interchangeable; the state file has `pensioner_id` and
  `outcome`, the legacy export has `memorial_id` and no outcome.
- **`ok_pensioners.json`** — canonical OK CW pensioner list
  (~7,758 records after merging the pensions + pensioncard
  collections on `application_number`). File renamed **twice**:
  first called `ok_pensioners.json`, then `unified.json` when the
  pipeline merged the two collections into one canonical list
  (this rename made the source ambiguous: OK-only, but no
  obvious name), then renamed **back** to `ok_pensioners.json`
  in T015 (2026-07-16) with a sibling `ok_pensioners.meta.json`
  carrying the provenance block (source URL, collection, pulled
  date, record count). Legacy references to `unified.json`
  remain in older run logs and design docs as historical
  breadcrumbs.
- **`findagrave-params/bio="..."`** — early v4.0 helper used
  Boolean operators in the bio field. FaG doesn't support them;
  the helper was rewritten to use a single narrowing term.

## Adding features

See [`docs/agents/feature-protocol.md`](docs/agents/feature-protocol.md)
for the canonical procedure.

## Laws (non-negotiable)

These are earned-by-real-bug laws. Each one cites the run that
earned it. **Treat any code that violates a law as a bug that
must be fixed before the change can ship.**

### L1. Throttle is the rate limit (Playwright)

FaG's Cloudflare Turnstile detects request rates > 1 req/sec
sustained. The `--throttle` flag (default 2.5s) is the only
thing between the run and a 30-minute backoff. Never bypass
it for "speed" — the speed-up is zero (the backoff dwarfs the
saved throttle time) and the cost is a wedged run.

**Earned by:** Run #1 (2026-07-16, see
[`docs/learnings/2026-07-16-run-1-learnings.md`](docs/learnings/2026-07-16-run-1-learnings.md)).

### L2. Browser reset on closed-target (Playwright)

Playwright's "Target page, context or browser has been closed"
error means the connection objects are stale. The harness must
reopen browser → context → page, drop refs to None, then
`gc.collect()` before the next request. Partial reset (only
closing Browser) leaks Context + Page refs and grows RSS
unboundedly.

**Earned by:** Run #2 (2026-07-16, see
[`docs/learnings/2026-07-16-run-2-learnings.md`](docs/learnings/2026-07-16-run-2-learnings.md)).

### L3. Resume-safe state writes (Python)

Every per-pensioner record flushes to `state.jsonl` BEFORE the
next pensioner starts (`f.flush(); os.fsync(f.fileno())`). A
crash mid-run leaves the file reloadable by re-running with
the same `--state` path.

**Earned by:** Run #1 mid-run crash (2026-07-16) lost ~40
records before the flush+fsync discipline was added.

### L4. Stable JSON key order in `state.jsonl`

`view.html` assumes a stable JSON key order across reads.
Adding/renaming keys requires coordinated changes in both
the Python writer and `view.html` reader. Tests:
`tests/test_view_html.py`, `tests/test_view_unified.py`.

**Earned by:** Phase 2 → Phase 3 transition (2026-07-15) when
`view.html` was updated to show `ranked_candidates` but the
harness hadn't yet emitted the field.

### L5. One line per pensioner in `state.jsonl`

The file is newline-delimited JSON, NOT a JSON array. The
flush-per-pensioner discipline depends on this. Don't wrap
the output in `[...]`; don't pretty-print.

**Earned by:** Run #1 mid-run crash — pretty-printed output
broke the reload (the parser split on `},` not `\n`).

### L6. Userscript edits are user-facing

A change to `FindaGraveScraper.user.js` is a change to a file
the user runs in their browser. The diff lands in their
Tampermonkey editor; an uninstall + reinstall is the "deploy".
The regression net is the `tests/` Python suite (which loads
the JSON export of the userscript + simulates the pipeline).

**Earned by:** (general) — script distribution hazard.

### L7. Doc comments on exported Python functions

Every public function in `scripts/` carries a docstring that
starts with the function name, names the contract, and states
the failure modes. `_probe_*.py` scripts are exempt (one-off
investigations).

**Earned by:** (general) — same justification as Go's
doc-comment law. The Python harness has 50+ public functions;
re-discovering the contract each session is wasted effort.

### L8. FaG requests go through Playwright + stealth, never `requests`

Plain `requests.get()` returns 200 OK but the body is the
Cloudflare Turnstile challenge page. The script thinks the
search succeeded. Use Playwright + `playwright-stealth` with
`headless=False` and the warmup dance.

**Earned by:** Phase 1 research, 2026-07-08. Cited again in
Run #1 when a one-off `requests` test for "speed" got blocked
in 5 seconds.