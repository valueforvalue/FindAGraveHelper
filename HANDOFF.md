# Handoff — Issue #137 investigation (2026-08-03/04)

**TL;DR:** B10 + bias shipped in `bcce40f`, but post-merge validation
on the full 575-record corpus showed the original issue's framing was
wrong. Neither change addresses the 4 real B1 miss sources. **The
state filter is a precision tool** (per operator's correction);
lifting it globally hurts precision. **The real fixes** are 4
follow-up issues (#146–#149).

---

## What's open

### B10-pre1851-tight (shipped, ineffective)

- **What it does:** Function-form strategy in
  `scripts/search/strategies.py`. Fires only when
  `pensioner.birth_year < 1851`. Uses `birthyearfilter=3` (tighter
  than B1's `=1`).
- **Ladder position:** After B5, before C1. Per issue acceptance
  criteria.
- **Reality:** **0% miss recovery on its target cohort.** Verified
  on the 575-record probe: 0/36 pre-1851 B1 misses recovered by
  B10. The strategy is correct in *guard logic* (fires for pre-1851,
  skips for 1851+), but the URL is wrong for the goal: tighter
  filter on a miss excludes more, not fewer.
- **Should we revert?** Cost is +1 strategy fetch per pre-1851
  pensioner per run. L1 budget impact is small. **Keep for now** —
  it's a precision refinement on hits, not a miss-catcher. Can be
  reverted if L1 budget tightens.

### State bias (shipped, effective as designed)

- **What it does:** `scripts/fag/scoring.py` adds +0.05 to a
  candidate's score when BOTH `pensioner.state` and
  `candidate.burial_state` are empty. Surfaces as
  `state_bias: 0.05` in the score breakdown.
- **Reality:** Fires on 44/575 top-1 candidates (7.6%). Sized small
  to break ties without overpowering name/death evidence. No
  measured regression. Working as designed.
- **Should we revert?** No — it's harmless and the design is
  correct for the rare unknown-state-AND-unknown-burial case.

## What was reverted

### `apply_location_filter` "skip when empty" attempt (commit `c0ad35e`)

- **What it did:** When `state_abbr == ""`, did NOT inject
  `locationId=country_4`. Theory: FaG's global ranking outperforms
  the US-only ranking for burial-unknown records.
- **Verified on memorial 285269207** (John Pate, Texas death,
  "Burial Details Unknown"): 486 US-only results push truth out of
  top 20; 1,182 global results keep it at rank ~9.
- **Reverted because:** In production, the operator confirmed
  **the state filter is a precision tool** — it cuts noise from
  foreign same-name candidates. Lifting it globally recovers
  0.2% of records (negligible) while losing precision in the
  common case. The diagnosis was right that the filter is
  harmful for burial-unknown records; the fix isn't to remove
  the filter globally but to add a targeted recovery path (a
  separate issue, see #148 fuzzy fallback).

## The 4 real miss classes (diagnosis results)

Source: `docs/learnings/2026-08-03-miss-diagnosis.md`. Method:
`scripts/analysis/experiment_miss_recovery.py` (4-variant URL
A/B harness).

| # | Class | Cause | Est. lift | Fix | Issue |
|---|---|---|---|---|---|
| 1 | locationId excludes burial-unknown | `locationId=country_4` deprioritizes "Burial Details Unknown" | 1-3% | Add targeted no-filter retry when results <3 | (none yet — fold into #148) |
| 2 | Name spelling + `exactspelling=true` | "Rozell" ≠ "Rozzell" | 1-2% | Fuzzy fallback after B1 miss | **#148** |
| 3 | Pagination — parser reads only page 1 | 20 results per page; truth on page 2+ | 5-15% | Iterate `page=2..N` in parser | **#147** |
| 4 | Birth-year proxy off | `death_year - 65` is rough; tight filter excludes truth | 2-5% | Wider year filter for unknown-birth | **#149** |

**Combined est. lift: 10-25%** on B1 hit rate (82.4% → 92-95%).

## Follow-up issues

| # | Title | Status | Priority |
|---|---|---|---|
| **#146** | Parallel FaG search via proxy pool | Filed | High — L1 throttle is the dominant cost; 4.4h probe becomes 30 min on 4-proxies |
| **#147** | Pagination in `scripts/fag/parser.py` | Filed | High — biggest single miss-class (5-15% lift) |
| **#148** | Fuzzy-name fallback after B1 exactspelling miss | Filed | Medium — 1-2% lift, low effort |
| **#149** | Wider year filter for unknown-birth cohort | Filed | Medium — 2-5% lift |

## Recommended work order

1. **#146 (parallel/proxy)** — speeds up everything else. 30 min
   probe → 4.4h probe becomes practical.
2. **#147 (pagination)** — biggest miss-class fix, low risk.
   Validate with 575 probe after #146 lands.
3. **#148 + #149** — small, independent. Implement + validate
   together if possible.
4. Re-run the full 575 probe after each fix; update
   `docs/learnings/` with per-fix lift.

## Validation infrastructure (reusable)

- `scripts/analysis/probe_575_capped.py` — 11 strategies × 575
  records, first-hit-stops optimization. ~24 min wall, ~3K
  fetches. B1 + targeted fallback. Set `--input` to use a
  pre-built JSON.
- `scripts/analysis/probe_575_no_state.py` — same but always
  empty state (no locationId at all). Useful for the
  precision-vs-recall tradeoff.
- `scripts/analysis/experiment_miss_recovery.py` — 4-variant
  URL A/B harness. The template for any future URL investigation.
- `scripts/analysis/validate_strategy_urls.py` — URL-shape
  smoke test for all 11 strategies × 20 records. ~9 min wall.
  Re-run after any strategy change.
- `scripts/analysis/build_575_probe_input.py` — builds the
  input JSON for the probes.
- `scripts/analysis/probe_mid_sample.py` — picks a 5-record
  mid-set sample for quick smoke tests.

## Data files (preserved)

- `data/probe_575.json` — original 575 probe (v1, broken state
  extraction, mostly empty state)
- `data/probe_575_v2.json` — v2: skip-when-empty change (no
  locationId for empty state)
- `data/probe_575_v3.json` — v3: state=OK for all OK pensioners
  (production-equivalent, but with the skip-when-empty change)
- `data/probe_575_no_state.json` — v4: no locationId at all
- `data/strategy_url_validation.json` — 11 strategies × 20 records
- `data/diagnosis_results.json` — 4-variant A/B for 10 B1 misses
- `data/probe_input_575.json` — input used for v1 probe
- `data/probe_input_mid5.json` — input used for mid-sample smoke

## Documentation (preserved)

- `docs/learnings/2026-08-03-issue-137-validation.md` —
  initial 575 probe numbers, recommendation
- `docs/learnings/2026-08-03-miss-diagnosis.md` — 4 miss
  classes with evidence (memorial 285269207 verified)
- `docs/research/137-miss-investigation-plan.md` — full
  investigation plan + per-fix impact estimates
- `CHANGELOG.md` `[Unreleased]` — both shipped (B10 + bias)
  and follow-up diagnosis documented

## Test suite state

- **1,704 passed, 6 deselected, 0 failed** (last run: 2026-08-04)
- New tests added: `test_state_bias_137.py` (8 tests for the bias
  trigger matrix), `test_strategies.py` (9 B10 tests),
  `test_fag_engine.py` (ladder count 13→14)
- All L1/L2/L8/L9/L11/L12 invariants honored in the probe
  scripts (throttle 2.5s, full browser reset on errors, Playwright
  + stealth, no `requests.get()`)

## What I did NOT do (be aware)

- **Did not run the full 11-strategy ladder on 575 records.**
  That's a 4.4h probe. Deferred to a follow-up because of L1
  risk (4.4h sustained iteration is a Cloudflare magnet).
  Issue #146 (parallel) makes this practical.
- **Did not implement any of the 4 follow-up fixes.** Filed as
  issues #146–#149 with clear acceptance criteria.
- **Did not validate #146's proxy pool design** beyond the L1
  reasoning. Real proxy source, cost, and Cloudflare-detection
  thresholds need empirical testing.
- **Did not promote the diagnosis to a design doc.** Kept as a
  learnings doc + investigation plan. If/when a fix lands,
  promote to a permanent design doc.

## Quick state for the next session

1. Read this file + `docs/learnings/2026-08-03-miss-diagnosis.md`
2. Check open issues: `gh issue list --repo valueforvalue/FindAGraveHelper --state open`
3. Pick a follow-up: #146 (parallel), #147 (pagination), #148
   (fuzzy), #149 (year)
4. Use the probe infrastructure above to validate each fix
5. Update `CHANGELOG.md` `[Unreleased]` block with each landed fix

## Operator's correction (in this session)

> "We need to be careful about this because a global search will
> be noisy and likely have a lot of false positives which is why
> we search OK first or neighbor states like TX and ARkansas"

**Lesson:** Don't propose "remove the filter" as a fix for
recall misses. The state filter is a precision tool; the
operator accepts some recall loss for the precision gain. The
right fix for Miss Class 1 is a *targeted* no-filter retry
when the regular search returns 0-2 candidates, not a global
removal of the filter.

## Contacts / references

- Original issue: #137 (closed with diagnosis comment)
- Follow-up issues: #146, #147, #148, #149
- Domain docs: `CONTEXT.md` (laws L1-L12), `docs/agents/`
- Pipeline architecture: `docs/agents/pipeline-architecture.md`
- Search abstraction: `docs/agents/search-abstraction.md`
