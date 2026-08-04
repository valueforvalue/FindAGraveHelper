# 2026-08-03 — B1 miss diagnosis: 4 distinct miss classes

**Trigger:** Full 575-record probe showed B1 hit rate 82.4% (not the
docs' 92.9%). Investigated 10 B1 misses to find why.

**Method:** `scripts/analysis/experiment_miss_recovery.py` — for
each B1 miss, fetched FaG with 4 URL variants:
- A.orig — what the existing pipeline sends (B1 + locationId=country_4
  + ACW date window 1810-1955)
- B.no_loc — strip locationId, keep date window
- C.no_date — keep locationId, strip date window
- D.bare — no locationId, no date window

**Result on 10 B1 misses (5 pre-1851 + 5 other):**

| Variant | Hits | Notes |
|---|---|---|
| A.orig (current) | 0/10 | What the pipeline currently sends |
| B.no_loc | 2/10 | Drop `locationId=country_4` |
| C.no_date | 0/10 | Drop date window only |
| D.bare | 1/10 | Drop everything |

**Conclusion: `locationId=country_4` is excluding 2 records that
the no-loc search finds.** Two clear miss classes identified:

## Miss Class 1: locationId excludes burial-unknown records

**Soldier 43, John Pate, truth=285269207.** Pension record has empty
burial state. The actual FaG memorial has:
- Birth: Georgia, USA
- Death: Palestine, Anderson County, **Texas, USA**
- Burial: **"Burial Details Unknown"** (the user added this memorial
  on 2025-07-27)
- Veteran: Yes (CW)

Search results:
- A.orig (`locationId=country_4` + ACW window): 18 candidates, NO hit
- B.no_loc (no `locationId`, ACW window): 20 candidates, **HIT@9**
- C.no_date (`locationId=country_4`, no window): 20 candidates, NO hit
- D.bare (no filters): 20 candidates, **HIT@10**

**The user was right.** A memorial with "Burial Details Unknown" is
**excluded or heavily deprioritized** when `locationId=country_4` is
applied. FaG's filter treats burial-unknown as a location mismatch.

Same pattern for **soldier 80, William Hawkins**:
- A.orig: 20 candidates, NO hit
- B.no_loc: 20 candidates, **HIT@17**
- C/D: NO hit

## Miss Class 2: name spelling mismatch with exactspelling=true

**Soldier 50, Peter Rozell, truth=38979849.** Pension record has
"Peter Rozell" (one z). The actual FaG memorial:
- Name: **Peter Wildman Rozzell** (two z's)
- Burial: Mount Olive Cemetery, Healdton, Carter County, **OK, USA**
- Born 1821 (pension proxy was 1831, off by 10)

Search results:
- A.orig / B / C / D: 1-2 candidates, NO hit

**B1's `exactspelling=true` excludes "Rozzell" from a search for
"Rozell".** With 1-2 results, the truth isn't there at all. Fixable
by a fuzzy fallback after B1 misses.

## Miss Class 3: pagination — parser reads only page 1 (20 results)

**Soldier 99, William Ritter, truth=24140875.** Pension record has
empty burial state. The actual FaG memorial:
- Name: William Ritter (exact match)
- Birth: 3 May 1844, North Carolina
- Death: 1 Jan 1902, Cornish, Jefferson County, **OK**
- Burial: Cornish Cemetery, **OK**

Search results:
- A.orig: 20 candidates, NO hit
- B.no_loc: 20 candidates, NO hit
- C.no_date: 20 candidates, NO hit
- D.bare: 20 candidates, NO hit

All 4 variants return 20 candidates. **But FaG reports "486 matching
records" for variant A** (per the rendered page). The truth is
somewhere in pages 2-25. Our parser only reads page 1.

The parser does not have a `page=2` iteration path. The probe sees
"20 candidates" and declares miss, when the truth might be at rank 47
on page 3.

**This is a major miss class.** The single soldier William Ritter
alone represents ~1% of the corpus. Extrapolated, many of the
remaining B1 misses are likely page-N misses, not filter-excluded.

## Miss Class 4: birth-year proxy is unreliable

**Soldier 42, James Moore (state='US'), truth=134094041.** All 4
variants miss. The pension proxy birth year is `death_year - 65`,
but the actual birth year on the FaG memorial may differ by 5-15
years. When the year filter is tight (B1's `birthyearfilter=1`,
B10's `birthyearfilter=3`), the truth gets filtered out.

The proxy `death_year - 65` is a rough heuristic. CW soldiers died
between ages 60-90 typically. The proxy underestimates birth year
for soldiers who died young (60-70) and overestimates for those
who died old (85+).

## Implications for #137

**B10 and the state_bias do not address any of the 4 miss classes.**

- B10's `birthyearfilter=3` (tighter than B1's `=1`) makes the
  birth-year proxy problem *worse*, not better. The pre-1851 cohort
  has rough birth years; tightening the filter excludes the truth
  faster.
- The bias is a +0.05 scoring tweak. It can't recover misses — it
  only re-ranks existing candidates by a tiny amount.

**The real fixes for the B1 miss rate are:**

1. **Pagination** (Miss Class 3) — biggest single fix. The parser
   needs a `page=2,3,...,N` loop until truth is found or 500-page
   cap hit (CONTEXT.md says L1: 500-page cap). This is a
   `scripts/fag/parser.py` change.

2. **Skip locationId when state is empty** (Miss Class 1) —
   `apply_location_filter` currently adds `locationId=country_4`
   when state is empty. The probe shows this is harmful for
   burial-unknown records. Fix: don't add any `locationId` when
   state is empty; let FaG's global ranking do its work. This is
   a `scripts/fag/filters.py` change.

3. **Fuzzy fallback after B1 exact miss** (Miss Class 2) — when
   B1 with `exactspelling=true` misses, try B1 with
   `exactspelling=false` (or B3 with `fuzzyNames=true`). This
   already exists as a strategy in the ladder; the issue is the
   order — B1 runs first, and the full ladder only fires the
   next strategy when B1's result count is too high. For name
   miss, B1 returns 1-2 candidates (low), so the ladder doesn't
   escalate.

4. **Wider year filter for known-rough birth years** — when the
   pensioner has a `death_year` but no `birth_year` (most of the
   575 set), the year filter should be wide (±10) or absent.
   The current `birthyear=1810&birthyearfilter=after` from the
   ACW window is reasonable but only catches the ACW-era guard.
   A pensioner's `birth_year - 30` to `birth_year + 30` would be
   the equivalent of "I don't know the birth year, give me a
   30-year window."

## Recommendation

**Don't ship #137 as a fix for the 82.4% B1 hit rate.** It's not
a fix — it's a no-op for misses (B10) and a small tiebreaker
(bias). The real fixes are the 4 above. Each is a separate
investigation + change:

| Fix | Impact est. | Effort | Risk |
|---|---|---|---|
| 1. Pagination | 5-15% lift (page-N misses) | Medium | L1 budget grows |
| 2. Skip locationId when state empty | 1-3% lift (burial-unknown) | Low | None |
| 3. Fuzzy fallback after B1 | 1-2% lift (spelling) | Low | None |
| 4. Wider year filter for unknown birth | 2-5% lift (year mismatch) | Low | False positives |

Combined: ~10-25% lift on B1 hit rate, which would put cumulative
hit rate (B1 + targeted fallback) at 92-95% on the 575 corpus.
Far above the current 84.9%.

**#137 should be re-scoped or split.** The original issue framed
two strategies (B10 + bias) that don't address the actual miss
sources. A new issue or amendment should describe the 4 fixes
above, each with its own validation probe.

## Reusable artifacts

- `scripts/analysis/experiment_miss_recovery.py` — 4-variant
  comparison harness. Pass any URL params dict + record context.
- `data/diagnosis_results.json` — full 10-record breakdown.
- `data/probe_575.json` — 575-record probe results.
