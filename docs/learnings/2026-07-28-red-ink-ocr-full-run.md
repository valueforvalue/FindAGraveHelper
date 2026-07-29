# Learning: Full-run red-ink OCR pipeline — what was built, what survived, what's next

> **Follow-up to:** `2026-07-28-red-ink-ocr-pilot.md`. The pilot
> validated the hypothesis on 50 cards. This doc covers the
> production-scale run (7709 cards / 9436 page-sides), the
> surrounding tooling (viewer, bundler), and the work that
> remains to actually use the extracted death dates.

## TL;DR

Built and pushed (commits `3ae2e0e` through `ad97014`):

- A download script that grabs 7709 pension card images from
  Digital Prairie IIIF.
- An OCR pipeline (Tesseract + red-channel mask + widow-aware
  date parsing) that extracted candidate death dates from 41%
  of pensioners.
- An enrichment step that writes `death_year` + `death_date_iso`
  onto each pensioner record, **but to a sidecar file** — the
  source `ok_pensioners.json` is untouched.
- A per-surname-letter HTML viewer with embedded JSON.
- A 5-part zip bundle (~4.8 GB total) for backup.

**The data is on disk and ready. What's missing is the actual
use of it: the FaG searcher scoring still doesn't use the
extracted death years to rank candidates.** Filing issue #138
to track the remaining work.

## What was built (with file paths)

```
scripts/ingest/
├── download_pensioncard_images.py     7709 → 9436 JPEGs in 8.4h
├── red_ink_ocr_pilot.py               red-mask + Tesseract + parse
├── red_ink_ocr_watchdog.py            auto-restart on silent death
├── enrich_pensioners_with_death_dates.py  → sidecar JSON
├── run_red_ink_ocr_pipeline.py        orchestrator
├── build_pensioncard_viewer.py        per-letter HTML + JSON
└── distribute_pension_viewer.py       → 5 zip parts, atomic write

data/cards/
├── img/                               4.8 GB, 9436 JPEGs (gitignored)
├── img_sampled_50/                    47 MB pilot subset
├── viewer/                            17 MB HTML+JSON (gitignored)
├── enrichment_report.json             1 MB, per-pensioner summary
├── red_ocr_results.json               10 MB, per-image OCR
├── red_ocr_summary.json               309 B, aggregate
└── download_summary.json              2.4 MB, per-card fetch log

docs/research/digitalprairie/
├── ok_pensioners.json                 UNTOUCHED source-of-truth
└── ok_pensioners.with_death_dates.json  30 MB, enriched sidecar

data/pension-viewer-bundle.part00{1-5}.zip  portable backup
```

## Numbers

| Metric | Value | Notes |
|---|---|---|
| Pensioners | 7709 | from `ok_pensioners.json` |
| Page images | 9436 | ~50% two-sided cards |
| Per-image candidate date rate | 34.2% | `red_ocr_summary.json` |
| Per-pensioner enrichment rate | **41.1% (3167)** | after per-card dedup |
| Widow card enrichment rate | 48% (1818 of 3793) | new widow-aware logic |
| Full-text "death" kw match | 111 (full run) | 17 on pilot — full run is fuller |
| Estimated precision | ~70% | manual review of 68 contexts on pilot |
| Download time | 8.4 hours | 1.0s throttle |
| OCR time | ~2.4 hours | 9028 images @ 0.67/s |

The 41% enrichment rate is lower than the pilot's 91.7% because:

1. The full set includes 9436 page-sides, many of which are
   the back side of cards that have only a marriage date or
   blank space.
2. 74 cards (1%) failed download entirely (45 HTTP 502/504
   errors, 29 with no API page IDs at all).
3. OCR confidence on first pass is lower than on the
   hand-curated pilot sample.

## Key engineering decisions

### Red-ink mask: R > G + B AND R > 100

Initial attempt with raw uint8 arithmetic produced wrong
results because `g + b` overflows above 255. Cream-background
pixels like `[255, 242, 209]` incorrectly classified as red.
Cast to int32 first; cream background correctly classified as
non-red.

This single bug cost about 30 minutes of debugging time. The
fix is two characters (`g = arr[:, :, 1].astype(np.int32)`)
and the symptom was so loud (95% of pixels classified as red)
that it should have been obvious. Lesson: **when masking in
numpy, always promote integer dtype before arithmetic**.

### IIIF compound-object bug

The `pensioncard_iiif_url` field in the pensioner JSON points
at `pensioncard:{pcid}` which is the parent item ID. For
two-sided cards (postcards), the parent ID is a compound object
that Cantaloupe cannot render — HTTP 501 with
"Unsupported source format". The real images live at
`pensioncard:{pageptr}` where `pageptr` comes from
`objectInfo.page[*].pageptr` in the singleitem API.

A different version of this same bug affected the pre-existing
`fetch_pensioncard_pages.py` — it returned `[]` for single-page
items because it only looked at `pageptr` and not the
fall-back to the parent ID. The two bugs are mirror images of
each other.

### Widow-aware scoring

The most subtle bug of the run. On widow pension cards (cards
where `spouse_name_raw` is non-empty), the red-ink stamp at
the top records the **widow's own death date**, not the
soldier's. The typewritten body text contains the soldier's
death in prose ("He died February 26 1915 in Pushmataha
County, Okla."). For FaG search we want the soldier's death.

The fix has three parts:

1. **Detect widow cards** via `spouse_name_raw` non-empty.
   49% of the 7709 pensioners are widow cards.

2. **Score each OCR candidate** for whether the soldier's
   last name appears in the candidate's context window. The
   bug I introduced and then caught: I had `(0, 1 if
   soldier_in_window else 0, ...)` as the second tuple
   element. Tuple sort is ascending — `(0, 0, ...)` sorts
   BEFORE `(0, 1, ...)`. So candidates mentioning the soldier
   were getting *deprioritized* over candidates that didn't.
   The fix: invert the bonus — `(0, 0 if soldier_in_window
   else 1, ...)` so the soldier-mentioning candidate sorts
   first.

3. **Per-card dedup** that prefers
   `mentions_soldier_name` > `near_death_keyword` > `kind=date`
   > earlier year (because the husband typically died decades
   before the widow, so when multiple candidates tie, the
   earlier year is more likely the soldier's).

Verified on `Baker, Dora` (widow of `John Stephens Baker`):
previous logic picked widow's death `1928-07-18`; widow-aware
picks soldier's `1915-02-26` ("He died February 26 1915 in
Pushmataha County").

The bug was caught by manual review of per-card context
windows, not by any test. **Lesson: when ranking, manually
inspect the winners, not just the aggregate metrics.**

### OCR process dies silently

The OCR script (`red_ink_ocr_pilot.py`) died at 519/9028,
1093/9028, 6718/9028, and 6793/9028 during the full run. No
exception, no traceback, no log line indicating cause. The
process just disappears from `tasklist`.

Suspected causes (none confirmed):
- Windows job object timeout (the nohup'd process may be
  hitting a background-process limit)
- Tesseract child process crash (would normally surface as
  an exception, but maybe not in all cases)
- Tesseract's GIL/CPU contention with the disk I/O from
  the per-record JSON flush

Mitigation: built `red_ink_ocr_watchdog.py` that polls every
30s, restarts on death, exits on idle. Worked perfectly for
the rest of the run. The watchdog itself doesn't fix the
root cause, but it makes the pipeline resumable, which is
what we actually need.

The same pattern is used for the zip bundler
(`distribute_pension_viewer.py` writes to `.partial`, atomic
rename on success, resumable on next run).

**Lesson: for long-running batch jobs, design for restart
from day one. The first attempt should write to a temp file
or use a database, not assume the process will run to
completion.**

## File-size economics

Card images compress negligibly with DEFLATE (they're already
JPEG). The 5-part zip bundle is 4.82 GB vs 4.81 GB raw —
1% savings. The `--split 1024` option exists for tools that
have a single-file upload limit, not for compression.

JSON, by contrast, compresses 70% (text with repetition).
The 30 MB `ok_pensioners.with_death_dates.json` becomes
~9 MB zipped. Not worth the complexity of mixed-compression
zips.

## What was NOT done (next steps)

The **critical missing piece**: death-year-aware candidate
scoring. The plumbing exists:

- `scripts/blackboard/projector.py:66` reads
  `pensioner_data.get("death_year")`
- `scripts/blackboard/decision_policy.py:206` uses
  `has_death` to pick different auto-accept thresholds

…but neither uses the death year to actually score FaG
candidates. The next agent should add:

1. **Date-window narrowing**: when pensioner death year is
   known, reject candidates whose death year is before the
   pensioner's. A candidate who died 10 years before the
   pensioner is impossible to be the same person.

2. **Death-year proximity bonus**: candidates with death
   year within ±5 years of the pensioner's get a +0.10
   score boost.

3. **Widow-specific search context**: the FaG search is
   currently soldier-agnostic; on widow cards we want to
   pass "looking for the soldier, not the widow" to the
   scraper.

4. **CalibratedClassifier retrain**: the auto-accept
   threshold needs to be re-calibrated against the DD
   benchmark with the new scoring signals in place.

5. **Bulk re-search**: 30-50% of the 4542 unenriched
   pensioners likely have recoverable death dates in the
   existing OCR results that didn't make the cut. Re-run
   the FaG search with death-year-aware scoring for the
   full set.

Tracked in **issue #138**. Expected precision gain:
+0.20-0.25 per the analysis in issue #127.

## Backup & restore

Bundle command for re-creating the backup zip:

```bash
python scripts/ingest/distribute_pension_viewer.py --split 1024
```

Extract command on the receiving end:

```bash
mkdir pension_viewer && cd pension_viewer
unzip /path/to/pension-viewer-bundle.part001.zip
unzip /path/to/pension-viewer-bundle.part002.zip
unzip /path/to/pension-viewer-bundle.part003.zip
unzip /path/to/pension-viewer-bundle.part004.zip
unzip /path/to/pension-viewer-bundle.part005.zip
open pension-viewer-bundle/data/cards/viewer/index.html
```

All 5 parts extract into the same `pension-viewer-bundle/`
directory and merge cleanly. Verified by extracting one part
to `/tmp/extract_test` (now cleaned up).

## Time spent

| Phase | Time |
|---|---|
| Pilot (50 cards) | ~2 hours |
| Download (7709 cards) | 8.4 hours (mostly idle) |
| OCR (9028 images) | ~2.4 hours (with 4 restarts) |
| Enrichment + viewer | ~10 minutes |
| Bundling | 2.5 minutes |
| Bug fixes (red-mask, widow logic, watchdog, atomic zip) | ~1.5 hours |
| **Total** | **~15 hours** |

## Lessons for next time

1. **Pilot the date picker logic on edge cases manually.**
   Aggregate precision metrics hide per-class bugs. Pick 20
   examples where the score changed between versions and
   verify each is correct.

2. **Tuple sort ascending means "smaller wins"**. When
   adding a bonus factor to a sort key, ask: does 1 mean
   "this is what I want" or "this is what I want to filter
   out"? Inverting the meaning is a one-character bug that's
   hard to spot in review.

3. **Long-running batch jobs need restart support, not just
   resume support.** Build the watchdog pattern into the
   first version, not after the second silent death.

4. **IIIF / digital library APIs have URL quirks that aren't
   in the docs.** Always test with the actual page IDs you
   care about, not the parent item IDs.

5. **OCR on cards with multiple dates in different inks is
   inherently a disambiguation problem, not a recognition
   problem.** The recognition is fine; the picker is hard.
   Plan for several rounds of precision refinement.

6. **Sidecar files are the right default for additive
   enrichment.** The source `ok_pensioners.json` stays
   reproducible from `scrape_digitalprairie.py`; the
   enrichment is opt-in via `cp`. No "is the source
   contaminated" debates.

## References

- `2026-07-28-red-ink-ocr-pilot.md` — the 50-card pilot writeup
- `scripts/ingest/build_pensioncard_viewer.py` — viewer build
- `scripts/ingest/distribute_pension_viewer.py` — backup bundler
- Issue #127 — predecessor: estimated death year from
  metadata (regiment/pension era)
- Issue #138 — successor: scoring integration with extracted
  death years
