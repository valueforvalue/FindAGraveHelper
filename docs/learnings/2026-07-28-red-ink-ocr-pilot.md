# Learning: Red-ink OCR death-date extraction — pilot on 50 cards

> **Earned by:** Developer request to extract death dates from the
> red-ink stamps on Oklahoma Confederate pension cards. The OCR
> layer that produced `ok_pensioners.json` was suspected of having
> missed the red ink. Pilot scope: 50 cards (95 page-sides
> including two-sided postcards). Result: red-ink hypothesis
> partially confirmed; full-image OCR turned out to do most of
> the work; 91.7% per-card candidate rate achieved at ~77%
> precision.

## TL;DR

- **Death date is NOT in the source JSON.** Confirmed in
  `ok_pensioners.json` and friends — fields are limited to
  `name_*, application_number, pension_number, company, regiment,
  date` (the last is publication date, not death).
- **Death info IS recoverable from the cards.** Three sources on
  each card, in priority order:
  1. **Red-ink stamp** at top right: "Deceased, M-D-YYYY" or
     "DECEASED Month D, YYYY". This is what the original OCR missed.
  2. **Typewritten body text** (black ink): sentences like
     "…died Sept. 10, 1896 near Webbers Falls, Ind. Ter."
  3. **Other stamps**: "GRANTED OCT 7-1915", "FILED M/D/YY",
     rejection marks. These are NOT death dates.
- **Pilot succeeded.** 44 of 48 unique cards yielded a candidate
  date string (91.7%). Of those, ~34 look like true death dates
  after filtering obvious false positives (war-end 1865,
  pension-grant 1915, "came to territory" years). Precision
  estimate: ~77%.

## Why the full-image OCR outperformed red-only

The pilot was set up to isolate the red channel and OCR that.
That worked on cards where the red stamp is bold and clean
(7 of 68 candidate results). On most cards, however, the red
ink is faint/thin and Tesseract returns gibberish even after a
clean mask.

What we hadn't anticipated: the cards already contain death
information in the typewritten black-ink narrative ("…died
Sept. 10, 1896…"). The full-image OCR pulls that out reliably.
So full-fallback dominates the candidate count (61 of 68).

**Implication:** Scaling to 7709 cards doesn't strictly need
the red-mask step. Full-image OCR + death-keyword filtering
gets us ~90% of the value at less compute cost.

## Implementation

Two scripts under `scripts/ingest/`:

1. `download_pensioncard_images.py` — Phase 1. Resolves each
   `pensioncard_id` to its actual IIIF page IDs via the
   Digital Prairie singleitem API, then downloads tiles to
   `data/pilot/img/<pcid>__<page_id>.jpg`. Throttle 1.25s.
   Took 4 min 43s for 95 page-sides (no failures).

2. `red_ink_ocr_pilot.py` — Phase 2. For each image:
   - Mask red: keep pixel iff `R > G + B AND R > 100`.
   - Tesseract pass A on red-masked image.
   - Tesseract pass B on full image only if A yielded nothing.
   - Parse text for `deceased|died|death` + date regex.
   - Prefer the candidate closest to a death keyword.

Outputs: `data/pilot/red_ocr_results.json` (per-image),
`data/pilot/red_ocr_summary.json` (aggregate),
`data/pilot/card_level_summary.json` (deduped per-card).

## Bugs found while building this

### `pensioncard_iiif_url` points at compound IDs, not pages

The `pensioncard_iiif_url` field in `ok_pensioners.json` is
`https://digitalprairie.ok.gov/iiif/2/pensioncard:{pcid}/full/full/0/default.jpg`
where `{pcid}` is the parent item ID. For two-sided cards
(postcards), Cantaloupe returns HTTP 501 — the parent ID is a
compound object with no single image. The actual pages live at
`pensioncard:{pageptr}` where `pageptr` comes from
`objectInfo.page[*].pageptr` in the singleitem API.

The first run with the naive URL got 1/50 (only pcid=98 was a
single-page card that rendered directly). After switching to
the API resolution path, 95/95 succeeded.

This same bug appears to affect `fetch_pensioncard_pages.py`
already in the repo — see the comment about a "historical bug"
where the old version returned `[]` for single-page items.
The reverse (compound items with broken direct URLs) is the
mirror image and not yet handled anywhere.

### Red-mask overflow on uint8

A first cut of `build_red_mask` did `r > g + b` with raw uint8
arithmetic. Because `g + b` overflows above 255, the cream
background `[255, 242, 209]` was incorrectly classified as
"red" (96% of pixels passed the test). Cast to `int32` first;
then 0.66% of pixels pass, all of them actual red ink.

### Card has two sides, one date per side

Two-sided cards (45 of 50 sample) yield two page images each.
The back side usually has the typewritten narrative with the
death year embedded in prose; the front side has the red
"Deceased" stamp. We dedupe per `pensioncard_id` and prefer
the candidate whose context window contains a death keyword.

## Pipeline metrics (pilot)

```
total_images:        95
with_red_text:       49    (red mask produced OCR-able text)
with_full_text:      88    (full image produced OCR-able text)
with_death_date:     68    (71.6% per-image)
  from_red_pass:      7
  from_full_fallback: 61
year_in_range:       68    (all 68 are 1865-1940)

unique_cards:        48    (two-sided cards counted once)
cards_with_date:     44    (91.7% per-card — exceeds 70% bar)
plausible:           44/44
precision_estimate:  ~77%  (manual review of 68 contexts)
```

## Go / no-go for full 7709-card run

**Go, with these caveats:**

1. **Full-image OCR is the workhorse.** Red-mask is bonus. Build
   the production pipeline around full-image OCR + death-keyword
   proximity scoring. Add red-mask only as a secondary signal
   for cards where full-image OCR found nothing.
2. **Schema for the result:** add a `death_date_iso` field to
   the pensioner JSON. Nullable. Don't replace existing fields.
   Existing schema-touching work should follow `CONTEXT.md`
   rules.
3. **Throttle 1.25s works** for Digital Prairie IIIF tiles.
   No 501/429/rate-limit evidence. 7709 cards × ~2 pages × 1.25s
   ≈ 5.3 hours of network time. OCR compute on top.
4. **Run on full set after pilot review.** Don't try to fix
   precision in pilot phase — the gap (77% → target 90%) is
   small and probably needs regex tuning against a bigger
   sample.

**Known precision gaps:**

- **War-end false positives**: "May 4, 1865" / "April 10, 1865"
  are parole/surrender dates, not death dates. The narrative
  contains them because it's a service-history summary. Filter:
  if year < 1870 AND no death keyword within 30 chars, drop.
- **Pension-grant false positives**: "OCT 7-1915" / "1915" appears
  on ~10 cards. Filter: if context window contains "GRANTED"
  or "FILED" or "OCT 7", drop the candidate unless death keyword
  is also present.
- **"Came to territory" false positives**: "came to Oklahoma
  Territory 1895". Filter: if context window starts with "came
  to", drop.

These three filters should lift precision from ~77% to ~90%+.

## Files added

- `scripts/ingest/download_pensioncard_images.py`
- `scripts/ingest/red_ink_ocr_pilot.py`
- `data/pilot/img/` (95 JPEGs, 47 MB)
- `data/pilot/red_ocr_results.json`
- `data/pilot/red_ocr_summary.json`
- `data/pilot/card_level_summary.json`
- `data/pilot/download_summary.json`

## Suggested next steps

1. Apply the three precision filters above and re-run the
   `data/pilot` artifact to confirm ≥90% precision.
2. If confirmed, build production version of both scripts
   pointed at the full `ok_pensioners.json` (7709 rows).
3. Decide whether to write back to `ok_pensioners.json` (add
   `death_date_iso` field) or to a separate sidecar.
4. If writing back: update `CONTEXT.md` glossary + add ADR
   under `docs/agents/adr/`.