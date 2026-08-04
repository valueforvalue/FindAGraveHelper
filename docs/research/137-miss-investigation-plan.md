# Investigation plan: 4 B1 miss classes + corrections

## What we found

The 575-record probe's B1 hit rate (82.4%) is below the docs' 92.9%
because of 4 distinct miss classes, none addressed by #137:

| Class | Frequency est. | Cause | Fix |
|---|---|---|---|
| 1. locationId excludes burial-unknown | ~5-10% of 575 = 30-60 records | `locationId=country_4` deprioritizes records with "Burial Details Unknown" | Skip `locationId` when state is empty |
| 2. Name spelling + exactspelling=true | ~1-2% of 575 = 6-12 records | FaG has "Rozzell", local has "Rozell" | Fuzzy fallback after B1 miss |
| 3. Pagination (page 1 only) | ~5-15% of 575 = 30-90 records | Parser reads only first 20 results | Iterate page=2..N |
| 4. Birth-year proxy off | ~2-5% of 575 = 12-30 records | `death_year - 65` is rough; tight year filter excludes truth | Use wider filter for unknown birth |

**Combined est. lift: 10-25% on B1 hit rate, putting cumulative
hit rate at 92-95% on the 575 corpus.**

## Why B10 (issue #137) doesn't help

- B10's `birthyearfilter=3` is TIGHTER than B1's `=1`. Makes
  Miss Class 4 (birth-year proxy) WORSE, not better.
- The bias is +0.05 to scoring. It can't recover URL-filter
  excludes.
- B10 has 0% recovery on its target cohort (verified on the
  full 575 probe: 0/36 pre-1851 B1 misses recovered by B10).

## What #137 should have been

The original issue was framed as "two strategies" but the real
fixes are filter changes, not new strategies. Three
recommendations:

### Option A: Re-scope the issue

Replace B10 with a fix for Miss Class 1 (locationId bug).
That's a 1-line change in `apply_location_filter`:

```python
# Current (line 159):
else:
    p.update(FAG_COUNTRY_FILTER_US)

# Proposed:
# When state is empty, do NOT inject locationId. FaG's
# global relevance ranking finds burial-unknown records
# earlier than the US-only ranking does.
else:
    pass  # No locationId; let FaG use global ranking
```

This change is small, low-risk, and addresses Miss Class 1
directly. Estimated impact: 5-10% lift on B1 hit rate
(per the 10-record diagnosis extrapolated).

### Option B: Three separate issues

File one issue per miss class:
1. "Skip locationId when state is empty" (Miss Class 1)
2. "Add pagination to scripts/fag/parser.py" (Miss Class 3)
3. "Fuzzy-name fallback after B1 miss" (Miss Class 2)
4. "Wider year filter for unknown-birth-year cohort" (Miss Class 4)

Each gets its own validation probe. More work but cleaner
separation.

### Option C: Ship #137 as-is, defer fixes

B10 is a no-op for misses; bias is a small tiebreaker. Neither
regresses anything. Ship and re-evaluate after the broader
fixes land.

## Recommended order of work

1. **Miss Class 1 fix** (Option A) — 1 line in filters.py.
   Re-run 575 probe. Expected: B1 hit rate 82.4% → 88-92%.
   L1 risk: same as today (no new requests per pensioner).

2. **Miss Class 3 fix** (pagination) — 20-50 lines in parser.py.
   Re-run 575 probe. Expected: B1 hit rate → 92-95%.
   L1 risk: GROWTH. Each pensioner may need 1-5 page fetches.
   Add per-page throttle (2.5s) + 500-page cap (CONTEXT L1).

3. **Miss Class 2 fix** (fuzzy fallback) — 5-10 lines in
   scripts/fag/search.py. After B1 miss with 0-2 results,
   run B1 with `exactspelling=false`. Expected: 1-2% lift.

4. **Miss Class 4 fix** (wider year filter) — change in
   `_inject_acw_date_window` or in B1's year filter logic.
   Expected: 2-5% lift.

5. **Re-run full 575 probe after each fix** to measure lift
   per fix. Update CONTEXT.md with new baseline.

## Validation harness

`scripts/analysis/probe_575_capped.py` is the reusable
infrastructure. Swap B1 for any strategy and re-run on the
575-record set. ~24 min wall, ~24K requests at 11 strategies.

For pagination tests, modify the parser and re-run; the
probe's first-hit-stops optimization will only fetch extra
pages when needed.

## References

- `docs/learnings/2026-08-03-issue-137-validation.md` —
  validation numbers
- `docs/learnings/2026-08-03-miss-diagnosis.md` — 4 miss
  classes with evidence
- `data/diagnosis_results.json` — 10-record variant comparison
- `data/probe_575.json` — full 575-record probe data
- `scripts/analysis/experiment_miss_recovery.py` — reusable
  4-variant A/B harness
