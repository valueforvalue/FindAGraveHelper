# 2026-07-31 — Issue #138: Death-year-aware scoring slice

Spun out of issue #138 (parent ticket for the red-ink OCR pipeline).
The L0–L4 OCR work landed in #139 (commit `c96c7f4`); this slice
implements the death-year-aware **scoring** half the issue
promised.

## What was already in place

`scripts/fag/scoring.py:score_candidate` already had:

- 3-tier death-year proximity bonus: `diff==0: 0.5`, `diff<=2: 0.4`,
  `diff<=5: 0.2`. Anything beyond 5 years gave 0.0 death_score.
- Soft ACW date gate (J13): candidates outside the ACW window
  (born after 1880 or died after 1955) get a 0.3× penalty
  multiplier on the entire score, so they still sort below
  in-window candidates but above parser noise.
- Widow era widener: on widow cards, the candidate's death
  year can be up to 1980 (WIDOW_DEATH_YEAR_MAX) before the
  ACW gate rejects them.

`scripts/blackboard/decision_policy.py:classify` already used
`local_death_year` to choose a threshold: lower threshold
(0.70 vs 0.85) when no death year is available, because the
score is naturally lower.

## What was missing

The issue's three claims were not fully met:

1. **Date-window narrowing** (issue point 1): no penalty for
   candidates whose death year is *near* the pensioner's but
   not exact. A candidate 20 years off scored 0.0 in the
   death component — same as a candidate 200 years off. The
   3-tier bonus dropped off a cliff.
2. **Death-year proximity bonus** (issue point 2): only 3 tiers.
   The issue asked for ±5, ±10, ±20 tiers. Adding them gives
   smooth decay and helps the scorer distinguish era-appropriate
   candidates from modern namesakes.
3. **Widow-specific matching** (issue point 3): the existing
   `if is_widow and cand_dy` branch only fired when `local_dy`
   was **not** set. On widow cards where the OCR pipeline
   extracted the soldier's death year, the standard proximity
   tiers fired, but they treated "died 10y before soldier" and
   "died 45y after soldier" as equivalent — both are diff > 5
   and get 0.0. The widow branch never ran, so the asymmetry
   (widow must die AFTER soldier) was never encoded.

## The fix

**`scripts/fag/scoring.py`** — extended the `local_dy and cand_dy`
branch:

- Added two new tiers: `diff <= 10 -> 0.1`, `diff <= 20 -> 0.05`.
- Added a widow-specific override when `is_widow`:
  - `gap_after < 0` (candidate died BEFORE soldier) → `death_score = 0`
  - `0 <= gap_after <= 5` → `max(0.45)`
  - `5 < gap_after <= 15` → `max(0.35)`
  - `15 < gap_after <= 40` → `max(0.25)`
  - `40 < gap_after <= 60` → `max(0.15)`
  - Uses `max(..., tier)` so the override can only INCREASE the
    death_score, never decrease. The non-widow tiers (which treat
    diff symmetrically) still apply if they give a higher score.

The widow tiers are **directional** (gap_after, not abs(diff))
because the candidate IS the widow; she can't have died before
her husband. A candidate 10 years before the soldier is the
wrong person (different person, same name); a candidate 30
years after the soldier is plausibly the widow.

The J13 ACW soft gate still applies unchanged — the new tiers
compose with the existing `_in_acw_window` filter.

## Tests added

`tests/test_date_filter_j13.py`:

- `test_death_year_window_penalises_far_off_candidates`: a
  candidate 40y off should score < 0.3 (heavy penalty).
- `test_death_year_window_proximity_bonus_tiers`: scores must
  monotonically decrease across `0y, 2y, 5y, 10y, 20y, 40y`
  distances.
- `test_death_year_window_handles_missing_cand_year`: missing
  candidate death year is not penalised (preserves name-match
  signal).
- `test_death_year_window_skipped_for_widows`: widow with
  death 45y after soldier beats widow with death 10y before.
- `test_death_year_window_respects_acw_soft_gate`: J13
  regression — out-of-ACW-window candidate still gets
  `_date_penalty` flag.
- `test_issue_138_realistic_pick`: 4-way contest (1920 vs 1925
  vs 1940 vs 1980); 1920 candidate should win by >0.1 over
  the 1940 modern namesake.
- `test_issue_138_widow_pick_against_pretender`: widow died
  1935 (45y after soldier 1893) beats pretender died 1880
  (10y before).

## What was NOT done (out of this slice)

- **CalibrateClassifier retrain**: `scripts/learning/train.py`
  would need to be re-run on a labeled benchmark with the new
  scores to re-fit the threshold. Out of scope for the narrow
  slice; the thresholds remain as-is.
- **Bulk re-search of all 7709 pensioners**: requires running
  the FaG searcher for hours. The scoring fix is in place; the
  re-search is a separate operational step.
- **`docs/agents/` documentation**: not added. The issue asks
  for it; this is a quick doc note. Will land in a follow-up.
- **Strategy ladder changes** (#137): the new tiers are
  scoring-only; they don't change which plans the searcher
  emits. The strategy layer is #137's territory.
- **The issue's "+0.20-0.25 top-1 improvement" claim**: this
  slice adds the scoring signals. A real benchmark on
  `tests/fixtures/ground_truth.csv` (240 rows) would quantify
  the improvement. Run with:
  `python scripts/run_e2e_benchmark.py` (TODO: not yet written).

## Suite

1674 → 1681 passed (+7 new tests), 0 failed, 0 skipped.
6 diag tests deselected as before.
