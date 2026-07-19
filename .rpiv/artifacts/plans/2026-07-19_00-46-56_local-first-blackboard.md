---
template_version: 1
date: 2026-07-19T00:46:56-0500
author: Jeremy Morris
commit: ec8028c
branch: master
repository: FindAGraveHelper
topic: Local-First Blackboard refactor of Find a Grave Helper Python harness
parent: .rpiv/artifacts/architecture-reviews/2026-07-18_23-33-38_python-local-first-blackboard.md
phase_count: 7
unresolved_phase_count: 0
phases:
  - { n: 1, title: "Correctness and dependency hygiene", depends_on: [], blast_radius: public-API, effort: M }
  - { n: 2, title: "Blackboard contracts and durable local store", depends_on: [1], blast_radius: on-disk, effort: L }
  - { n: 3, title: "Unified evidence and decision policy", depends_on: [2], blast_radius: cross-module, effort: L }
  - { n: 4, title: "Provider safety and browser lifecycle", depends_on: [2], blast_radius: cross-module, effort: L }
  - { n: 5, title: "Event-guided scheduler skeleton", depends_on: [2], blast_radius: cross-module, effort: M }
  - { n: 6, title: "Typed Knowledge Sources and multi-pass refinement", depends_on: [3, 4, 5], blast_radius: cross-module, effort: L }
  - { n: 7, title: "Projection and review migration", depends_on: [6], blast_radius: cross-module, effort: L }
status: ready
tags: [plan, python, blackboard, persistence, playwright, cgr, multi-phase]
last_updated: 2026-07-19T00:46:56-0500
last_updated_by: Jeremy Morris
last_updated_note: "Step 9 triage complete: 17 reviewer findings (5 blockers, 8 concerns, 4 suggestions) — all 17 applied to plan; L7 AST check, schema smoke, view.html grep, SQLite pinning, teardown test, file count fix, import paths pinned, scope corrected."
---

# Local-First Blackboard Refactor — Multi-Phase Plan

Implementation plan for the 7-phase refactor documented in the parent
architecture review. Every phase ships as one or more vertical slices.
Each slice is copy-pasteable code; tests live alongside their slice.

## Overview

Refactor `FindAGraveHelper` (82 Python files, ~16,632 LOC) from rigid
batch control into Local-First Blackboard architecture. The 7 phases are
fixed by the parent review; this plan defines slices within each phase,
file maps, success criteria, and test updates. The Plan History tracks
per-phase approval as implement executes.

Approach: phases 1–4 are foundation (correctness, contracts, evidence,
safety). Phases 5–7 introduce the scheduler, migrate existing engines to
typed Knowledge Sources, and switch the review/projection layer to a
disposable projector. Code is source of truth; tests are evolved with
the architecture and may be retired or rewritten as new contracts land.

## Requirements

From architecture review (parent artifact, status `ready`):

1. Eliminate one-way-dependency violations in package root facade,
   internal module imports, leak-fix duplicates, parser undefined
   names, CGR limit flag, and dead code blocks.
2. Establish typed Blackboard contracts and durable work ledger.
3. Make scoring/decision policy source-neutral, versioned, and testable.
4. Centralize throttle/cooldown/bot detection across one RequestGate
   and one BrowserSession; measure process-tree RSS correctly.
5. Replace the central god-loop with a scheduler that dispatches
   autonomous Knowledge Sources from durable work.
6. Migrate ingestion, FaG search, CGR cross-reference, and refinement
   to typed Knowledge Sources; persist `QueryPlan` and FetchObservation.
7. Make current rows, reports, DD/CGR/spouse badges, and review export
   disposable projections from Blackboard facts.

## Current State Analysis

Key constraints derived from existing code:

- 1002 tests collected (1 deselected as `integration`); pytest config
  at `pytest.ini:5-9` skips real-browser tests by default.
- Production throttle floor: 2.5s between FaG requests; headful Chromium +
  stealth + warmup is mandatory (CONTEXT.md L1).
- Per-pensioner JSONL writer exists in `scripts/state/repository.py:168-175`
  (flush+fsync). Standalone FaG writer in `scripts/fag/state_io.py:52-57`
  flushes only.
- Knowledge Source split is aspirational; production code still has
  monolithic engines.

### Key Discoveries

- Issue #19 precedent (CHANGELOG.md, 2026-07 entry "Refactor: delete
  44 back-compat shim files in scripts/") shows a successful shim
  removal pattern: `scripts/__init__.py` emptied to docstring,
  tests + downstream migrated, full suite passed (892/892).
- Issue #22 iteration (CHANGELOG.md, "Iteration on issue #22: rip
  out adapter wrappers + add InMemoryStateRepository") introduced
  Repository protocol; `JsonlStateRepository._atomic_write`
  (`scripts/state/repository.py:240-251`) is the canonical atomic
  write seam to reuse.
- `JsonlStateRepository.iter_all` silently swallows
  `JSONDecodeError` (`:170-181`); state_check records them. No strict
  mode toggle exists.
- `JsonlStateRepository.replace_all(records, *, atomic: bool = True)`
  exposes the only existing toggle; no caller passes `atomic=False`.
- `cgr_ok_scraper.py:55-58` `ScrapingConfig` already has the right shape
  for adding `max_cemeteries`; pattern matches `batch_config.py:50-68`
  `BatchConfig` and `UnifiedRunnerConfig` pattern.
- `playwright_leak_fix` root copy differs at line 84-96 (sets list vs
  `_DummyTrace.format()`); Playwright calls `.format()` on
  `__pw_stack_trace__` per community fix.
- `scripts/fag/parser.py:1-10` imports only `Page`; `PWTimeout` and
  `log` referenced but not defined; `log.debug/warning` at `:89,103`.

## Desired End State

After Phase 7 ships:

```python
# scripts/blackboard/store.py — local-first durable store
from scripts.blackboard import BlackboardStore
store = BlackboardStore.open("output/run_blackboard")
store.append_observation(
    kind="FaGCandidateFetch",
    pensioner_id=12345,
    plan_id="plan-7d3a",
    payload={"memorial_id": "50923719", "slug": "william-pickney-looney"},
)
store.complete_work(
    work_id="work-12345-1",
    status="succeeded",
    observation_ids=[...],
)
projection = store.build_projection()
# projection is bytes-compatible with current state.jsonl
projection.write_text("output/run/state.jsonl")
```

```python
# scripts/fag/request_gate.py — single throttle seam
from scripts.fag.request_gate import RequestGate
gate = RequestGate.default_fag(provider="findagrave.com")
with gate.acquire("search") as token:
    page.goto(token.url)
    if token.bot_wall_observed:
        gate.cooldown_for(token.retry_after)
```

```python
# scripts/blackboard/scheduler.py — event-guided control
scheduler = BlackboardScheduler(store)
for knowledge_source in [IngestionKS, RegionalPlannerKS, FaGScraperKS,
                         CandidateScorerKS, CGRCorroboratorKS,
                         DeepRefinerKS, ProjectionKS]:
    scheduler.register(knowledge_source)
scheduler.run()  # blocks until terminal
```

## What We're NOT Doing

Per architecture review, scope is fixed. We are NOT:

- Building cloud brokers, central schedulers, or message queues.
- Adopting `pydantic`, `sqlmodel`, or new third-party dependencies
  without explicit approval.
- Touching `docs/`, `AGENTS.md`, or root `playwright_leak_fix.py` until
  the design lands in the new Blackboard form.
- Preserving legacy compat shims beyond the documented deprecation
  window. Issue #19's pattern: one removal commit per feature.
- Rewriting working `docs/agents/adr/*` historical records.
- Refactoring `tests/__init__.py`; tests live in their own files
  and need no package init.
- Adding public APIs that change wire format. JSONL projection must
  remain byte-shape compatible where `view.html` consumes it.

## Decisions

### From Step 4 directional confirms

#### D1. Empty `scripts/__init__.py` docstring-only (L0-01)
**Origin:** L0-01, CHANGELOG.md issue #19 precedent.
**Rule.** After Phase 1, the only content of `scripts/__init__.py` is
the module docstring. No eager re-exports of `run_batch`,
`search_one_pensioner`, `normalize_state_record`, or `build_report`.
Production code imports canonical subpackage paths only.
**Apply to (keep):** issue #19 deletion pattern.
**Apply to (drop / change):** the 4-name facade in
`scripts/__init__.py:34-37`; downstream callers that import via facade.

#### D2. Canonical imports only in production code (L0-02)
**Origin:** L0-02, current `scripts/fag/fag_browser.py:33` and
`scripts/pipeline/retry_errors.py:31,176` reach back to compatibility
shims.
**Rule.** Internal production code imports `scripts.fag.search`,
`scripts.pipeline.run_unified`, `scripts.fag.parser`, etc. directly.
Tests that import the shim (`tests/test_country_filter.py:13`,
`test_found_by.py:23`, `test_year_filter_strategy.py:19`,
`test_intra_strategy_throttle.py:28`, `test_search_fag_memory.py:28`)
get rewritten in Phase 1; they continue to pass.
**Apply to (keep):** `scripts/search_fag.py` shim file (retained
during transition; not removed in Phase 1).
**Apply to (drop / change):** `from scripts.search_fag import …` and
`from scripts.run_unified import …` in production modules; the same
imports in tests that have canonical equivalents.

#### D3. Strict-mode toggle on `iter_all` and `update` (L5-04)
**Origin:** L5-04. No existing strict-mode toggle exists
(Pattern B in `codebase-pattern-finder` report).
**Rule.** Add `strict: bool = False` keyword to
`JsonlStateRepository.iter_all` and `.update`. Default = `False`
preserves existing fail-soft behavior. When `strict=True`, the methods
raise `CorruptStateError(path, lineno, offset, raw)` instead of
swallowing `JSONDecodeError`. Add `check_state_then_read(path,
expected_ids)` helper that runs `check()` first and raises on
`not is_clean()`. Phase 1 ships the additions without changing
default behavior; Phase 2 uses strict mode in projection rebuilds.
**Apply to (keep):** existing `iter_all` swallow path; `InMemoryStateRepository`
default; `state_check.check_state_file` corruption reporting.
**Apply to (drop / change):** silent `JSONDecodeError: continue` only
for explicit forensic/recovery callers (named: `forensic_iter_all`).

#### D4. `ScrapingConfig.max_cemeteries` (L4-06)
**Origin:** L4-06; precedent in `batch_config.py:50-68` `BatchConfig`
and `UnifiedRunnerConfig` pattern.
**Rule.** Add `max_cemeteries: Optional[int] = None` to
`scripts.cgr.cgr_ok_scraper.ScrapingConfig`. CLI `--limit-cemeteries`
wires the value through. `scrape_ok_cemeteries` stops the per-cemetery
loop when `len(records) >= max_cemeteries` and returns early.
Existing resume-skip behavior still applies; limit binds the
newly-processed set on top of the resume set.
**Apply to (keep):** existing `processed_ids` resume logic.
**Apply to (drop / change):** the post-loop `pass` in
`cgr_ok_scraper_run.py:73-78`; argparse default `0` becomes `None`.

#### D5. Delete root `playwright_leak_fix.py` (L3-06)
**Origin:** L3-06. Canonical `scripts/fag/playwright_leak_fix.py`
already uses `_DummyTrace` per community fix.
**Rule.** Delete `playwright_leak_fix.py` (root). Update
`scripts/analysis/_probe_fag_filter.py:13` and
`tests/test_leak_fix_real.py:109` to import canonical module
(`from scripts.fag.playwright_leak_fix import apply_playwright_leak_fix`).
Canonical module is the only implementation.
**Apply to (keep):** `_DummyTrace.format()` semantics in canonical.
**Apply to (drop / change):** the divergent root `__pw_stack_trace__=[]`
list copy that breaks Playwright's `.format()` call path.

#### D6. Trim parser debug calls and add logger (L3-08)
**Origin:** L3-08. `scripts/fag/parser.py:89,103` reference undefined
`log`; `PWTimeout` not aliased.
**Rule.** Define module logger; alias `PWTimeout` from
`playwright.sync_api.TimeoutError`; replace the two
`log.debug(...)` and one `log.warning(...)` with logger calls.
The `log.debug("Too many results …")` and `log.warning("Locator
query failed: …")` survive as informational; the `PWTimeout` except
path returns silently. No behavior change beyond fixing the
`NameError` that was masked.
**Apply to (keep):** the fail-soft return paths for timeout and
locator failure.
**Apply to (drop / change):** `log.debug/warning` references that
depend on undefined `log`.

#### D7. Delete unreachable backfill block (L5-06)
**Origin:** L5-06. `backfill_backlinks.py:83-89` has 4 dead lines
after `return`, referencing undefined `tmp_path`.
**Rule.** Delete lines 84-89. The function `backfill` returns the
correct tuple via the existing `JsonlStateRepository.replace_all`
path. No other change. (Final review confirmed the dead block
causes a `NameError` only if execution ever reached it; the existing
return short-circuits before.)
**Apply to (keep):** the working `backfill()` body and its callers.
**Apply to (drop / change):** the stale `tmp_path.replace` second path.

### Slice shape

#### D8. One slice per finding; deps respected
**Origin:** Step 4 directional confirms.
**Rule.** Each of the 7 findings in Phase 1 becomes its own vertical
slice. Slice order respects depends_on edges; slices within a phase
that don't depend on each other may be parallelized by the implement
agent but each is reviewed at its own micro-checkpoint.
**Apply to (keep):** the architecture review's blast-radius and
file-target recommendations.
**Apply to (drop / change):** any attempt to "fix multiple findings
in one slice." A slice is one finding + tests; the merged change
is the implement commit.

### Test evolution

#### D9. Tests die when the architecture replaces their contract
**Origin:** Step 4 developer input.
**Rule.** The new architecture dictates that some tests must be
retired and new tests must take their place. The plan explicitly
allows test retirements when:
- The test pins behavior that the new Blackboard contracts replace
  (e.g. `test_unified_line_removed` no longer applies if the helper
  is genuinely gone and the migration is complete).
- The test imports a removed module (e.g. `from scripts.search_fag
  import …` in `tests/test_country_filter.py` retires after Phase 1
  Slice 2 updates it to `from scripts.fag.search import …`).
- The test asserts against the old `ScrapingConfig` shape before
  Slice 6 adds `max_cemeteries`.
Each slice's Success Criteria list which tests are expected to be
updated, added, or retired. Test count is a consequence, not a
constraint. The Phase-level "all 1002 pass" criterion applies only
to the tests still in scope at that phase.
**Apply to (keep):** the existing 28 state repository tests
(unaffected by Phase 1 changes to `iter_all`/`update`).
**Apply to (drop / change):** tests asserting removed shim imports
when canonical equivalent is in place.

## Phase 1: Correctness and Dependency Hygiene

**Goal:** remove known defects, establish one-way canonical imports,
and ship the smallest foundational layer for Blackboard work.

**Depends on:** none.
**Effort:** M. **Blast radius:** public-API (root facade emptied).
**Findings (7):** L0-01, L0-02, L3-06, L3-08, L4-06, L5-04, L5-06.
**Files touched (~18):** `scripts/__init__.py`, `scripts/fag/fag_browser.py`, `scripts/fag/parser.py`, `scripts/fag/playwright_leak_fix.py`, `playwright_leak_fix.py` (delete), `scripts/analysis/_probe_fag_filter.py`, `scripts/cgr/cgr_ok_scraper.py`, `scripts/cgr/cgr_ok_scraper_run.py`, `scripts/state/repository.py`, `scripts/pipeline/backfill_backlinks.py`, tests updated: `tests/test_country_filter.py`, `tests/test_found_by.py`, `tests/test_year_filter_strategy.py`, `tests/test_intra_strategy_throttle.py`, `tests/test_search_fag_memory.py`, plus new test additions to `tests/test_fag_parser_constants.py` (1 new), `tests/test_state_repository.py` (3 new), `tests/test_cgr_ok_scraper.py` (2 new).

### Phase 1: Overview

Each slice removes a single defect. Slices are ordered so that
non-dependent slices can ship independently; subsequent phases
build on Phase 1's canonical surface.

### Phase 1: Slice 1.1 — Empty root facade (L0-01)

**Goal:** `scripts/__init__.py` is docstring only; no eager
re-exports.

#### Phase 1: Slice 1.1: Changes Required:

##### 1. scripts/__init__.py

**File**: scripts/__init__.py
**Changes**: MODIFY — delete the four `from … import …` lines at `:34-37`;
leave docstring + comments only.

**File**: tests/test_scripts_facade.py (NEW)
**Changes**: NEW — assert `scripts.__init__.__all__` does not exist
(no `__all__`); assert module has only the docstring and no eager
imports of pipeline/search/state symbols at module-load time
(measure `len(sys.modules)` before/after import of `scripts`).

#### Phase 1: Slice 1.1: Success Criteria:

##### Automated Verification:
- [ ] `python -c "import scripts; import sys; assert 'scripts.pipeline.run_unified' not in sys.modules, 'scripts.search_fag' not in sys.modules"` succeeds
- [ ] `pytest tests/test_scripts_facade.py -q` passes
- [ ] `pytest tests/ -m "not integration" -q` passes (full existing suite)

##### Manual Verification:
- [ ] `python scripts/run_unified.py --help` exits 0
- [ ] `python scripts/search_fag.py --help` exits 0 (note: if Slice 1.1 ships before this manual check, the shim is gone and `python scripts/search_fag.py` fails with `ModuleNotFoundError`; if shim remains, `scripts/__init__.py:35` still eagerly imports `scripts.search_fag.search_one_pensioner` which pulls `scripts.pipeline.run_unified` — replace this check with a `python -c "import scripts; import sys; assert 'scripts.pipeline.run_unified' not in sys.modules"` smoke to assert the facade is inert regardless of shim order)

### Phase 1: Slice 1.2 — Canonical imports in production (L0-02)

**Goal:** internal production modules import canonical subpackage
paths only; never the compatibility shims.

#### Phase 1: Slice 1.2: Changes Required:

##### 1. scripts/fag/fag_browser.py

**File**: scripts/fag/fag_browser.py
**Changes**: MODIFY `:33-37` — replace
`from scripts.search_fag import (search_one_pensioner, setup_browser, warmup_session)`
with two import lines (canonical `scripts.fag.search` module):
`from scripts.fag.search import search_one_pensioner` and
`from scripts.fag.search import setup_browser, warmup_session`.
Verify at HEAD that `scripts/fag/search.py` exports all three
names (no `__all__` filtering blocks them); if any is missing,
add an explicit re-export in `scripts/fag/search.py` so the
import works without the shim.

##### 2. scripts/pipeline/retry_errors.py

**File**: scripts/pipeline/retry_errors.py
**Changes**: MODIFY `:31` and `:176` — replace `from scripts.run_unified import …`
with `from scripts.pipeline.run_unified import …`.

##### 3. tests/test_country_filter.py

**File**: tests/test_country_filter.py
**Changes**: MODIFY `:13` — replace
`from scripts.search_fag import (apply_location_filter, strategy_b1_exact, …)`
with `from scripts.fag.filters import (apply_location_filter, …)`
and `from scripts.search.strategies import (strategy_b1_exact, …)`
(`apply_location_filter` lives in `scripts/fag/filters.py`, not
`scripts.fag.search`; the strategy functions live in
`scripts/search/strategies.py`).

##### 4. tests/test_found_by.py

**File**: tests/test_found_by.py
**Changes**: MODIFY `:23` — `from scripts.search_fag import tag_candidates_with_found_by`
becomes `from scripts.fag.search import tag_candidates_with_found_by`.

##### 5. tests/test_year_filter_strategy.py

**File**: tests/test_year_filter_strategy.py
**Changes**: MODIFY `:19` — `from scripts.search_fag import (strategy_b1_exact, …)`
becomes `from scripts.search.strategies import (strategy_b1_exact, strategy_b3_first_initial_fuzzy, …)`
(no ambiguity; the strategy functions live in
`scripts/search/strategies.py` and are re-exported by
`scripts/fag/filters.py:320` for backward compat).

##### 6. tests/test_intra_strategy_throttle.py

**File**: tests/test_intra_strategy_throttle.py
**Changes**: MODIFY `:28` — `from scripts.search_fag import search_one_pensioner`
becomes `from scripts.fag.search import search_one_pensioner`.

##### 7. tests/test_search_fag_memory.py

**File**: tests/test_search_fag_memory.py
**Changes**: MODIFY `:28,111` — `import scripts.search_fag as sf` becomes
`import scripts.fag.search as sf`; the shim path is no longer required.

#### Phase 1: Slice 1.2: Success Criteria:

##### Automated Verification:
- [ ] `grep -rn "from scripts\.search_fag import\|from scripts\.run_unified import" scripts/fag scripts/pipeline scripts/analysis` returns no matches
- [ ] `pytest tests/test_country_filter.py tests/test_found_by.py tests/test_year_filter_strategy.py tests/test_intra_strategy_throttle.py -q -m "not integration"` passes
- [ ] `pytest tests/test_search_fag_memory.py -q -m "not integration"` passes (memory test loads the new module path)

##### Manual Verification:
- [ ] `python -c "from scripts.fag.fag_browser import make_fag_search_fn"` succeeds
- [ ] `python -c "from scripts.pipeline.retry_errors import RetryResult"` succeeds

### Phase 1: Slice 1.3 — Parser fail-soft fix (L3-08)

**Goal:** `scripts/fag/parser.py` no longer raises `NameError` for
undefined `PWTimeout` and `log`; module logger and timeout alias
are defined.

#### Phase 1: Slice 1.3: Changes Required:

##### 1. scripts/fag/parser.py

**File**: scripts/fag/parser.py
**Changes**: MODIFY — add `import logging`; define
`log = logging.getLogger(__name__)`; add
`PWTimeout = TimeoutError` (alias from `playwright.sync_api`).
Trim the two `log.debug("Too many results …")` and
`log.warning("Locator query failed: …")` calls — they were already
referencing an undefined `log`. Either remove the calls or
leave them; since the logger is now defined, the calls execute
cleanly. Keep the calls (no behavior change beyond fixing the
`NameError`).

##### 2. tests/test_fag_parser_constants.py

**File**: tests/test_fag_parser_constants.py
**Changes**: MODIFY — add one new test
`test_parser_module_defines_logger` asserting `hasattr(fag_parser, "log")`
and `hasattr(fag_parser, "PWTimeout")`. Existing regex tests remain.

#### Phase 1: Slice 1.3: Success Criteria:

##### Automated Verification:
- [ ] `python -c "from scripts.fag.parser import log, PWTimeout; assert log is not None; assert PWTimeout is not None"` succeeds
- [ ] `pytest tests/test_fag_parser_constants.py -q` passes
- [ ] `pytest tests/ -m "not integration" -q` passes (full existing suite, no parser regressions)

##### Manual Verification:
- [ ] `python -c "from scripts.fag.parser import parse_results_page"` succeeds (no `NameError` on module load)

### Phase 1: Slice 1.4 — Leak-fix dedup (L3-06)

**Goal:** root `playwright_leak_fix.py` is deleted; canonical
`scripts/fag/playwright_leak_fix.py` is the only implementation.

#### Phase 1: Slice 1.4: Changes Required:

##### 1. playwright_leak_fix.py (root)

**File**: playwright_leak_fix.py
**Changes**: DELETE (root-level shim; canonical lives in `scripts/fag/playwright_leak_fix.py`).

##### 2. scripts/analysis/_probe_fag_filter.py

**File**: scripts/analysis/_probe_fag_filter.py
**Changes**: MODIFY `:13-14` — replace
`import playwright_leak_fix / playwright_leak_fix.apply_playwright_leak_fix()`
with
`from scripts.fag.playwright_leak_fix import apply_playwright_leak_fix / apply_playwright_leak_fix()`.

##### 3. tests/test_leak_fix_real.py

**File**: tests/test_leak_fix_real.py
**Changes**: MODIFY `:109` — `from playwright_leak_fix import apply_playwright_leak_fix`
becomes `from scripts.fag.playwright_leak_fix import apply_playwright_leak_fix`.

#### Phase 1: Slice 1.4: Success Criteria:

##### Automated Verification:
- [ ] `[ ! -f playwright_leak_fix.py ] && echo gone` reports `gone` at repo root
- [ ] `python -c "from scripts.fag.playwright_leak_fix import apply_playwright_leak_fix"` succeeds
- [ ] `grep -rn "from playwright_leak_fix\|import playwright_leak_fix" .` returns no production matches (only docs/comments if any)
- [ ] `pytest tests/ -m "not integration" -q` passes (all existing tests still load with canonical module)

##### Manual Verification:
- [ ] `python scripts/analysis/_probe_fag_filter.py --help` does not error on import
- [ ] When the fix is applied, `__pw_stack_trace__` is `_DummyTrace` (matches canonical contract)

### Phase 1: Slice 1.5 — CGR cemetery limit (L4-06)

**Goal:** `--limit-cemeteries N` actually caps the per-cemetery
work units; `ScrapingConfig.max_cemeteries` carries the value
through `scrape_ok_cemeteries`.

#### Phase 1: Slice 1.5: Changes Required:

##### 1. scripts/cgr/cgr_ok_scraper.py

**File**: scripts/cgr/cgr_ok_scraper.py
**Changes**: MODIFY — add `max_cemeteries: Optional[int] = None` to
`ScrapingConfig`; in the per-cemetery loop, stop early and
log when `max_cemeteries is not None and len(records) >= max_cemeteries`.

##### 2. scripts/cgr/cgr_ok_scraper_run.py

**File**: scripts/cgr/cgr_ok_scraper_run.py
**Changes**: MODIFY — pass `max_cemeteries=args.limit_cemeteries or None`
to `ScrapingConfig`; replace the post-loop `pass` with documentation
comment explaining the limit is now enforced inside the scrape loop.

##### 3. tests/test_cgr_ok_scraper.py

**File**: tests/test_cgr_ok_scraper.py
**Changes**: MODIFY — add 2 new tests:
- `test_scrape_max_cemeteries_caps_results` — build 5 cemeteries
  in mock, pass `max_cemeteries=2`, assert 2 records returned.
- `test_scrape_max_cemeteries_none_means_all` — pass
  `max_cemeteries=None`, assert all 5 processed.

#### Phase 1: Slice 1.5: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_cgr_ok_scraper.py -q` passes (existing 15 test functions + 2 new = 17)
- [ ] `pytest tests/ -m "not integration" -q` passes (full existing suite)
- [ ] `grep -n "max_cemeteries" scripts/cgr/cgr_ok_scraper.py` returns ≥ 3 lines (ScrapingConfig field + use sites)

##### Manual Verification:
- [ ] `python scripts/cgr/cgr_ok_scraper_run.py --state OK --limit-cemeteries 5 --out C:/tmp/smoke.jsonl` returns after ≤ 5 cemeteries; log shows the cap

### Phase 1: Slice 1.6 — Strict mode for state I/O (L5-04)

**Goal:** `JsonlStateRepository.iter_all` and `.update` accept
`strict: bool = False`; when `strict=True`, `JSONDecodeError`
raises `CorruptStateError` with line context instead of being
silently swallowed. `check_state_then_read()` helper runs `check()`
first and raises on `is_clean() == False`.

#### Phase 1: Slice 1.6: Changes Required:

##### 1. scripts/state/repository.py

**File**: scripts/state/repository.py
**Changes**: MODIFY — add `CorruptStateError` exception class;
add `strict: bool = False` keyword to `JsonlStateRepository.iter_all`
and `.update`; when `strict=True`, raise `CorruptStateError(path,
lineno, offset, raw_line)`; add `JsonlStateRepository.check_state_then_read`
classmethod. Keep default `strict=False` so existing callers are
unaffected.

##### 2. tests/test_state_repository.py

**File**: tests/test_state_repository.py
**Changes**: MODIFY — add 3 new tests:
- `test_iter_all_strict_raises_on_corrupt_line` — write 3 lines
  (one corrupt) to state file; `repo.iter_all(strict=True)` raises
  `CorruptStateError` with line context.
- `test_iter_all_lenient_default_unchanged` — same input, default
  `strict=False` skips corrupt line and yields the rest.
- `test_check_state_then_read_raises_on_corruption` —
  `JsonlStateRepository.check_state_then_read(path, expected_ids)`
  raises when `check()` returns `not is_clean()`.

#### Phase 1: Slice 1.6: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_state_repository.py -q` passes (existing 27 test functions + 3 new = 30)
- [ ] `pytest tests/ -m "not integration" -q` passes (full existing suite; default `strict=False` keeps all callers fail-soft)
- [ ] `python -c "from scripts.state.repository import CorruptStateError, JsonlStateRepository; assert JsonlStateRepository.iter_all.__doc__ is not None"` succeeds

##### Manual Verification:
- [ ] `python -c "from scripts.state.repository import JsonlStateRepository, CorruptStateError; import tempfile, pathlib; f=tempfile.NamedTemporaryFile(delete=False, suffix='.jsonl'); f.write(b'{\"a\":1}\nnot json\n{\"a\":3}\n'); f.close(); list(JsonlStateRepository(pathlib.Path(f.name)).iter_all(strict=True))"` raises `CorruptStateError` (use `NamedTemporaryFile` to avoid `tempfile.mktemp()` deprecation noise)

### Phase 1: Slice 1.7 — Dead-block removal (L5-06)

**Goal:** `scripts/pipeline/backfill_backlinks.py` has only the
working `backfill()` path; the unreachable 4-line dead block is
gone.

#### Phase 1: Slice 1.7: Changes Required:

##### 1. scripts/pipeline/backfill_backlinks.py

**File**: scripts/pipeline/backfill_backlinks.py
**Changes**: MODIFY — delete lines 84-89 (the duplicate
`tmp_path.replace` and second `return` after the working
`return filled, skipped, missing`).

#### Phase 1: Slice 1.7: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/ -m "not integration" -q` passes (no test touched)
- [ ] `python -c "from scripts.pipeline.backfill_backlinks import backfill, load_unified_index"` succeeds
- [ ] `python -c "from scripts.pipeline.backfill_backlinks import backfill; import inspect; src=inspect.getsource(backfill); assert 'tmp_path' not in src"` confirms dead block is gone

##### Manual Verification:
- [ ] `python -c "from scripts.pipeline.backfill_backlinks import backfill, load_unified_index; import tempfile, json, pathlib; from scripts.state.repository import JsonlStateRepository; unified=pathlib.Path(tempfile.mkdtemp())/'ok.json'; unified.write_text(json.dumps([{'id':1,'backlink':'https://x'}])); state=pathlib.Path(tempfile.mkdtemp())/'state.jsonl'; JsonlStateRepository(state).append({'pensioner_id':1, 'pensioner_first':'A','pensioner_last':'B','fag_records':[],'cgr_records':[],'backlink':''}); filled, skipped, missing = backfill(state, load_unified_index(unified)); assert filled == 1"` succeeds

### Phase 1: Plan History

- Phase 1: Correctness and dependency hygiene — pending

## Phase 2: Blackboard Contracts and Durable Local Store

**Goal:** establish versioned RunManifest, Observation, WorkItem,
QueryPlan, and Projection envelopes plus durable local store while
preserving the JSONL projection.

**Depends on:** Phase 1.
**Effort:** L. **Blast radius:** on-disk.
**Findings (7):** L0-03, L1-02, L1-03, L5-01, L5-02, L5-03, L6-04.

### Phase 2: Overview

This phase creates the Blackboard persistence core. Slices ship
in dependency order: RunManifest first (observation has nothing
to reference without manifest); then observation/work envelopes
(L1-02, L1-03); then store (L5-01, L5-02); then durable migrations
(L6-04, L5-03). The phase preserves `state.jsonl` projection
byte-shape compatibility.

### Phase 2: Slice 2.1 — `RunManifest` envelope (L0-03)

**Goal:** `BatchConfig` evolves into or pairs with a versioned
`RunManifest` recording policy version, scheduler/bot budget,
and pass lineage.

**Spec:** `RunManifest(manifest_id, run_id, parent_manifest_id,
policy_version, knowledge_source_versions, scheduler_budget,
bot_budget, source_fingerprints, created_at)`. Persist manifest
side-by-side with `state.jsonl` (sibling file).

#### Phase 2: Slice 2.1: Changes Required:

##### 1. scripts/blackboard/schema.py (NEW)

**File**: scripts/blackboard/schema.py
**Changes**: NEW — define `RunManifest`, `ManifestBudget`, dataclass
versions; `schema_version: int = 1`; `to_dict()` and `from_dict()`.

##### 2. scripts/batch_config.py

**File**: scripts/batch_config.py
**Changes**: MODIFY — `BatchConfig.runname` keeps role; add helper
`build_manifest(batch_config, policy_version, knowledge_source_versions)`
that constructs and returns a `RunManifest`. Existing
`load_config`/`init_batch` unchanged.

##### 3. tests/test_batch_config.py

**File**: tests/test_batch_config.py
**Changes**: MODIFY — add `test_build_manifest_includes_policy_version`
and `test_manifest_roundtrip` tests.

#### Phase 2: Slice 2.1: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_batch_config.py -q` passes
- [ ] `python -c "from scripts.blackboard.schema import RunManifest; from scripts.batch_config import BatchConfig; m = RunManifest.from_dict(RunManifest(run_id='r', policy_version='1', knowledge_source_versions={}, scheduler_budget={}, bot_budget={}, source_fingerprints={}).to_dict()); print(m['schema_version'])"` outputs `1`

##### Manual Verification:
- [ ] `python -c "import scripts.blackboard.schema"` succeeds without circular imports

### Phase 2: Slice 2.2 — `Observation` envelope (L1-02)

**Goal:** `Observation(observation_id, pensioner_id, kind, source,
source_version, run_id, pass_id, caused_by, recorded_at, payload)`
becomes the durable unit for FaG/CGR/DD/post-pass evidence.

#### Phase 2: Slice 2.2: Changes Required:

##### 1. scripts/blackboard/schema.py

**File**: scripts/blackboard/schema.py
**Changes**: MODIFY — add `Observation` dataclass + `Kind` enum
(`FaGSearchPlan`, `FaGCandidateFetch`, `CGRCorroboration`,
`DixieDataMatch`, `SpouseMatch`, `BotWallObserved`,
`MemoryPressureObserved`, `ParseError`, etc.).

##### 2. tests/test_state_schema.py (existing, possibly under
different name) — assert envelope exists, has all required
fields, `to_dict()`/`from_dict()` round-trips.

#### Phase 2: Slice 2.2: Success Criteria:

##### Automated Verification:
- [ ] `python -c "from scripts.blackboard.schema import Observation, Kind; o=Observation(observation_id='o1', pensioner_id=123, kind=Kind.FaGCandidateFetch, source='search.py', source_version='1', run_id='r', pass_id='p1', caused_by=None, recorded_at='now', payload={'memorial_id': '50923719'}); print(o.to_dict())"` returns the full envelope

##### Manual Verification:
- [ ] Observations have stable JSON key order (no `extras` ordering surprises)

### Phase 2: Slice 2.3 — `WorkItem` ledger (L1-03)

**Goal:** work ledger tracks per-KS/per-pass/per-plan work units
independently of pensioner row presence. States: `ready | leased
| succeeded | retryable | blocked | terminal`. `not_before`
enforces cooldowns.

#### Phase 2: Slice 2.3: Changes Required:

##### 1. scripts/blackboard/schema.py

**File**: scripts/blackboard/schema.py
**Changes**: MODIFY — add `WorkItem` dataclass + `WorkState` enum
+ `WorkAttempt` record.

##### 2. tests/test_state_schema.py

**File**: tests/test_state_schema.py (existing)
**Changes**: MODIFY — assert WorkItem round-trip and state
transitions (e.g. `succeeded` is terminal; `retryable` records
`not_before`).

#### Phase 2: Slice 2.3: Success Criteria:

##### Automated Verification:
- [ ] `python -c "from scripts.blackboard.schema import WorkItem, WorkState, WorkAttempt; w=WorkItem(work_id='w1', pensioner_id=123, knowledge_source='FaGScraper', plan_id='p1', pass_id='1', input_revision=1, state=WorkState.LEASED, attempt=1, not_before=None, leased_by='proc1', completed_at=None); assert w.state == WorkState.LEASED"` succeeds

##### Manual Verification:
- [ ] `not_before` field supports timezone-aware datetime objects and ISO 8601 strings

### Phase 2: Slice 2.4 — `BlackboardStore` durable adapter (L5-01)

**Goal:** `BlackboardStore.append_observation`, `enqueue_work`,
`claim_work`, `complete_work`, `set_provider_not_before`,
`read_since`, `save_projection_cursor`, plus SQLite WAL adapter
implementation. JSONL adapter remains available as a fallback.

#### Phase 2: Slice 2.4: Changes Required:

##### 1. scripts/blackboard/store.py (NEW)

**File**: scripts/blackboard/store.py
**Changes**: NEW — `BlackboardStore` Protocol, `SqliteBlackboardStore`
implementation (default), `JsonlBlackboardStore` (fallback for
CI/test). Methods: `open(path)`, `append_observation(obs)`,
`enqueue_work(item)`, `claim_work(knowledge_source, lease_seconds)`
with `not_before` honor and stale-lease reclaim, `complete_work
(work_id, status, observation_ids)`, `set_provider_not_before
(provider, until)`, `read_since(cursor)`, `save_projection_cursor
(cursor)`, `check()` (returns `StateCheckResult`).
**SQLite durability pinning** (required for `kill -9` survival):
- `journal_mode=WAL`
- `synchronous=NORMAL`
- `isolation_level=None` (autocommit) with explicit
  `BEGIN IMMEDIATE` per append
- fsync via `con.commit()` (WAL mode flushes the WAL file but
  relies on `PRAGMA synchronous` for full durability); document
  this in the module docstring.

##### 2. tests/test_blackboard_store.py (NEW)

**File**: tests/test_blackboard_store.py
**Changes**: NEW — 6-8 tests covering append/claim/complete/lease
reclaim/provider cooldown/projection cursor. Use `tmp_path`
for SQLite isolation; mock the JSONL adapter for fallback tests.

#### Phase 2: Slice 2.4: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_blackboard_store.py -q` passes
- [ ] `python -c "from scripts.blackboard.store import BlackboardStore, SqliteBlackboardStore, JsonlBlackboardStore; print('ok')"` succeeds
- [ ] `pytest tests/ -m "not integration" -q` passes (existing tests not broken)

##### Manual Verification:
- [ ] Open a store, append 3 observations, kill -9 the process, reopen — observations survive
- [ ] `claim_work` honors `not_before` (no work returned before time)

### Phase 2: Slice 2.5 — `QueryPlan` envelope (L5-02 partial)

**Goal:** `QueryPlan(plan_id, pensioner_id, strategy, params, scope,
reason, estimated_requests, policy_version)` is the typed plan
shape used by all Knowledge Sources.

#### Phase 2: Slice 2.5: Changes Required:

##### 1. scripts/blackboard/schema.py

**File**: scripts/blackboard/schema.py
**Changes**: MODIFY — add `QueryPlan` dataclass + `PlanScope` enum
(`US` | `OK` | `Global` | `MemorialDetail` | etc.).

#### Phase 2: Slice 2.5: Success Criteria:

##### Automated Verification:
- [ ] `python -c "from scripts.blackboard.schema import QueryPlan, PlanScope; p=QueryPlan(plan_id='plan-7d3a', pensioner_id=123, strategy='B1-exact', params={'firstname':'William'}, scope=PlanScope.OK, reason='Exact sniper.', estimated_requests=1, policy_version='1'); print(p.to_dict())"` outputs the full plan

##### Manual Verification:
- [ ] `params` is `dict[str, str|int|float|bool]`; complex values raise at construction

### Phase 2: Slice 2.6 — Non-destructive snapshots (L5-03)

**Goal:** checkpoint snapshot writes are transactional with
hash/size verification, fsync file and directory, and the
named snapshot is preserved (not consumed) by rollback. Under
append-only store, the projection cursor replaces os.replace
behavior; legacy file-snapshot path remains for disaster
recovery.

#### Phase 2: Slice 2.6: Changes Required:

##### 1. scripts/pipeline/checkpoint.py

**File**: scripts/pipeline/checkpoint.py
**Changes**: MODIFY — `write_checkpoint_snapshot` writes to temp,
computes SHA-256, fsyncs temp + directory, `os.replace` to final
name; writes a sibling `<name>.meta.json` with `created_at`,
`record_count`, `sha256`, `policy_version`; `rollback_to_checkpoint`
copies the snapshot to state.jsonl (does not consume); records
rollback event in Blackboard; cursor-based rollback path takes
precedence.

##### 2. tests/test_checkpoint_rollback.py (existing)

**File**: tests/test_checkpoint_rollback.py
**Changes**: MODIFY — add 2 new tests:
- `test_write_checkpoint_creates_meta_json` — assert sibling
  meta file exists with sha256 and record_count.
- `test_rollback_does_not_consume_snapshot` — after rollback,
  the original snapshot file still exists with same content.

#### Phase 2: Slice 2.6: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_checkpoint_rollback.py -q` passes (existing 9 tests + 2 new)
- [ ] `python -c "from scripts.pipeline.checkpoint import write_checkpoint_snapshot, rollback_to_checkpoint; print('ok')"` succeeds

##### Manual Verification:
- [ ] Take a snapshot, write a manifest event "rollback-to-ckpt-X", verify the manifest ledger records it; snapshot file still exists

### Phase 2: Slice 2.7 — Atomic migration (L6-04)

**Goal:** `scripts/pipeline/rename_to_ok_names.py` is restartable
and atomic; write destination to temp, hash-verify, then
`os.replace`; record migration manifest event.

#### Phase 2: Slice 2.7: Changes Required:

##### 1. scripts/pipeline/rename_to_ok_names.py

**File**: scripts/pipeline/rename_to_ok_names.py
**Changes**: MODIFY — write destination + meta to `*.tmp`, hash
each (SHA-256), fsync, then `os.replace`; record migration
manifest event with source/destination hashes and record count;
re-run detects completed/partial states safely.

##### 2. tests/test_pipeline_migration.py (NEW)

**File**: tests/test_pipeline_migration.py
**Changes**: NEW — 3 tests covering atomic-write success, partial-
state re-run resume, and hash mismatch detection.

#### Phase 2: Slice 2.7: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_pipeline_migration.py -q` passes
- [ ] `python -c "import inspect, scripts.pipeline.rename_to_ok_names as m; src=inspect.getsource(m); assert 'tmp' in src and 'os.replace' in src"` confirms atomic write present

##### Manual Verification:
- [ ] Dry-run `--dry-run` against a fake state directory prints correct plan and writes nothing

### Phase 2: Plan History

- Phase 2: Blackboard contracts and durable local store — pending

## Phase 3: Unified Evidence and Decision Policy

**Goal:** scoring and decision policy become source-neutral,
versioned, and runnable offline from Blackboard observations.

**Depends on:** Phase 2.
**Effort:** L. **Blast radius:** cross-module.
**Findings (6):** L2-02, L2-03, L2-04, L2-05, L4-02, L6-02.

### Phase 3: Overview

This phase extracts pure decision logic from FaG and CGR
adapters. Slices ship in dependency order: `NameEvidence` first;
then `CandidateScorer`; then `DecisionPolicy`; then `CGRMatchEvidence`;
then `FellegiSunterMatcher` rewrite; then evaluation harness.

### Phase 3: Slice 3.1 — `NameEvidence` model (L2-04)

**Goal:** one shared `NameEvidence` extractor feeding scorer,
CGR match, dedup, and BOTH MATCH.

#### Phase 3: Slice 3.1: Changes Required:

##### 1. scripts/matching/name_evidence.py (NEW)

**File**: scripts/matching/name_evidence.py
**Changes**: NEW — `NameEvidence` dataclass with normalized values
+ signals (exact, jaro_winkler, metaphone, nysiis, soundex, prefix,
initial). `extract_name_evidence(first_a, last_a, first_b, last_b)`
helper.

##### 2. scripts/matching/phonetic_match.py, scripts/matching/both_match.py

**File**: scripts/matching/phonetic_match.py
**Changes**: MODIFY — `combined_name_score` and similar
adopt `NameEvidence`; deprecate duplicate ad hoc normalization.

**File**: scripts/matching/both_match.py
**Changes**: MODIFY — `_normalise_name` and `_names_match`
delegate to `NameEvidence`; delete duplicated heuristic.

#### Phase 3: Slice 3.1: Success Criteria:

##### Automated Verification:
- [ ] `python -c "from scripts.matching.name_evidence import extract_name_evidence, NameEvidence; e = extract_name_evidence('William', 'Looney', 'Will', 'Loony'); print(e.signals)"` outputs the seven signals
- [ ] `pytest tests/test_matching/test_name_evidence.py -q` passes
- [ ] Existing phonetic/both_match tests still pass

##### Manual Verification:
- [ ] Two records with the same normalized names but different raw spellings produce identical `NameEvidence`

### Phase 3: Slice 3.2 — `CandidateScorer` extraction (L2-02)

**Goal:** scoring math moves under `matching/candidate_scoring.py`
consuming `PensionerSnapshot` + `CandidateObservation`; the
FaG adapter normalizes raw candidate to domain observation.

#### Phase 3: Slice 3.2: Changes Required:

##### 1. scripts/matching/candidate_scoring.py (NEW)

**File**: scripts/matching/candidate_scoring.py
**Changes**: NEW — `PensionerSnapshot`, `CandidateObservation`,
`score_candidate(snapshot, candidate) -> (float, ScoreBreakdown)`.
Pure function; no Playwright/HTML imports.

##### 2. scripts/fag/scoring.py

**File**: scripts/fag/scoring.py
**Changes**: MODIFY — becomes a thin adapter that normalizes
FaG candidate to `CandidateObservation`, builds `PensionerSnapshot`
from local pensioner, calls `score_candidate`; preserves
`_in_acw_window` sentinel (`_impossible_date`).

##### 3. tests/test_candidate_scoring.py (NEW)

**File**: tests/test_candidate_scoring.py
**Changes**: NEW — 8-10 tests covering all features
(last/first/middle/OK_burial/state/veteran/death), ACW window
gating, slug parsing, and edge cases (missing name parts).

#### Phase 3: Slice 3.2: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_candidate_scoring.py -q` passes
- [ ] `pytest tests/test_fag_parser_constants.py -q` passes
- [ ] `pytest tests/test_state_names_module_level.py -q` passes (outlier_classifier still works)

##### Manual Verification:
- [ ] `python -c "from scripts.matching.candidate_scoring import score_candidate; from scripts.matching.candidate_scoring import PensionerSnapshot, CandidateObservation; r, b = score_candidate(PensionerSnapshot(...), CandidateObservation(...)); print(round(r,3), b)"` runs offline

### Phase 3: Slice 3.3 — `DecisionPolicy` consolidation (L2-03)

**Goal:** one versioned `DecisionPolicy` owns weights, thresholds,
dominance gap, status enum, refinement eligibility. Persists
`policy_version` on every score/verdict; projector recomputes
current verdict from observations.

#### Phase 3: Slice 3.3: Changes Required:

##### 1. scripts/matching/decision_policy.py (NEW)

**File**: scripts/matching/decision_policy.py
**Changes**: NEW — `DecisionPolicy(policy_version, weights,
auto_accept_threshold, auto_accept_gap, dominance_gap,
status_enum, refinement_eligibility)`; `derive_status(policy,
best_score, fag_status, second_score)` returns canonical status.
Import from `scripts.pipeline.scoring_constants` for status enum.

##### 2. scripts/pipeline/scoring_constants.py

**File**: scripts/pipeline/scoring_constants.py
**Changes**: MODIFY — remove duplicated thresholds; delegate to
`decision_policy`. Existing callers continue to work.

##### 3. tests/test_decision_policy.py (NEW)

**File**: tests/test_decision_policy.py
**Changes**: NEW — round-trip, status derivation rules, threshold
boundaries, dominance gap, refinement eligibility.

#### Phase 3: Slice 3.3: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_decision_policy.py -q` passes
- [ ] `pytest tests/test_outlier_classifier.py -q` passes (uses policy)
- [ ] `python -c "from scripts.matching.decision_policy import DecisionPolicy, derive_status; p=DecisionPolicy(policy_version='1', ...); print(derive_status(p, 0.92, 'auto_accept', None))"` outputs `auto_accept`

##### Manual Verification:
- [ ] Replay from observations with `policy_version='1'` produces same verdict as live run with same policy

### Phase 3: Slice 3.4 — `CGRMatchEvidence` unification (L4-02)

**Goal:** one shared `CGRMatchEvidence` extractor; CGR Corroborator
and strict CGR Deduplicator apply explicit versioned policy.
Delete malformed `match_pensioner_to_cgr` adapter call in
`cgr_fag_dedup.py`.

#### Phase 3: Slice 3.4: Changes Required:

##### 1. scripts/cgr/match_evidence.py (NEW)

**File**: scripts/cgr/match_evidence.py
**Changes**: NEW — `CGRMatchEvidence` extractor sharing
`NameEvidence`; `match_strength(pensioner, cgr_row, policy)` returns
typed strength; `same_person(rec_a, rec_b, policy)` returns bool.

##### 2. scripts/cgr/cgr_matcher.py, cgr_dedup.py, cgr_fag_dedup.py

**File**: scripts/cgr/cgr_matcher.py
**Changes**: MODIFY — `match_pensioner_to_cgr` returns a typed
`MatchResult` (not just a list); uses `NameEvidence` + `CGRMatchEvidence`.

**File**: scripts/cgr/cgr_dedup.py
**Changes**: MODIFY — `same_person` calls CGRMatchEvidence helper.

**File**: scripts/cgr/cgr_fag_dedup.py
**Changes**: MODIFY — `match_strength` (the 4-arg one inside
`classify_pensioner`) consumes `CGRMatchEvidence`; fix the malformed
`matches, _ = match_pensioner_to_cgr(...)` unpacking.

##### 3. tests/test_cgr_match_evidence.py (NEW)

**File**: tests/test_cgr_match_evidence.py
**Changes**: NEW — 5-6 tests covering strong/medium/weak/none
buckets, year match, unit match, year-conflict demotion.

#### Phase 3: Slice 3.4: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_cgr_match_evidence.py -q` passes
- [ ] `pytest tests/test_cgr_fag_dedup.py -q -m "not integration"` passes
- [ ] `python -c "from scripts.cgr.cgr_fag_dedup import classify_pensioner; classify_pensioner({'pensioner_last':'Looney'}, [{'last_name':'Looney'}])"` returns a dict (does not raise `TypeError`)

##### Manual Verification:
- [ ] CGR dedup against a saved state file with `policy_version='1'` reproduces the saved outcomes

### Phase 3: Slice 3.5 — `FellegiSunterMatcher` rewrite (L2-05)

**Goal:** actual Fellegi-Sunter m/u linkage producing explainable
per-field weights, with versioned model provenance.

#### Phase 3: Slice 3.5: Changes Required:

##### 2. tests/test_fellegi_sunter.py (existing)

**File**: tests/test_fellegi_sunter.py
**Changes**: RETIRED — the existing tests assert against the
`LogisticRegression`-based artifact load path. After Slice 3.5's
`fellegi_sunter.py` MODIFY, those tests would silently regress
against the new Fellegi-Sunter m/u semantics. Add CHANGELOG
entry: "Test: retired `tests/test_fellegi_sunter.py` (replaced by
`tests/test_fellegi_sunter_real.py`)."

##### 3. scripts/matching/fellegi_sunter.py

**File**: scripts/matching/fellegi_sunter.py
**Changes**: MODIFY — replace the `LogisticRegression` body with
actual Fellegi-Sunter m/u training; versioned `MatchModel`
artifact with `model_version`, `feature_schema`, `trained_at`,
`feature_count`; `predict(pensioner, cgr_vet) -> (probability,
evidence)`; restrict `load()` to operator-owned local paths.

##### 2. tests/test_fellegi_sunter_real.py (NEW)

**File**: tests/test_fellegi_sunter_real.py
**Changes**: NEW — train a small model on synthetic data; verify
m/u values differ between matching and non-matching pairs; verify
artifact round-trips; verify old (pickled Logistic) artifact
triggers migration warning.

#### Phase 3: Slice 3.5: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_fellegi_sunter_real.py -q` passes
- [ ] `python -c "from scripts.matching.fellegi_sunter import FellegiSunterMatcher, MatchModel; m=MatchModel(model_version='1', feature_schema=[], m={}, u={}, trained_at='now'); p, ev = FellegiSunterMatcher().predict_with_evidence({}, {}, m); print(p, ev)"` works
- [ ] `grep -n "LogisticRegression" scripts/matching/fellegi_sunter.py` returns no matches

##### Manual Verification:
- [ ] Saved artifact reloads and produces same scores for known inputs

### Phase 3: Slice 3.6 — Evaluation harness (L6-02)

**Goal:** one evaluation harness consumes actual `StrategySpec`,
name/score evidence, `DecisionPolicy`, and Blackboard observations.
Throwaway validation/analysis scripts retire or migrate to
`scripts.analysis/`.

#### Phase 3: Slice 3.6: Changes Required:

##### 1. scripts/evaluation/__init__.py (NEW package)

**File**: scripts/evaluation/__init__.py
**Changes**: NEW — package init.

##### 2. scripts/evaluation/evaluator.py (NEW)

**File**: scripts/evaluation/evaluator.py
**Changes**: NEW — `evaluate(plan, snapshot, observations, policy) -> EvalResult`;
`run_benchmark(plan_set, fixture_path, policy)`; CLI `main()` for
offline evaluation.

##### 3. scripts/ingest/validate_v5_ladder.py

**File**: scripts/ingest/validate_v5_ladder.py
**Changes**: MODIFY — replace shadow slug parser + Soundex with
`from scripts.matching.name_evidence import …`; replace shadow
strategy predicates with `from scripts.search.strategies import …`;
move CLI to `main()` so import is side-effect-free; archive
the duplicate `analysis/analyze_local_db.py`, `analyze_slug_shapes.py`,
`match_broadened_to_local.py` after lessons codified (or keep under
`analysis/` for historical comparison only).

##### 4. tests/test_evaluation_harness.py (NEW)

**File**: tests/test_evaluation_harness.py
**Changes**: NEW — 4-5 tests covering fixture loading, plan
emission, evaluation result, hit-rate computation.

#### Phase 3: Slice 3.6: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_evaluation_harness.py -q` passes
- [ ] `python -m scripts.evaluation.evaluator --help` exits 0
- [ ] `pytest tests/ -m "not integration" -q` passes (existing 1002 minus retirements + new tests)

##### Manual Verification:
- [ ] Run `python -m scripts.evaluation.evaluator` against a saved state file; hit-rate within 1pp of the 88% ground truth

### Phase 3: Plan History

- Phase 3: Unified evidence and decision policy — pending

## Phase 4: Provider Safety and Browser Lifecycle

**Goal:** every FaG request crosses one durable throttle/
cooldown/session seam; process-tree RSS measured correctly;
parser defects fixed.

**Depends on:** Phase 2.
**Effort:** L. **Blast radius:** cross-module.
**Findings (6):** L3-02, L3-03, L3-05, L3-07, L4-04, L6-03.

### Phase 4: Overview

This phase builds the `RequestGate` and `BrowserSession` deep
modules that the Web Scraper and Spouse Knowledge Sources will
share in Phase 6. Slices ship in dependency order:
`RequestGate` first, then `BrowserSession`, then response
classifier, then process-tree RSS, then spouse retrieval
integration, then probe canonicalization.

### Phase 4: Slice 4.1 — `RequestGate` (L3-02)

**Goal:** process-wide `RequestGate.acquire(request_kind)` with
floor, adaptive penalty, persisted cooldown, jitter policy,
metrics; never bypass.

#### Phase 4: Slice 4.1: Changes Required:

##### 1. scripts/fag/request_gate.py (NEW)

**File**: scripts/fag/request_gate.py
**Changes**: NEW — `RequestGate` class with `acquire(request_kind) ->
Token`; `acquire` waits monotonic now-last_request_at ≥ throttle;
honors provider `not_before`; records bot-wall cooldown; emits
metrics.

##### 2. tests/test_intra_strategy_throttle.py (existing)

**File**: tests/test_intra_strategy_throttle.py
**Changes**: MODIFY — extend to assert gate invocation; existing
throttle assertion preserved.

#### Phase 4: Slice 4.1: Success Criteria:

##### Automated Verification:
- [ ] `python -c "from scripts.fag.request_gate import RequestGate; g=RequestGate.default_fag(); t=g.acquire('search'); assert t is not None"` succeeds
- [ ] `pytest tests/test_intra_strategy_throttle.py -q` passes

##### Manual Verification:
- [ ] Two consecutive `acquire()` calls honor the 2.5s floor in live time

### Phase 4: Slice 4.2 — `BrowserSession` consolidation (L3-05)

**Goal:** single deep `BrowserSession` owns stealth, warmup,
gated navigation, page→context→browser→Playwright teardown,
reset, and target-closed recovery. Absorb `pw_session.py` and
`fag_browser.py`'s lifecycle. Delete `pw_session.py`.

#### Phase 4: Slice 4.2: Changes Required:

##### 1. scripts/fag/browser_session.py (NEW)

**File**: scripts/fag/browser_session.py
**Changes**: NEW — `BrowserSession` with `start()`, `navigate(url,
gate_token)`, `reset()`, `close()`, event hooks; full
page→context→browser→Playwright teardown in `close()` and `reset()`.

##### 2. scripts/fag/fag_browser.py

**File**: scripts/fag/fag_browser.py
**Changes**: MODIFY — `make_fag_search_fn` uses `BrowserSession`; preserve
public function signature.

##### 3. scripts/fag/pw_session.py

**File**: scripts/fag/pw_session.py
**Changes**: DELETE (absorbed into BrowserSession).

##### 4. tests/test_browser_session_teardown.py (NEW)

**File**: tests/test_browser_session_teardown.py
**Changes**: NEW — 1 test `test_close_calls_teardown_in_reverse_order`
mocking Playwright primitives; spy on `page.close`,
`context.close`, `browser.close`, `pw_cm.__exit__`; assert
page closed first, then context, then browser, then Playwright
context manager exits. Reverse-order enforcement is critical
because Playwright's Python wrappers hold frame references; a
leak in any layer adds to RSS.

#### Phase 4: Slice 4.2: Success Criteria:

##### Automated Verification:
- [ ] `[ ! -f scripts/fag/pw_session.py ] && echo gone` reports `gone`
- [ ] `pytest tests/test_intra_strategy_throttle.py -q` passes
- [ ] `pytest tests/test_browser_session_teardown.py -q` passes
- [ ] `python -c "from scripts.fag.browser_session import BrowserSession; print('ok')"` succeeds

##### Manual Verification:
- [ ] `python -c "from scripts.fag.fag_browser import make_fag_search_fn; fn = make_fag_search_fn(throttle=0.1); print(fn)"` returns a closure (no crash)

### Phase 4: Slice 4.3 — Response classifier + persisted cooldown (L3-03)

**Goal:** dedicated `ResponseClassifier` posts `BotWallObserved`
observations; scheduler sets durable provider-wide `not_before`,
pauses all FaG work, exposes manual-release path for escalated
challenge.

#### Phase 4: Slice 4.3: Changes Required:

##### 1. scripts/fag/response_classifier.py (NEW)

**File**: scripts/fag/response_classifier.py
**Changes**: NEW — `ResponseClassifier.classify(response, body,
title, url) -> Classification`; returns `CloudflareChallenge | RateLimit1015
| NormalPage | ErrorPage`; no sleeps; pure.

##### 2. tests/test_response_classifier.py (NEW)

**File**: tests/test_response_classifier.py
**Changes**: NEW — 6+ tests covering title patterns, body
markers, URL fragments, edge cases (empty body, redirected).

##### 3. scripts/fag/fag_browser.py, scripts/fag/search.py

**File**: scripts/fag/fag_browser.py
**Changes**: MODIFY — replace inline title/body heuristics with
`ResponseClassifier` calls; route `BotWallObserved` through
`RequestGate.set_provider_not_before`.

**File**: scripts/fag/search.py
**Changes**: MODIFY — same classifier swap; remove the
process-local `time.sleep(120.0)` hardcodes (use `RequestGate`).

#### Phase 4: Slice 4.3: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_response_classifier.py -q` passes
- [ ] `pytest tests/ -m "not integration" -q` passes

##### Manual Verification:
- [ ] On a real Cloudflare 1015 response, `ResponseClassifier` returns `RateLimit1015` and `RequestGate` records `not_before`

### Phase 4: Slice 4.4 — Process-tree RSS (L3-07)

**Goal:** memory observer measures Python plus owned browser
process tree; posts `MemoryPressureObserved`; scheduler triggers
reset or graceful checkpointed exit.

#### Phase 4: Slice 4.4: Changes Required:

##### 1. scripts/fag/rss_watchdog.py

**File**: scripts/fag/rss_watchdog.py
**Changes**: MODIFY — add `psutil`-free cross-platform child PID
detection; aggregate child RSS via `ctypes` on Windows,
`/proc/<pid>/statm` on Linux; report Python+aggregate; update
docstring to claim what the code measures.

##### 2. tests/test_rss_watchdog.py (NEW)

**File**: tests/test_rss_watchdog.py
**Changes**: NEW — 3 tests covering Python-only fallback,
child-aggregate happy path, threshold signaling.

#### Phase 4: Slice 4.4: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_rss_watchdog.py -q` passes
- [ ] `python -c "from scripts.fag.rss_watchdog import RSSWatchdog, make_default_watchdog; w = make_default_watchdog(); assert w is not None or w is None"` does not raise (depends on platform)

##### Manual Verification:
- [ ] `grep -n "GetCurrentProcess\|process_tree" scripts/fag/rss_watchdog.py` confirms both code paths present

### Phase 4: Slice 4.5 — Spouse retrieval unification (L4-04)

**Goal:** Deep Refiner emits memorial-detail plans; same
BrowserSession/RequestGate executes each request; spouse
fetch/parse/match posts durable observation.

#### Phase 4: Slice 4.5: Changes Required:

##### 1. scripts/cgr/spouse_compare.py

**File**: scripts/cgr/spouse_compare.py
**Changes**: MODIFY — use `BrowserSession.navigate` through
`RequestGate.acquire("memorial_detail")`; use
`ResponseClassifier` before reading HTML; append
`SpouseMatchObserved` observations instead of in-place
`spouse_match` mutation.

##### 2. tests/test_spouse_compare_through_gate.py (NEW)

**File**: tests/test_spouse_compare_through_gate.py
**Changes**: NEW — 4 tests covering gate invocation on every
navigation, classification before HTML read, observation
append behavior, no-throttle-burst check.

#### Phase 4: Slice 4.5: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_spouse_compare_through_gate.py -q` passes
- [ ] `pytest tests/test_spouse_compare.py -q -m "not integration"` passes (no behavior regression)

##### Manual Verification:
- [ ] When `FAG_AUTO_RELAX=1` and spouse scrape both run, no concurrent burst > 5 requests in < 2.5s

### Phase 4: Slice 4.6 — Probe canonicalization (L6-03)

**Goal:** probe imports canonical `BrowserSession`/`RequestGate`
and leak fix; the probe is one more `QueryPlan` set, not a
different transport seam.

#### Phase 4: Slice 4.6: Changes Required:

##### 1. scripts/analysis/_probe_fag_filter.py

**File**: scripts/analysis/_probe_fag_filter.py
**Changes**: MODIFY — refactor `main()` to build `QueryPlan`s and
use `BrowserSession` + `RequestGate` for navigation; remove
`sync_playwright` direct call.

##### 2. tests/test_probe_uses_canonical.py (NEW)

**File**: tests/test_probe_uses_canonical.py
**Changes**: NEW — 2 tests asserting the probe module imports
canonical `BrowserSession` and `RequestGate`, not `sync_playwright`
directly.

#### Phase 4: Slice 4.6: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_probe_uses_canonical.py -q` passes
- [ ] `grep -n "sync_playwright" scripts/analysis/_probe_fag_filter.py` returns 0 matches (only inside main via Session)

##### Manual Verification:
- [ ] `python scripts/analysis/_probe_fag_filter.py --help` exits 0

### Phase 4: Plan History

- Phase 4: Provider safety and browser lifecycle — pending

## Phase 5: Event-Guided Scheduler Skeleton

**Goal:** scheduler dispatches registered Knowledge Sources
from durable work, replacing the central god-loop.

**Depends on:** Phase 2.
**Effort:** M. **Blast radius:** cross-module.
**Findings (1):** L1-01.

### Phase 5: Overview

This phase builds the scheduler as a thin orchestrator that
loads Blackboard work, claims ready items, invokes eligible
Knowledge Sources, and atomically posts outputs/completion.
Phase 5 ships the skeleton and a single in-process sample
Knowledge Source. The full Knowledge Source migration happens
in Phase 6.

### Phase 5: Slice 5.1 — `BlackboardScheduler` + `KnowledgeSource`

**Goal:** small scheduler that owns claim, invoke, complete
loops. Initial Knowledge Source sample proves the seam.

#### Phase 5: Slice 5.1: Changes Required:

##### 1. scripts/blackboard/knowledge_source.py (NEW)

**File**: scripts/blackboard/knowledge_source.py
**Changes**: NEW — `KnowledgeSource` Protocol with `name`, `eligible
(work_item) -> bool`, `invoke(work_item, store, session) -> list
[Observation]`, `estimated_cost(work_item) -> int`.

##### 2. scripts/blackboard/scheduler.py (NEW)

**File**: scripts/blackboard/scheduler.py
**Changes**: NEW — `BlackboardScheduler(store, lease_seconds=30)`;
`register(ks)`; `run(max_iterations=None)` claims ready work,
invokes eligible KS, posts outputs, atomically completes;
stale-lease reclaim every N iterations.

##### 3. scripts/knowledge/__init__.py (NEW, empty package)

**File**: scripts/knowledge/__init__.py
**Changes**: NEW — package init.

##### 4. scripts/knowledge/ingestion.py (NEW, sample KS)

**File**: scripts/knowledge/ingestion.py
**Changes**: NEW — `IngestionKS(KnowledgeSource)` loads
ok_pensioners.json, posts one `PensionerImported` observation
per pensioner. Demonstrates the seam.

##### 5. tests/test_blackboard_scheduler.py (NEW)

**File**: tests/test_blackboard_scheduler.py
**Changes**: NEW — 4 tests covering claim/invoke/complete,
eligibility, stale-lease reclaim, no-eligible-ks idle.

#### Phase 5: Slice 5.1: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_blackboard_scheduler.py -q` passes
- [ ] `python -c "from scripts.blackboard.scheduler import BlackboardScheduler; from scripts.blackboard.knowledge_source import KnowledgeSource; print('ok')"` succeeds
- [ ] `python -c "from scripts.knowledge.ingestion import IngestionKS; print('ok')"` succeeds

##### Manual Verification:
- [ ] `scripts/pipeline/run_unified.py` can register the scheduler and call `run()` for one iteration without breaking the existing flow (CLI argument `no-op until Phase 6`)

### Phase 5: Plan History

- Phase 5: Event-guided scheduler skeleton — pending

## Phase 6: Typed Knowledge Sources and Multi-Pass Refinement

**Goal:** migrate ingestion, planning, FaG search, CGR
cross-reference, and refinement to autonomous typed Knowledge
Sources.

**Depends on:** Phases 3, 4, 5.
**Effort:** L. **Blast radius:** cross-module.
**Findings (7):** L1-04, L2-01, L3-01, L3-04, L4-01, L4-05, L6-01.

### Phase 6: Overview

This phase is the largest. Land one vertical flow first
(ingestion → regional plan → gated FaG scrape → candidate
observation → scorer → projection), then add CGR corroboration
and deep refinement. Each Knowledge Source gets its own
slice; refactor is incremental.

### Phase 6: Slice 6.1 — `RegionalPlannerKS` (L2-01, L1-04)

**Goal:** planner emits typed `QueryPlan`s from pensioner
evidence; no fake-pensioner adaptation.

#### Phase 6: Slice 6.1: Changes Required:

##### 1. scripts/knowledge/regional_planner.py (NEW)

**File**: scripts/knowledge/regional_planner.py
**Changes**: NEW — `RegionalPlannerKS` reads pensioner
observations + last known CGR match (if any), emits one
`QueryPlan` per pensioner with `PlanScope.US | OK | Global`,
appropriate `StrategySpec.plan(subject, evidence) -> QueryPlan`,
and `estimated_requests`.

##### 2. scripts/search/strategies.py

**File**: scripts/search/strategies.py
**Changes**: MODIFY — `StrategySpec.plan(subject, evidence) ->
QueryPlan | None` typed wrapper; existing `STRATEGIES` list
returns anonymous dicts today, becomes `QueryPlan` list.

##### 3. tests/test_regional_planner.py (NEW)

**File**: tests/test_regional_planner.py
**Changes**: NEW — 5 tests covering plan emission for typical
cases (exact name, last name only, with birth year, with death
year, with CGR-side widow info).

#### Phase 6: Slice 6.1: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_regional_planner.py -q` passes
- [ ] `pytest tests/test_year_filter_strategy.py tests/test_nickname_strategy.py tests/test_regiment_strategy.py -q` passes (existing strategy tests still work)
- [ ] `python -c "from scripts.search.strategies import StrategySpec, STRATEGIES; print(STRATEGIES[0][0])"` outputs the first ladder label

##### Manual Verification:
- [ ] Planner emits a plan for the first 5 OK pensioners; plans differ on scope

### Phase 6: Slice 6.2 — `FaGScraperKS` (L3-01, L3-04, L4-01, L4-05)

**Goal:** FaG Scraper executes one `QueryPlan`; BrowserSession +
RequestGate; posts `FaGCandidateFetch` observation. Also covers
`CGRFetcherKS` (L4-01) and durable CGR adapter (L4-05) in
combined slice.

#### Phase 6: Slice 6.2: Changes Required:

##### 1. scripts/knowledge/fag_scraper.py (NEW)

**File**: scripts/knowledge/fag_scraper.py
**Changes**: NEW — `FaGScraperKS` accepts one `QueryPlan`,
acquires `RequestGate.acquire('search')`, navigates through
`BrowserSession`, runs `parse_results_page`, appends
`FaGCandidateFetch` observations to Blackboard.

##### 2. scripts/knowledge/cgr_fetcher.py (NEW)

**File**: scripts/knowledge/cgr_fetcher.py
**Changes**: NEW — `CGRFetcherKS` fetches CGR search + vet
details, posts `CGRFetch` observations. Reuses L4-01 split
fetch/parse contract; raw HTML/response meta attached.

##### 3. scripts/fag/search.py

**File**: scripts/fag/search.py
**Changes**: MODIFY — `search_one_pensioner` reduces to a thin
adapter calling `FaGScraperKS`; one-plan behavior preserved for
backward compat during migration.

##### 4. scripts/cgr/cgr_client.py

**File**: scripts/cgr/cgr_client.py
**Changes**: MODIFY — split into `fetch(CGRRequest) ->
RawSourceObservation` and `parse(raw) -> CGRObservation`;
`CGRClient` thin wrapper for backward compat.

##### 5. scripts/cgr/cgr_enrich.py, cgr_ok_scraper.py

**File**: scripts/cgr/cgr_enrich.py
**Changes**: MODIFY — writes durable store; reuses L4-05
work-key semantics.

**File**: scripts/cgr/cgr_ok_scraper.py
**Changes**: MODIFY — `scrape_ok_cemeteries` becomes a thin
adapter that enqueues `CGRFetch` work items; durable
observation path replaces the per-cemetery append.

##### 6. tests/test_fag_scraper_ks.py, test_cgr_fetcher_ks.py (NEW)

**File**: tests/test_fag_scraper_ks.py
**Changes**: NEW — 4 tests covering one-plan execution,
gate invocation, observation append.

**File**: tests/test_cgr_fetcher_ks.py
**Changes**: NEW — 3 tests covering raw/parsed separation,
durable work-key behavior.

#### Phase 6: Slice 6.2: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_fag_scraper_ks.py tests/test_cgr_fetcher_ks.py -q` passes
- [ ] `pytest tests/test_search_fag_memory.py tests/test_country_filter.py -q` passes (legacy CLIs still work)
- [ ] `python -c "from scripts.knowledge.fag_scraper import FaGScraperKS; print(FaGScraperKS)"` succeeds

##### Manual Verification:
- [ ] First 5 OK pensioners through `FaGScraperKS` produce ≥ 5 `FaGCandidateFetch` observations
- [ ] One `QueryPlan` is consumed by exactly one scrape; no `dict` discards

### Phase 6: Slice 6.3 — `CandidateScorerKS` and `DeepRefinerKS` (L1-04)

**Goal:** Scorer consumes `FaGCandidateFetch` observations,
emits `ScoreObserved`; Deep Refiner reacts to low-score
ambiguity, emits new `QueryPlan`s with spouse/global/nickname
scopes within request budget.

#### Phase 6: Slice 6.3: Changes Required:

##### 1. scripts/knowledge/candidate_scorer.py (NEW)

**File**: scripts/knowledge/candidate_scorer.py
**Changes**: NEW — `CandidateScorerKS` reads `FaGCandidateFetch`
+ `PensionerImported`, runs `matching.candidate_scoring`, posts
`ScoreObserved`.

##### 2. scripts/knowledge/deep_refiner.py (NEW)

**File**: scripts/knowledge/deep_refiner.py
**Changes**: NEW — `DeepRefinerKS` reads `ScoreObserved` with
status in {ambiguous, too_many, no_results}, emits new
`QueryPlan`s (spouse, global, nickname, regiment). Uses
`PlanScope.MemorialDetail` for spouse requests.

##### 3. scripts/pipeline/leftover_investigation.py

**File**: scripts/pipeline/leftover_investigation.py
**Changes**: MODIFY — becomes a thin wrapper around
`DeepRefinerKS`.

##### 4. tests/test_candidate_scorer_ks.py, test_deep_refiner_ks.py (NEW)

**File**: tests/test_candidate_scorer_ks.py
**Changes**: NEW — 3 tests covering observation → score chain.

**File**: tests/test_deep_refiner_ks.py
**Changes**: NEW — 4 tests covering plan emission for ambiguous,
too_many, no_results, and budget-overflow no-op.

#### Phase 6: Slice 6.3: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_candidate_scorer_ks.py tests/test_deep_refiner_ks.py -q` passes
- [ ] `pytest tests/test_cgr_match_evidence.py -q` passes (scorer unit tests still pass)
- [ ] `python -c "from scripts.knowledge.deep_refiner import DeepRefinerKS; print(DeepRefinerKS)"` succeeds

##### Manual Verification:
- [ ] On 50 ambiguous pensioners, DeepRefiner emits ≤ 5 new `QueryPlan`s each (budget honored)

### Phase 6: Slice 6.4 — Ingestion via Blackboard (L6-01)

**Goal:** Ingestion posts raw/normalized `PensionerImported`
observations per ID with parser-version provenance; failed
work remains retryable.

#### Phase 6: Slice 6.4: Changes Required:

##### 1. scripts/ingest/scrape_digitalprairie.py

**File**: scripts/ingest/scrape_digitalprairie.py
**Changes**: MODIFY — splits fetch/parse/merge; per-ID work
enqueued via `BlackboardStore`; `IngestionKS` reuses fetch.

##### 2. scripts/ingest/fetch_pensioncard_pages.py

**File**: scripts/ingest/fetch_pensioncard_pages.py
**Changes**: MODIFY — emits `PensioncardPageFetch` observations
per pensioncard_id; cache becomes projection.

##### 3. tests/test_ingestion_ks.py (NEW)

**File**: tests/test_ingestion_ks.py
**Changes**: NEW — 4 tests covering fetch observation,
parser observation, retry on fetch error, dual-write
compatibility with existing cache.

#### Phase 6: Slice 6.4: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_ingestion_ks.py -q` passes
- [ ] `pytest tests/test_fetch_pensioncard_pages.py -q` passes (legacy behavior)
- [ ] `python scripts/ingest/scrape_digitalprairie.py --out-dir C:/tmp/dp --max-id 10 --no-merge` exits 0; observations written to Blackboard store

##### Manual Verification:
- [ ] Re-running the Ingestion with a partial cache skips completed IDs (resume works)

### Phase 6: Slice 6.5 — `ProjectionKS` and remove legacy writers (L3-04)

**Goal:** projection emits compatibility `state.jsonl` from
append-only observations; legacy `append_state` and
`JsonlStateRepository` writes retire (replaced by projection).

#### Phase 6: Slice 6.5: Changes Required:

##### 1. scripts/knowledge/projection_ks.py (NEW)

**File**: scripts/knowledge/projection_ks.py
**Changes**: NEW — `ProjectionKS` reads all observations, applies
`DecisionPolicy` to derive current verdict per pensioner,
emits `state.jsonl` byte-compatible projection. Uses
`StableKeyDict` for key order.

##### 2. scripts/fag/state_io.py

**File**: scripts/fag/state_io.py
**Changes**: MODIFY — `append_state` now raises
`RemovedInPhase7Error`; `state_io` becomes a thin shim for
non-Blackboard legacy callers with deprecation warning.

##### 3. tests/test_projection_ks.py (NEW)

**File**: tests/test_projection_ks.py
**Changes**: NEW — 4 tests covering determinism, byte-shape
compatibility, schema_version emission, policy version
change reproduces different verdict.

#### Phase 6: Slice 6.5: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_projection_ks.py -q` passes
- [ ] `pytest tests/test_state_repository.py -q` passes
- [ ] `python -c "from scripts.knowledge.projection_ks import ProjectionKS; print(ProjectionKS)"` succeeds

##### Manual Verification:
- [ ] Run a 5-pensioner smoke; `state.jsonl` from ProjectionKS matches the legacy shape byte-for-byte for the un-versioned fields

### Phase 6: Plan History

- Phase 6: Typed Knowledge Sources and multi-pass refinement — pending

## Phase 7: Projection and Review Migration

**Goal:** current rows, reports, DD/CGR/spouse badges, and
review export become disposable projections from Blackboard
facts; one deterministic projector.

**Depends on:** Phase 6.
**Effort:** L. **Blast radius:** cross-module/on-disk.
**Findings (2):** L4-03, L5-05.

### Phase 7: Overview

This phase finalizes the local-first contract. The projection
becomes the single source of current truth for `state.jsonl`,
`view.html`, reports, and sidecars. CGR/DD/spouse passes stop
mutating and only append observations.

### Phase 7: Slice 7.1 — One `ProjectionBuilder` (L5-05)

**Goal:** one deterministic projector in Python consumes
observations + DecisionPolicy and emits canonical review rows,
report facts, and badges. `view.html` renders projection;
does not normalize domain truth.

#### Phase 7: Slice 7.1: Changes Required:

##### 1. scripts/blackboard/projector.py (NEW)

**File**: scripts/blackboard/projector.py
**Changes**: NEW — `ProjectionBuilder` builds `(state_row,
report_stats, badges)` tuple from observations + policy;
deterministic; pure; testable.

##### 2. scripts/state_normalize.py, scripts/state/report_generator.py

**File**: scripts/state_normalize.py
**Changes**: MODIFY — delegates to `ProjectionBuilder`; backwards
compat aliases preserved for any external Python consumers.

**File**: scripts/state/report_generator.py
**Changes**: MODIFY — same delegate; counts/statuses computed
inside `ProjectionBuilder`.

##### 3. scripts/cgr/cgr_fag_dedup.py, dixiedata_match.py, spouse_compare.py

**File**: scripts/cgr/cgr_fag_dedup.py
**Changes**: MODIFY — append `CGRCorroborationObserved` only;
projection owns badge data.

**File**: scripts/cgr/dixiedata_match.py
**Changes**: MODIFY — append `DixieDataMatchObserved` only.

**File**: scripts/cgr/spouse_compare.py
**Changes**: MODIFY — append `SpouseMatchObserved` only.

##### 4. scripts/pipeline/dd_marker.py, run_unified.py

**File**: scripts/pipeline/dd_marker.py
**Changes**: MODIFY — projector merges `DixieDataMatchObserved`.

**File**: scripts/pipeline/run_unified.py
**Changes**: MODIFY — `result_to_dict` no longer writes
`spouse_match` in-place; instead projector reads
`SpouseMatchObserved` per pensioner and writes the
projection-shaped field.

##### 5. scripts/view.html

**File**: scripts/view.html
**Changes**: MODIFY — read `pensioner_record` from
`embedded-results-jsonl`; no business logic for status/badge;
pure render of projection. `loadFromText`/`applyLoaded` import
logic stays.

##### 6. tests/test_projection_determinism.py (NEW)

**File**: tests/test_projection_determinism.py
**Changes**: NEW — 4 tests: rebuild determinism, byte-shape
compatibility, multi-policy rerun, view round-trip.

#### Phase 7: Slice 7.1: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_projection_determinism.py -q` passes
- [ ] `pytest tests/test_view_html.py tests/test_view_unified.py -q` passes
- [ ] `pytest tests/test_dixiedata_match_j14.py tests/test_spouse_badge_j15.py -q` passes
- [ ] `python -c "import re; src=open('scripts/view.html', encoding='utf-8').read(); assert not re.search(r'\\.score\\s*=\\|\\bbadge\\s*=\\|\\bstatus\\s*=', src), 'view.html still derives score/badge/status'"` exits 0 (no business logic in view.html)
- [ ] `python -c "from scripts.blackboard.projector import ProjectionBuilder; print(ProjectionBuilder)"` succeeds

##### Manual Verification:
- [ ] Round-trip: load old `state.jsonl` into projector, emit new projection, diff against original — only schema_version field differs

### Phase 7: Slice 7.2 — Stop mutating canonical rows (L4-03)

**Goal:** CGR/DD/spouse post-passes append observations only;
projection owns mutable state; canonical rows become read-only
under Blackboard.

#### Phase 7: Slice 7.2: Changes Required:

##### 1. scripts/cgr/cgr_fag_dedup.py, scripts/cgr/dixiedata_match.py, scripts/cgr/spouse_compare.py

**File**: scripts/cgr/cgr_fag_dedup.py
**Changes**: MODIFY — `run_dedup` no longer rewrites
`results.jsonl`; emits `CGRCorroborationObserved` per pensioner.

**File**: scripts/cgr/dixiedata_match.py
**Changes**: MODIFY — `annotate_results_with_dd` no longer rewrites
state; emits `DixieDataMatchObserved`.

**File**: scripts/cgr/spouse_compare.py
**Changes**: MODIFY — `annotate_records` no longer rewrites
state; emits `SpouseMatchObserved`.

##### 2. tests/test_post_passes_no_mutation.py (NEW)

**File**: tests/test_post_passes_no_mutation.py
**Changes**: NEW — 3 tests asserting each post-pass no longer
mutates input state.

#### Phase 7: Slice 7.2: Success Criteria:

##### Automated Verification:
- [ ] `pytest tests/test_post_passes_no_mutation.py -q` passes
- [ ] `grep -n "JsonlStateRepository(state_path).replace_all\|state_repo.append" scripts/cgr/cgr_fag_dedup.py scripts/cgr/dixiedata_match.py scripts/cgr/spouse_compare.py` returns 0 production matches
- [ ] `pytest tests/ -m "not integration" -q` passes

##### Manual Verification:
- [ ] On a saved state file, run all 3 post-passes with `BlackboardStore` enabled; no field on existing rows changes; new observations exist

### Phase 7: Plan History

- Phase 7: Projection and review migration — pending

## Ordering Constraints

- Phase 1 has no dependencies.
- Phase 2 depends on Phase 1 (canonical imports must exist before
  Blackboard files import them).
- Phases 3, 4, 5 all depend on Phase 2 (Blackboard contracts and
  store are prerequisites for typed evidence, request gate, and
  scheduler).
- Phase 6 depends on Phases 3, 4, 5 (scoring policies, request
  safety, scheduler all required for Knowledge Sources).
- Phase 7 depends on Phase 6 (Knowledge Sources must emit
  observations for the projector to consume).

Slices within a phase are sequential; slices across phases are
blocked by the phase-level dependency.

## Verification Notes

### Cross-phase integrity

- `python -c "import ast, pathlib; bad=[str(p) for p in pathlib.Path('scripts').rglob('*.py') for n in ast.parse(p.read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and (not (ast.get_docstring(n) and ast.get_docstring(n).splitlines()[0].strip().startswith(n.name))) and not n.name.startswith('_') and n.col_offset == 0]; assert not bad, bad"` — L7 docstring convention: every non-private top-level function's docstring first line must start with the function name (CONTEXT.md L7); exits 0
- `python -c "from scripts.blackboard.schema import RunManifest, Observation, WorkItem, QueryPlan; print('ok')"` — combined schema import smoke
- `python -c "import ast, pathlib; [ast.parse(open(p).read()) for p in __import__('pathlib').Path('scripts').rglob('*.py')]"` — every Python file parses
  (catches L3-08 `NameError` and L5-06 `NameError`).
- `python -m pytest --collect-only -q -m "not integration"` — 1,002
  tests collected; 1 deselected. Compare against pre-plan baseline
  after each phase to see how many tests were added, modified,
  or retired.

### Phase 1 checks

- Parser no longer raises `NameError` on import:
  `python -c "from scripts.fag.parser import log, PWTimeout"`.
- `grep -rn "from scripts\.search_fag import\|from scripts\.run_unified import" scripts/fag scripts/pipeline scripts/analysis` returns no matches.
- CGR limit enforced: `python scripts/cgr/cgr_ok_scraper_run.py --state OK --limit-cemeteries 1 --out C:/tmp/smoke.jsonl` returns after 1 cemetery.
- Strict mode raises: `python -c "from scripts.state.repository import JsonlStateRepository, CorruptStateError; import tempfile, pathlib; p=pathlib.Path(tempfile.mktemp()); p.write_text('{\"a\":1}\\nnot json\\n', encoding='utf-8'); list(JsonlStateRepository(p).iter_all(strict=True))"` raises `CorruptStateError`.

### Phase 2 checks

- Blackboard store survives kill: open store, append 3
  observations, kill -9, reopen — observations present.
- `python -c "from scripts.blackboard.schema import RunManifest, Observation, WorkItem, QueryPlan; print('ok')"` succeeds.
- Snapshot rollback preserves source: take snapshot, write
  manifest event, verify snapshot file still exists with same
  SHA-256.
- Migration: dry-run on fake state dir prints plan and writes
  nothing.

### Phase 3 checks

- Live and replay under same `policy_version='1'` produce same
  verdict on a saved state file.
- `grep -n "LogisticRegression" scripts/matching/fellegi_sunter.py` returns 0 matches.
- Evaluation harness CLI: `python -m scripts.evaluation.evaluator
  --help` exits 0.

### Phase 4 checks

- Two `RequestGate.acquire()` calls in a row honor the 2.5s
  floor in live time.
- Spouse scrape through gate: no concurrent burst > 5 requests
  in < 2.5s.
- RSS watchdog reports Python+aggregate.

### Phase 5 checks

- `BlackboardScheduler.run()` with one registered sample
  Knowledge Source completes and posts observations.
- Stale lease reclaim test: manually expire a lease, run
  scheduler one iteration, claim succeeds.

### Phase 6 checks

- Scraper executes one plan; no fake-pensioner adaptation
  remains in follow-up.
- `python -c "from scripts.knowledge.projection_ks import
  ProjectionKS"` succeeds.
- `state.jsonl` from ProjectionKS matches legacy shape
  byte-for-byte for un-versioned fields (round-trip test).

### Phase 7 checks

- Projection rebuilt from same observation cursor is
  deterministic.
- `view.html` reads projection only; no business logic.
- `grep -n "JsonlStateRepository.*replace_all\|state_repo\.append" scripts/cgr/cgr_fag_dedup.py scripts/cgr/dixiedata_match.py scripts/cgr/spouse_compare.py` returns 0 matches.

## Performance Considerations

- Blackboard store: SQLite WAL with `synchronous=NORMAL` for
  durability vs latency; per-pensioner observation append is
  one transaction. Expected: < 5ms per append.
- RequestGate: monotonic timing only; no scheduler busy-wait.
- BrowserSession teardown: page→context→browser→Playwright in
  sequence; per-reset cost ~2s. Reset cadence unchanged
  (`reset_browser_every=250`).
- Projection rebuild: linear in observation count; expected
  < 1s for 7,758 pensioners.

## Migration Notes

- Each phase is a single PR. PR description template:
  "Phase N — <name>. Closes findings L<>-NN. Migration: <list>.
  Tests: <added>/<modified>/<retired>."
- Within a phase, multiple commits per slice are allowed if
  the slice is large; default is one commit per slice.
- `CHANGELOG.md` `[Unreleased]` block must be updated in the
  same commit as the code change. CHANGELOG item format: one
  bullet per finding closed.
- Test retirements: remove the test file entirely. Add a
  CHANGELOG entry: "Test: retired <name>.py (replaced by
  <new>)."
- Doc updates: `docs/agents/bug-catalog.md`, `docs/agents/adr/*`
  get updated to reference new contracts; do not edit
  `docs/learnings/run-*-learnings.md` (historical).
- Output deletion `output/test-batch-25/view.html` is user-owned;
  do not touch unless explicitly asked.

## Pattern References

- Issue #19 shim deletion:
  `CHANGELOG.md` "Refactor: delete 44 back-compat shim files in
  scripts/" entry; canonical home table.
- Issue #22 Repository pattern:
  `scripts/state/repository.py:100-148` (Protocol +
  `JsonlStateRepository`); `tests/test_state_repository.py:1-260`
  (test patterns).
- Atomic write: `scripts/state/repository.py:240-251`
  (`_atomic_write`).
- `BatchConfig` / `ScrapingConfig` dataclass pattern:
  `scripts/batch_config.py:50-68`;
  `scripts/cgr/cgr_ok_scraper.py:55-58`.
- L7 docstring convention: every public function starts with
  function name, names the contract, states failure modes.
  See `CONTEXT.md` L7.

## Developer Context

- Phase 1 slice 1.1: "Empty root facade now or phase 2?" → emptied
  in Phase 1 (developer chose); modeled after issue #19 precedent.
- Phase 1 strict mode: developer chose opt-in flag (preserves
  existing tests); new helper `check_state_then_read` to make
  strict checks ergonomic.
- Phase 1 cemetery limit: developer chose `ScrapingConfig` field
  (matches existing dataclass pattern).
- Phase 1 leak fix: developer chose canonical + delete root
  (keeps Playwright `.format()` compatibility intact).
- Phase 1 parser debug: developer chose drop calls + log
  warnings (keeps operational visibility; no behavior change).
- Phase 1 dead block: developer chose delete now (Phase 1
  compactness outweighs deferring to Phase 7).
- Phase 1 scope: developer chose stick to review's 7 findings
  (no drift from architecture review).
- Phase 1 slice shape: developer chose 7 single-finding slices
  (one micro-checkpoint per finding; max 3 review cycles per
  slice).
- Test plan: developer agreed that tests must evolve with
  architecture; some current tests will be retired when their
  contract is replaced (e.g. `test_unified_line_removed` and
  shim-import tests). Plan explicitly allows retirement.

## Plan Review (Step 8)

_Independent post-finalization review by artifact-code-reviewer and artifact-coverage-reviewer subagents. Findings triaged at Step 9._

| source   | plan-loc          | codebase-loc                | severity   | dimension             | finding   | recommendation   | resolution         |
| -------- | ----------------- | --------------------------- | ---------- | --------------------- | --------- | ---------------- | ------------------ |
| coverage | Pattern References §29 (L7 docstring) | <n/a> | blocker | verification-coverage | L7 docstring convention not enforced anywhere; many new public functions ship in Phases 2–7 | Add automated L7 AST check to `### Cross-phase integrity:` | applied: L7 AST check added to Cross-phase integrity; covers all new public functions in Phases 2–7 |
| code     | Phase 1 §1.2 (test_country_filter.py) | tests/test_country_filter.py:13 | blocker | codebase-fit | Plan says import from `scripts.fag.search` but `apply_location_filter` lives in `scripts.fag.filters` | Slice 1.2 §3 rewritten to import from `scripts.fag.filters` and `scripts.search.strategies` |
| code     | Phase 1 §1.2 (test_year_filter_strategy.py) | tests/test_year_filter_strategy.py:19 | blocker | codebase-fit | Same as above: `strategy_b1_exact` lives in `scripts.search.strategies` not `scripts.fag.search` | covered by B3 (pinned to single canonical path) |
| code     | Phase 1 §1.2 (fag_browser.py) | scripts/fag/fag_browser.py:33 | blocker | actionability | `setup_browser` and `warmup_session` are in `scripts/fag/search.py` but plan implies unqualified import works today only because the shim's `from ... import *` re-exports them. Removing the shim without explicit re-export in `scripts/fag/search.py` will break `fag_browser.py` | Slice 1.2 §1 rewritten with separate-line import; verification step added |
| code     | Phase 1 (overall) | <n/a> | blocker | scope | Files touched count says ~14 but actual file list has 18 distinct files | Files touched block rewritten to enumerate 18 files |
| code     | Phase 1 §1.1 (success criteria) | <n/a> | concern | actionability | Manual criterion `python scripts/search_fag.py --help (if shim still imported) does not pull scripts.pipeline.run_unified` self-contradicts with Slice 1.1's MODIFY (if shim is removed in Slice 1.1, this check passes; if shim remains, this check fails) | Manual criterion rewritten with shim-order note and `sys.modules` smoke fallback |
| code     | Phase 1 §1.6 (corrupt-state manual) | <n/a> | concern | code-quality | Uses deprecated `tempfile.mktemp()` (Python 3.12+ deprecation) | Manual criterion uses `NamedTemporaryFile` |
| code     | Phase 1 §1.2 (test_year_filter_strategy.py) | tests/test_year_filter_strategy.py:19 | concern | codebase-fit | Plan hedge `from scripts.search.strategies and/or scripts.fag.search` is ambiguous | Pin to one canonical path (`from scripts.search.strategies import …`) | covered by B3 (pinned to single canonical path) |
| code     | Phase 1 §1.5 (test_cgr_ok_scraper.py) | tests/test_cgr_ok_scraper.py:1 | concern | scope | Plan claims `(existing 15 tests + 2 new)` but file has ~17 tests; off-by-two | AST count confirms 15 test functions; criterion updated to "(existing 15 test functions + 2 new = 17)" |
| code     | Phase 1 §1.7 (success criterion) | scripts/pipeline/backfill_backlinks.py:90 | concern | code-quality | Manual criterion duplicates Automated load smoke; no incremental signal | Manual criterion now calls `backfill()` against tmp state and asserts `filled == 1` |
| code     | Phase 6 §6.2 (success criterion) | <n/a> | concern | codebase-fit | Typo: `FaqScraperKS` should be `FaGScraperKS` (NameError otherwise) | typo fixed to `FaGScraperKS` |
| code     | Phase 1 §1.6 (test_state_repository.py) | <n/a> | suggestion | scope | Plan says "(existing 28 tests + 3 new)" — actual file has ~24 tests; off-by-four | AST count confirms 27 test functions; criterion updated to "(existing 27 test functions + 3 new = 30)" |
| code     | Phase 3 §3.5 (fellegi_sunter.py) | scripts/matching/fellegi_sunter.py:1 | concern | codebase-fit | Plan rewrites fellegi_sunter to remove `LogisticRegression` but does not list `tests/test_fellegi_sunter.py` for MODIFY/RETIRE in Slice 3.5; new file `test_fellegi_sunter_real.py` may contradict | Slice 3.5 §2 added RETIRED note for `tests/test_fellegi_sunter.py` |
| code     | Phase 4 §4.2 (BrowserSession) | scripts/fag/fag_browser.py:33 | concern | actionability | Teardown order is sensitive but no test asserts reverse-order close | Slice 4.2 §4 added `tests/test_browser_session_teardown.py` with reverse-order assertion |
| code     | Phase 2 §2.4 (BlackboardStore) | <n/a> | concern | actionability | SQLite WAL `journal_mode`, `synchronous`, `isolation_level` not pinned; kill -9 may lose the last observation | Slice 2.4 §1 expanded with SQLite durability pinning (WAL/NORMAL/IMMEDIATE) |
| coverage | Verification Notes §8 | <n/a> | concern | verification-coverage | Combined `RunManifest, Observation, WorkItem, QueryPlan` import not asserted in any single slice | combined schema smoke added to Cross-phase integrity |
| coverage | Verification Notes §23 | <n/a> | concern | verification-coverage | `view.html` business-logic absence not asserted | Add `grep`/AST check to Phase 7 Slice 7.1 Automated | applied: Phase 7 Slice 7.1 Automated now has `view.html` business-logic grep |

Sort by severity (blocker → concern → suggestion). All 17 findings have
a `source` of `code` (artifact-code-reviewer) or `coverage`
(artifact-coverage-reviewer).

## References

- Parent review: `.rpiv/artifacts/architecture-reviews/2026-07-18_23-33-38_python-local-first-blackboard.md`
- CONTEXT.md (laws L1–L8): `CONTEXT.md`
- Cross-layer contract: `docs/agents/cross-layer-contract.md`
- Issue #19 precedent: CHANGELOG.md "Refactor: delete 44
  back-compat shim files in scripts/"
- Issue #22 pattern: CHANGELOG.md "Iteration on issue #22"
- ADR 0001 (Playwright + stealth): `docs/agents/adr/0001-playwright-stealth-over-requests.md`
- ADR 0006 (reversibility flags): `docs/agents/adr/0006-reversibility-flags.md`
- Bug catalog (per-layer patterns): `docs/agents/bug-catalog.md`
- Pattern-finder report: see Step 2 output
