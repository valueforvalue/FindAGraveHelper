# Changelog

All notable changes to this project.

## [Unreleased] — 2026-07-16

### Memory leak fixes for long runs

The full 7,758-record Run #2 grew pwsh.exe to ~7 GB and then
~3.5 GB even on resume; pwsh became unresponsive. Investigation
pointed at two compounding issues:

1. **Playwright Locator and `body` string retention** in
   `scripts/search_fag.parse_results_page()` — link_locators list
   (up to 20 refs) and the full `page.inner_text("body")` string
   remained alive until function exit; on multi-thousand-record
   runs this added up. Fixed by explicitly clearing the locator
   list, dropping the body string, and running
   `gc.collect()` every 25 records.
2. **`scripts/fag_browser._open_browser()` only closed the
   Browser**, not the Context or Page — leaving Playwright
   connection objects referenced after periodic resets. Now closes
   page → context → browser in order, drops state refs to None,
   and runs `gc.collect()` once before spawn.

Added:
- `scripts/rss_watchdog.py` — background thread that polls process
  RSS via Win32 `GetProcessMemoryInfo` (no psutil dependency).
  Three configurable thresholds: warn, force-reset (signals the
  runner to reopen the browser at the next opportunity), exit
  (hard `os._exit(1)` so the runner can't write junk records after
  a wedged pwsh).
- `scripts/soak_memory.py` — manual smoke test that drives N
  synthetic Playwright navigations, samples RSS, computes slope,
  and exits 1 if average growth exceeds `--max-slope-mb-per-10`.
- `tests/test_rss_watchdog.py` — platform-agnostic watchdog tests
  via monkeypatched `GetProcessMemoryInfo` (7 tests).
- `tests/test_search_fag_memory.py` — parse_results_page memory
  hygiene tests (3 tests).

`scripts/run_unified.py` and `scripts/retry_errors_run.py` now
expose `--no-rss-watchdog`, `--rss-warn-mb`, `--rss-force-reset-mb`,
`--rss-exit-mb`, and `--max-consecutive-errors` CLI flags. Defaults:
2048 / 4096 / 6144 MB; 10 consecutive errors.

`scripts/fag_browser.py`: `fag_search()` now auto-recovers from
Playwright closed-target errors ("Target page, context or browser
has been closed" etc.) by reopening the browser at the next
opportunity. After `--max-consecutive-errors` (default 10)
in-a-row errors, raises to let the outer loop terminate the run.

`scripts/fag_browser.py`: matches closed-target errors against a
list of stable substrings across Playwright versions
("target closed", "browser has been closed", etc.) so the
recovery logic doesn't break on Playwright message changes.

### Run #1 / Run #2 update

- Run #1 produced ~3,361 valid records before the original DOM-
  crash bug.
- Run #2 (resume) added another ~1,000 valid records before
  Chromium memory pressure + a previously-broken browser reset
  produced two more error storms.
- State file `data/results/run_full_2026_07_16/state.jsonl` is
  the canonical record; the new leak fixes only affect future
  runs. Existing errored records will be re-tried with the new
  code via `scripts/retry_errors_run.py` once a fresh main run
  completes.



### Added — Oklahoma Digital Prairie Confederate pension index

**The goal of the project** is to find Confederate soldiers associated
with Oklahoma. The 1915 Oklahoma Confederate Soldiers' Pension Act
created a Board of Pension Commissioners that documented every
Confederate veteran (or widow) who applied for a state pension — a
canonical list of OK-associated CW soldiers.

- **`docs/research/digitalprairie/`** — pulled 7,558 unique pensioners
  from `digitalprairie.ok.gov` (both `pensions` and `pensioncard`
  collections, merged on application #).
  - 7,709 application files
  - 11,987 index cards
  - 7,558 unified records (canonical OK-associated CW pensioner list)
  - Each record has: parsed name, app#, pension#, company, regiment,
    spouse name, source URL, IIIF image URL, and a backlink to the
    original card on digitalprairie.ok.gov
- **`scripts/scrape_digitalprairie.py`** — the scraper. Iterates ID
  range, hits the CONTENTdm v13 single-item JSON API, parses
  structured metadata (no OCR needed), merges the two collections
  on application #, outputs both per-collection and unified JSON+CSV.
  Resume-safe. ~5 min for full run at concurrency 15.
- A 50-record sample (`unified_sample_50.{json,csv}`) is committed
  for quick reference. The full 30 MB unified.json is gitignored
  (reproducible by re-running the script).

### Top-level implication

The 7,558 unified records are the canonical input for the next step:
batch FaG searching. The local dixiedata DB has 575 soldiers
already in FaG. Most of the ~7,000 not-yet-in-FaG OK-associated CW
pensioners are the next batch to search. The next helper script
should:

1. Iterate `digitalprairie/unified.json`
2. Build a search URL per soldier using the v5.0 strategy ladder
3. Parse results, score, auto-flag high-confidence matches
4. Output `digitalprairie/unified_with_fag.csv`

### Previous: Research workspace for v5.0 design

Earlier in the same session, this commit also added the v5.0
research workspace. It does **not change any userscript behavior**.
It documents research conducted in July 2026 toward a v5.0 rewrite
of `FindaGraveIterativeHelper.user.js`.

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

But before implementation, **Path B** was needed: pull NPS Soldiers &
Sailors index data to broaden the training set beyond the NARA CMSR
bias (enlisted-focused, surviving-regiment bias). Path B has since
been deferred — the immediate goal shifted to building the OK
Confederate pensioner index (see above) for batch FaG searching.

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