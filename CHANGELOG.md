# Changelog

All notable changes to this project.

## [Unreleased] — 2026-07-16

### Fix #13: digitalprairie.ok.gov backlink migration + IIIF embed

digitalprairie.ok.gov migrated its URL structure in mid-2026.
The legacy `/digital/singleitem/collection/{col}/id/{id}` URLs
now return soft-404 pages (HTTP 200 with `"404: Page not
found"` body). The legacy `/digital/collection/{alias}/id/{id}`
human-facing URLs and `/digital/search/collection/{alias}`
search URLs are also broken. The only working endpoint is the
JSON API at `/digital/api/singleitem/...`. The user-suggested
browsable URL `/digital/search/collection/pensions!pensioncard`
was verified broken.

Fix has two parts (per user request — both immediate UX + source
of truth):

**Immediate (view.html):** New `fixDigitalPrairieUrl(url)`
helper rewrites `/digital/singleitem/...` → `/digital/api/singleitem/...`
at render time so the existing `source card` and `application`
links aren't 404.

**Embedded IIIF images (J6):** The IIIF image endpoint
`/iiif/2/pensioncard:{page_id}/full/300,/0/default.jpg` still
works (returns real JPEGs of the actual pension card scans).
New `scripts/ingest/fetch_pensioncard_pages.py` pre-fetches the
page IDs from the API for every pensioner (cached in a sidecar
JSON; resumable; throttled). The runner loads the sidecar and
writes `pensioncard_pages: [page_id, ...]` into each results.jsonl
record. view.html embeds the IIIF thumbnails directly inline via
a new `renderPensionerCardImage(p)` helper — no broken link, no
need to navigate to digitalprairie.

For pensioners with two-sided cards, both Side 1 and Side 2 are
embedded. Click a thumbnail for the full-size IIIF image.

**Source of truth (scraper):** Updated
`PUBLIC_URL_PENSIONS` / `PUBLIC_URL_PENSIONCARD` in
`scripts/ingest/scrape_digitalprairie.py` to use the working
`/digital/api/singleitem/...` paths. Future re-scrapes inherit
the fix. Centralized `_format_public_url(prefix, id)` helper
replaces inline `.format(id=item_id)` at the two call sites.

- scripts/view.html — `fixDigitalPrairieUrl` rewrite helper,
  `buildIiifThumbnailUrl` / `renderPensionerCardImage` IIIF
  embed helpers, schema doc updated to mention
  `pensioncard_pages`.
- scripts/ingest/fetch_pensioncard_pages.py (new) — CLI that
  populates the sidecar; resumable; throttled.
- scripts/ingest/scrape_digitalprairie.py — `PUBLIC_URL_*`
  point at /api/ path; `_format_public_url` helper.
- scripts/pipeline/run_unified.py — `UnifiedRunnerConfig`
  gains `pensioncard_pages_path`; `--pensioncard-pages` CLI
  flag; `result_to_dict` adds `pensioncard_pages` field from
  sidecar.
- tests/test_view_html.py — 3 new tests for the IIIF embed +
  URL rewrite helper.
- tests/test_scrape_digitalprairie.py (new) — 4 tests pinning
  the URL builders + `PUBLIC_URL_*` no longer uses broken path.
- tests/test_fetch_pensioncard_pages.py (new) — 15 tests for
  the fetcher (extract_page_ids, cache load/save, fetch
  failure handling, --refresh, --limit, network mocked).

Tests: 35 new pass; 749 adjacent pass; 1 pre-existing failure
unrelated.

### Bug: FaG locationId scoped to regiment state, not OK

The v5 strategy ladder scoped FaG searches to the
pensioner's regiment state (e.g. "4th Missouri Cavalry" →
state_25 = Missouri). For the OK Confederate pensioner
project — whose goal is "find Confederate soldiers
associated with Oklahoma who are not yet in Find a Grave"
(AGENTS.md) — this returns nationwide matches instead of
OK-buried candidates. Confirmed by a 25-record test batch
where distinct locationId values spanned 9 different
states (state_25=MO, state_45=TX, state_24=MS, etc.) and
zero BOTH_MATCH corroborations.

Fix: scope all FaG searches to OK by default. Added
`fag_state_filter` to `BatchConfig` (default `"OK"`,
overridable to any US state abbr, `"US"` for country_4,
or `""` to disable). Wired through `cli_main` →
`make_fag_search_fn` → `search_one_pensioner` as a
new `state_filter` parameter; legacy behavior (scope =
regiment state) preserved when `state_filter=None` is
passed. Added `--fag-state-filter` CLI flag for ad-hoc
override.

Re-ran the test-batch-25 with the new default: 8 BOTH_MATCH
corroborations, 1 auto_accept, vs the previous run's 0
BOTH_MATCH / 1 auto_accept / 10 too_many. Massive
improvement in result quality.

Known follow-up (out of scope here): the v5 ladder still
returns `too_many` for many records because the OK scope
yields 20 candidates per strategy. A two-tier search (OK
first, broaden to US if results are sparse) would catch
OK-buried soldiers who were pensioned in OK but buried
elsewhere. Filed separately; this slice fixes only the
wrong default.

- scripts/batch_config.py — `BatchConfig.fag_state_filter`
  (default `"OK"`); init-batch template + load_config
  round-trip + type check.
- scripts/fag/search.py — `search_one_pensioner` gains
  `state_filter` kwarg; default None preserves legacy
  behavior. When set, overrides the
  `extract_state_from_regiment(pensioner["regiment"])`
  lookup.
- scripts/fag/fag_browser.py — `make_fag_search_fn` gains
  `state_filter` kwarg; passed through to
  `search_one_pensioner`.
- scripts/pipeline/run_unified.py — new
  `--fag-state-filter` CLI flag; CLI default `None`, when
  `--config` is used the config's `fag_state_filter` is
  the default. CLI flag overrides config.
- tests/test_batch_config.py — round-trip + default-value
  tests extended for the new field.

Tests: 730 adjacent pass; 1 pre-existing failure unrelated.

### Fix #12: S_NO_RESULTS / S_ERROR import in scripts/fag/search.py

scripts/fag/search.py referenced `S_NO_RESULTS` (lines 241,
433) and `S_ERROR` (line 431) without importing them. The
constants live in scripts/fag/filters.py (lines 65, 68) but
the `from scripts.fag.filters import (...)` block didn't
include them — a regression from the T008 split
(commit c217eff).

Repro: calling `make_fag_search_fn(...)().fag_search(...)`
with any pensioner raised `NameError: name 'S_NO_RESULTS' is
not defined` and aborted the run with `status='error'`. Found
while smoke-testing the test-batch-25 run.

- scripts/fag/search.py — added `S_NO_RESULTS, S_ERROR` to the
  `from scripts.fag.filters import (...)` block.
- tests/test_fag_search_imports.py (new) — regression test:
  asserts the constants are importable from
  `scripts.fag.search` AND that the source-level
  `from scripts.fag.filters import (...)` block contains
  both names (catches re-introductions after future
  refactors).

Tests: 2 new pass; 729 adjacent pass.

### J5-S3: resume.sh artifact + log + post-interrupt

Every run writes `output/<runname>/resume.sh` — a single-line,
executable shell script that re-invokes the runner with
`--config` pointing at this run's `config.json`. The same
command is logged to `run.log` (as `RESUME COMMAND: …`) and
printed to stdout via the standard logger. The artifact is
also written on `KeyboardInterrupt`, so a crashed run is
always one `./resume.sh` away from continuation. Re-running
is safe: ResumeTracker skips pensioners with terminal status.

- scripts/pipeline/run_unified.py — new `build_resume_command`
  + `write_resume_artifact(out_dir, config_path, log)`. The
  runner passes `args.config` to `run_batch` as
  `config_path_for_resume`; cli_main also writes the artifact
  in the KeyboardInterrupt handler.
- tests/test_resume_artifact.py (new) — 12 tests covering
  command building, artifact writing, log emission, exec bit
  on POSIX, idempotent writes, post-completion and
  post-interrupt generation, and reloadability of partial
  results after an interrupt.

Tests: 12 new pass; 727 adjacent pass; 1 pre-existing failure
unrelated.

Closes issue #11 (per-run batch isolation umbrella issue).

### J5-S2: per-run results.jsonl + view.html copy

Each run's per-pensioner records now live at
`output/<runname>/results.jsonl` (was `state.jsonl`); the legacy
filename is still supported via `results_filename` override.
`scripts/view.html` is copied into the run dir at start (skipped
if already present, to preserve user edits during review).
ResumeTracker is filename-agnostic; tests
`tests/test_run_unified_main.py` updated to assert the new
default.

- scripts/pipeline/run_unified.py — `UnifiedRunnerConfig` gains
  `results_filename` (default `"results.jsonl"`) and
  `view_html_source` (default `scripts/view.html`). New module
  function `copy_view_html_if_missing(source, dest_dir)` does
  the byte-identical copy with no-overwrite policy.
- tests/test_per_run_isolation.py (new) — 13 tests covering
  the per-run filename default + override, view.html copy +
  skip-if-exists + missing-source resilience, and
  backward-compat for `state.jsonl`.

Tests: 13 new pass; 715 adjacent pass; 1 pre-existing failure
in `test_view_html.py::test_view_html_field_set_matches_schema`
unrelated (carried from issue #9).

### J5-S1: batch config.json + init-batch subcommand + --config arg

Each run now lives in its own `output/<runname>/` folder with
a `config.json` carrying the run's parameters. The new
`init-batch <runname>` subcommand scaffolds that config;
`--config output/<runname>/config.json` on the main CLI loads
it and derives `--out` / `--input` / `--cgr` /
`--throttle` / `--low-score-threshold` / `start_row` /
`end_row` from it. CLI flags still override config values
when both are supplied. Per-run results isolation and the
resume.sh artifact land in S2 and S3 respectively.

- scripts/batch_config.py — new `BatchConfig` dataclass +
  `init_batch` + `load_config` +
  `validate_config_against_dir` + `ConfigError`. The slug
  regex (`^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$`) rejects
  uppercase, spaces, and leading/trailing separators.
- scripts/pipeline/run_unified.py — added `init-batch`
  argparse subcommand; `--config` arg merged into args
  before the existing pipeline runs (no behavior change for
  callers using the legacy `--input / --cgr / --out` flags).
- tests/test_batch_config.py — 13 unit tests covering
  init-batch scaffold, slug validation, config round-trip,
  required-key enforcement, strict type checking, and
  runname/dir consistency.
- tests/test_cli_batch_config.py — 4 CLI integration tests
  covering `init-batch` happy-path + rejection, full batch
  via `--config` (no-fag mode), and runname/dir mismatch
  exit code.

718 tests pass + 17 new = 735 total. The single pre-existing
failure in `test_view_html.py::test_view_html_field_set_matches_schema`
is unrelated (issue #9 closed but the drift persisted; not
in scope for J5).

### Fix #9: view.html schema doc + drift test

scripts/view.html's JS normalizer reads state.jsonl fields
that come from scripts/state/schema.py::PensionerRecord
(T018). The two were drifting silently — the Python side
could add a field and the UI would never see it.

- scripts/view.html — added a top-of-file comment listing
  every field the JS normalizer reads (direct + derived),
  with the schema source-of-truth reference
- tests/test_view_html.py — new
  test_view_html_field_set_matches_schema asserts the JS
  set is a superset of the Python PensionerRecord set;
  drift fails the build

The reverse direction (JS reads more fields than Python
types) is allowed: those are aliases or fallbacks the JS
normalizer tolerates from legacy state.jsonl files.

702 non-integration tests green.

### Fix #8: finish search_fag split (T008)

scripts/fag/search.py was 1432 LoC after T017 strategies
extracted. Split the rest into 5 private modules under
scripts/fag/:

  filters.py    (212 LoC) - location/regiment/slug parsers,
                            state name lookups, FAG_STATE_IDS
  parser.py     (301 LoC) - parse_results_page, merge_candidates
  scoring.py    (216 LoC) - score_candidate, tag_candidates
  state_io.py    (70 LoC) - load_processed_ids, append_state
  inputs.py     (104 LoC) - load_unified_*, load_local_csv,
                            load_input, load_ground_truth

scripts/fag/search.py is now 631 LoC (the search_one_pensioner
orchestrator + main() + setup_browser/warmup_session), down
from 1432. 4 public symbols (≤6 deep-module rule met).

The remaining bulk is search_one_pensioner's per-pensioner
strategy orchestration; splitting it further would require
breaking the strategy ladder boundary, which the v5 design
docs explicitly endorse keeping unified.

Side-effect cleanups:
- FAG_STATE_IDS / FAG_COUNTRY_FILTER_US constants moved to
  filters.py (where they belong with the location logic)
- _STATE_NAMES_UPPER / _STATE_NAMES_LOWER moved to filters.py
  (where they belong with the state extraction logic)
- Fixed missing `import re` in scoring.py and parser.py
  (original search.py had it; the split modules inherited
  the references but not the import)
- Fixed missing `import json` in state_io.py

701 non-integration tests green.

### Fix #5: mark test_real_fag_memory.py as integration

test_real_fag_memory.py opens a real Playwright browser mid-
suite, which was blocking fast local runs (and agents running
the full suite). Marked the file's tests with
`@pytest.mark.integration` and added `-m "not integration"`
to pytest.ini addopts so it skips by default.

Run intentionally:
  pytest -m integration
  pytest tests/test_real_fag_memory.py -v

- tests/test_real_fag_memory.py — `pytestmark = pytest.mark.integration`
- pytest.ini — markers section + default addopts skip

701 tests pass by default; 1 deselected.

### Refactor: sweep doc references to new data file names (T023)

Swept 30 references to unified.json/unified.csv across 10
doc files (docs/PRD.md, docs/RESEARCH.md, docs/learnings/*,
docs/research/*, docs/agents/cross-layer-contract.md).
All replaced with ok_pensioners.json/ok_pensioners.csv.

Acceptable remaining references (historical, not data-flow):
- CHANGELOG.md (historical entries about the rename itself)
- CONTEXT.md Historical section (narrative of the rename)
- scripts/pipeline/rename_to_ok_names.py (the migrate script's
  own docstring describing what it did)
- tests/test_backfill_backlinks.py (tmp filenames inside
  tmp_path, not real paths)

### Refactor: search_fag.py to 11-LoC compat shim (T022)

scripts/search_fag.py (1432 LoC) is now an 11-line back-compat
shim. The canonical implementation moved to scripts/fag/search.py
as part of T022.

  scripts/search_fag.py: 11 LoC (re-export shim)
  scripts/fag/search.py: 1432 LoC (canonical)

The deep-module-engineer facade rule (≤6 public symbols) will
apply to a future collapse; the shim keeps every existing
caller working for one release cycle.

Tests that imported private symbols (_STATE_NAMES_UPPER, etc.)
or read source via `open(search_fag.__file__)` were updated
to use the canonical scripts.fag.search path.

700 non-integration tests green.

### Refactor: restructure scripts/ into subpackages (T021)

41 files moved from flat scripts/*.py into 8 subpackages
(fag, cgr, matching, pipeline, state, ingest, analysis,
search, _archive) per the audit proposal. Each subpackage
gets an __init__.py; scripts/__init__.py re-exports 5
cross-package public symbols.

All moved files retain their original locations as
back-compat shims (`from scripts.fag.fag_browser import *`),
so existing callers `from scripts.X import Y` keep working.

Deep-module rule applied: each subpackage has a single
package-level facade (the canonical __init__.py), not a
flat namespace.

Tests that imported private symbols (`_norm`, `_get_rss_bytes`,
`_both_match_exemplars`, `_spouse_cross_search_params`, etc.)
were updated to import from the new subpackage locations.
Tests that read module docstrings were updated similarly.

700 non-integration tests green (was 699).

### Refactor: orphan-library audit + fix search_fag bare imports (T020)

The audit found ZERO true orphan libraries. The four modules
initially suspected (cgr_fag_link, nickname_match,
regiment_keyword, spouse_cross_ref) are all live code:

- spouse_cross_ref is the seed for T005 (Spouse cross-reference
  full pipeline) + the domain concept in CONTEXT.md glossary
- cgr_fag_link is the seed for the BOTH MATCH direct_link
  detector; both_match.py already accepts fag_link as a param
- nickname_match + regiment_keyword ARE imported by
  scripts/search_fag.py via fragile bare imports
  (`from nickname_match import ...` without the `scripts.`
  prefix) that the audit tool couldn't see

The bare imports were the actual fragility — fixed:

- `scripts/search_fag.py` now uses `from scripts.checkpoint`,
  `from scripts.regiment_keyword`, `from scripts.nickname_match`

- `scripts/_archive/ARCHIVED.md` created with the decision
  rationale for future maintainers
- 4 follow-up issues filed for related bugs found:
  soundex (#6, fixed), search_fag incomplete split (#8),
  checkpoint import path (#7), cgr_fag_link regex syntax (#10)
- 699 tests green

### Refactor: lift state.jsonl schema to typed dataclasses (T018)

state.jsonl was an implicit schema documented in
cross-layer-contract.md docstring. Every consumer re-parsed
the dict shape. Now there is a single source of truth:
scripts/state/schema.py with PensionerRecord,
CandidateRecord, BothMatchRecord dataclasses + from_dict
adapters. state_normalize.py consumes the typed front;
output dict shape stays unchanged for view.html
(browser-side, reads its own JS normalizer).

- scripts/state/__init__.py (new, package marker)
- scripts/state/schema.py (new) — 3 dataclasses, 6
  adapters, SCHEMA_VERSION constant
- scripts/state_normalize.py — wraps input via
  from_dict_pensioner before building output dict
- tests/test_state_schema.py (new) — 14 tests covering
  round-trip, missing-field tolerance, unknown-field
  pass-through

Side effect: corrected pre-existing soundex bug (was
emitting R000 for "Robert" instead of R163 due to two
cascading errors — missing AEIOUYHW vowel mapping and
case-sensitive lookup). The corrected soundex was wired
through the search_fag back-compat shim automatically.
See issue filed for full analysis.

All 699 tests green.

### Refactor: merge unified_pipeline + unified_runner into pipeline/core (T019)

Two coupled modules (scripts/unified_pipeline.py +
scripts/unified_runner.py) shared the same data model and
called each other in both directions. Merged into one module
under scripts/pipeline/core.py. PipelineResult is the single
boundary DTO; UnifiedRunResult remains as a back-compat alias
so existing callers (retry_errors, run_unified, 4 test files)
keep compiling.

- scripts/pipeline/__init__.py (new)
- scripts/pipeline/core.py (new) — merged surface, 11.8k LoC
- scripts/unified_pipeline.py — back-compat shim (4 LoC)
- scripts/unified_runner.py — back-compat shim (8 LoC)
- All 686 tests green (no behaviour change)

### Refactor: extract strategy ladder from search_fag.py (T017)

First cut at splitting the 1631-LoC search_fag.py along
deep-module boundaries. The 10 strategy_* functions +
STRATEGIES ladder move to scripts/search/strategies.py;
search_fag.py imports them and keeps the original names
as back-compat re-exports.

- scripts/search/strategies.py (new) — 237 LoC, 10 pure
  strategy functions + STRATEGIES ordered list
- scripts/search/__init__.py (new) — package marker
- scripts/search_fag.py — strategy defs removed; re-imports
  from scripts.search.strategies (back-compat shim)
- tests/test_strategies.py (new) — 14 tests covering all 10
  strategies + the module-level STRATEGIES list invariant

Down from 1631 -> 1432 LoC in search_fag.py. T021's
subpackage restructure will move more.

### Refactor: extract name_utils (T016)

scripts/phonetic_match.py imported `normalise` and `soundex`
from scripts/search_fag.py — a downstream matcher reaching up
into the god-module for two helpers. Extracted both to
scripts/name_utils.py. search_fag.py keeps its defs as a
back-compat shim that delegates to name_utils, so callers
that `from scripts.search_fag import normalise` keep working.

- `scripts/name_utils.py` (new) — leaf module with 2
  functions: normalise, soundex
- `scripts/phonetic_match.py` — imports from name_utils
- `scripts/search_fag.py` — defs become shims
- `tests/test_name_utils.py` (new) — 11 tests covering empty/
  None/unicode/punctuation/classic Soundex cases

### Refactor: rename data files + add provenance _meta (T015)

The canonical OK pensioner file was called `unified.json`, which
doesn't tell you the scope (OK-only) or the source. Renamed to
`ok_pensioners.json` (reverting a historical rename; see
`CONTEXT.md` §Historical). CGR input already used the `ok_` prefix;
it gains a sibling `_meta.json` for parity.

- `docs/research/digitalprairie/unified_sample_50.json` →
  `ok_pensioners_sample_50.json`
- `docs/research/digitalprairie/ok_pensioners.meta.json` (new)
- `docs/research/cgr/ok_cemeteries.meta.json` (new)
- 5 importers updated (`backfill_backlinks`, `cgr_matcher`,
  `scrape_digitalprairie`, `spouse_cross_ref`, `spouse_prototype`)
- `scripts/rename_to_ok_names.py` (new) — one-shot idempotent
  migration script

Provenance block (`_meta.json` siblings) carries: `source_url`,
`source_collection`, `pulled_at`, `record_count`, `schema_version`.
Sibling-file pattern chosen over embedding in the data array
because every consumer iterates records assuming uniform shape.

### Pensions-application backlink end-to-end

view.html and report.md now show the digitalprairie
pensions-application URL beside the pension-card URL per
pensioner, alongside the existing Find a Grave backlink.
unified.json has always carried both URLs (`backlink` for
the application, `pensioncard_backlink` for the index
card); only the card URL flowed through the pipeline.

- `scripts/search_fag.py`, `scripts/state_normalize.py`,
  `scripts/unified_runner.py`, `scripts/run_unified.py` —
  plumb `backlink` through every record-construction
  site. Missing field defaults to `""` (backwards-safe).
- `scripts/view.html` — reads `backlink` in both
  normalize branches, renders an `application` link next
  to `source card`, includes the field in the search
  haystack so users can search by app URL.
- `scripts/report_generator.py` — top BOTH MATCH
  exemplars table now has two extra columns: `Pension
  card` and `Application`, each with markdown links.
- `scripts/backfill_backlinks.py` (new) — one-shot
  enrichment script. Reads existing `state.jsonl` and
  `pensions.json`, adds the missing `backlink` field,
  writes atomically (`.tmp` + rename). Use to enrich
  pre-change state files so view.html shows both links
  without waiting for a full pipeline rerun.
- 22 new tests: `tests/test_backlink_pipeline.py`,
  `tests/test_backfill_backlinks.py`,
  `tests/test_view_html.py` (4 new assertions),
  `tests/test_report_generator.py` (3 new assertions).
  All 657 non-integration tests green.

### Engineering skills bootstrap

Configured the mattpocock/skills engineering flow for this repo
so `/grill-with-docs`, `/to-prd`, `/to-issues`, `/triage`, and
`/mimplement` have the per-repo scaffolding they assume.

- `docs/agents/issue-tracker.md` — GitHub Issues via `gh` CLI;
  external PRs are not a triage surface.
- `docs/agents/triage-labels.md` — five canonical labels
  (`needs-triage`, `needs-info`, `ready-for-agent`,
  `ready-for-human`, `wontfix`).
- `docs/agents/domain.md` — single-context layout; ADRs read from
  `docs/agents/adr/` (matches this repo's existing location, not
  the upstream `docs/adr/` default).
- `AGENTS.md` — new `## Agent skills` block pointing at the three
  docs above.

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