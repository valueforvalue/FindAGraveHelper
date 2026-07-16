# Changelog

All notable changes to this project.

## [Unreleased] — 2026-07-16

### Added — Research workspace for v5.0 design

This commit does **not change any userscript behavior**. It documents
research conducted in July 2026 toward a v5.0 rewrite of
`FindaGraveIterativeHelper.user.js`.

- **`docs/research/`** — five research documents:
  - `local-data/` — analysis of 575 CW veterans in the dixiedata DB
    with attached FaG URLs. Found the slug-shape pattern (82% are
    `first_middle-last`), middlename prevalence (25% single-letter,
    90% any middle), and date-coverage distributions.
  - `findagrave-params/` — verified live parameter reference for
    `/memorial/search`. Confirmed `middlename` as a first-class
    narrowing param (the v4 helper doesn't use it).
  - `cw-tactics/` — practical CW genealogy playbook: abbreviation
    expansion (Wm/Jas/Thos), apostrophe variants, Confederate Home
    records, recommended search order.
  - `phonetic-algorithms/` — comparison of Soundex, Daitch-Mokotoff,
    Double Metaphone, Jaro-Winkler, Damerau-Levenshtein. Includes
    drop-in JS snippets for Tampermonkey.
  - `naming-conventions/` — Southern 1800–1860 naming culture,
    Confederate Home populations, service-record naming quirks.
  - `broadened-set/` — **43,834-soldier Confederate + Union CW
    dataset** pulled from `freecivilwarrecords.org` (17 Confederate,
    5 Union regiments, 11 states). Used to validate strategy
    patterns beyond the OK-heavy local data.

- **`docs/v5-design/`** — proposed v5.0 design:
  - `playbook.md` — master design doc with sources and architecture
  - `strategy-ladder.md` — 13 strategies in execution order with
    validated hit-rates per strategy

- **`scripts/`** — analysis scripts that produced the research:
  - `analyze_local_db.py`
  - `analyze_slug_shapes.py`
  - `validate_v5_ladder.py`
  - `build_broadened_set.py`
  - `match_broadened_to_local.py`

### Top-level finding

The current `FindaGraveIterativeHelper.user.js` v4.0 reaches ~80%
hit-rate against the local 577-pair validation set. The proposed
v5.0 strategy ladder reaches **100%** by adding:
- `middlename` as a primary search parameter (recovers 24 of 41
  exact-sniper failures)
- Apostrophe and abbreviation variant generation
- Civil War bio context filter as catch-all

But before implementation, **Path B** is needed: pull NPS Soldiers &
Sailors index data to broaden the training set beyond the NARA CMSR
bias (enlisted-focused, surviving-regiment bias).

## [0.7] — 2026-07-01

- Added update/download URLs and minor ledger fixes.
- Added README and MIT license.
- Added `process_ledger.py` for converting JSON exports to CSV + Markdown.

## [0.6] — 2026-06-XX

- Strip `VETERAN` suffix from memorial names during scraping.

## [0.5] — 2026-06-XX

- Made buttons collapsable.

## [0.1] — Initial commit

- `FindaGraveScraper.user.js` — basic memorial scraper with ledger
  export.