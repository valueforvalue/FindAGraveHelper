---
date: 2026-07-19T20:00:00-0500
author: Jeremy Morris
commit: 38b77d3
branch: refactor/blackboard-full
repository: FindAGraveHelper
topic: "Wire Blackboard scheduler into main pipeline"
status: ready
phases:
  - { n: 1, title: "CliMain: --scheduler flag + Blackboard bootstrap", depends_on: [], blast_radius: public-API }
  - { n: 2, title: "SchedulerBatchRunner: scheduler-driven alternative to run_batch", depends_on: [1], blast_radius: cross-module }
  - { n: 3, title: "Wire BrowserSession into make_fag_search_fn", depends_on: [2], blast_radius: internal }
  - { n: 4, title: "Integration smoke test + backward compat", depends_on: [3], blast_radius: cross-module }
---

# Wiring Plan: Blackboard Scheduler → Main Pipeline

## Overview

The new architecture (schema, store, scheduler, Knowledge Sources, decision policy,
request gate, BrowserSession, projector) exists alongside the old god-loop in
`run_unified.py` but nothing calls it. This plan wires the scheduler as an
opt-in code path via `--scheduler` flag, preserving the existing `run_batch`
path for backward compatibility.

## Current State

- `cli_main()` (L1031): builds `fag_search_fn` via `make_fag_search_fn()`,
  builds `UnifiedRunnerConfig`, calls `run_batch()`.
- `run_batch()` (L516): the god-loop. Iterates pensioners, calls
  `run_pipeline_for_pensioner()`, writes state.jsonl via `JsonlStateRepository`.
- `make_fag_search_fn()` in `fag_browser.py` (L115): closure-based browser
  lifecycle with state dict, lock, reset, recovery. Does NOT use BrowserSession.
- `BrowserSession` exists but is unused by production code.
- `BlackboardScheduler` exists but is unused by production code.

## Desired End State

```python
# New path (--scheduler):
python scripts/run_unified.py --scheduler --input ... --cgr ... --out ...
```

1. Bootstrap: open SQLite Blackboard store, build RunManifest
2. Ingest: load pensioners + CGR into Blackboard as observations
3. Enqueue: create WorkItems for IngestionKS → RegionalPlannerKS → FaGScraperKS
4. Register: all Knowledge Sources with scheduler
5. Run: `scheduler.run()` — event-guided dispatch replaces god-loop
6. Project: ProjectionBuilder emits state.jsonl + report from observations
7. Existing `--dry-run`, `--state-replay`, `--rollback-to` still work
   (they read from the projected state.jsonl, same as before)

Backward compat: without `--scheduler`, behavior is unchanged. Old `run_batch`
path stays as the default.

---

## Slice W1: `--scheduler` CLI flag + Blackboard bootstrap

**Goal:** parse `--scheduler` flag, open Blackboard store, build RunManifest,
wire into `UnifiedRunnerConfig` as optional field.

### Changes

1. `scripts/pipeline/run_unified.py` — add `--scheduler` flag to argparse.
   Add `--blackboard-db` flag (default: `<out_dir>/blackboard.db`).
   When `--scheduler`, open SqliteBlackboardStore, build RunManifest,
   attach to config.

2. `scripts/batch_config.py` — add optional `blackboard_store` and
   `run_manifest` fields to `UnifiedRunnerConfig` (dataclass, defaults None).

### Success criteria
- `python scripts/run_unified.py --help` shows `--scheduler` flag
- `--scheduler --dry-run` validates config without running
- Old path (no `--scheduler`) unchanged

---

## Slice W2: `SchedulerBatchRunner` — scheduler-driven batch

**Goal:** new function `run_batch_scheduler()` that replaces the god-loop
with scheduler dispatch. Called when `--scheduler` is set.

### Changes

1. `scripts/pipeline/run_unified.py` — add `run_batch_scheduler(pensioners, cems, config, log)`:
   - Ingest pensioners as PensionerImported observations
   - Ingest CGR records as CGRCorroboration observations
   - Enqueue RegionalPlannerKS work per pensioner
   - Register IngestionKS, RegionalPlannerKS, FaGScraperKS, CandidateScorerKS
   - Run scheduler
   - Project results via ProjectionBuilder → state.jsonl + report

2. `cli_main()` — branch: if `--scheduler`, call `run_batch_scheduler()`;
   else call `run_batch()` (existing path).

### Success criteria
- `python scripts/run_unified.py --scheduler --limit 5` runs 5 pensioners
  through scheduler and writes state.jsonl
- Existing tests pass (old path untouched)

---

## Slice W3: Wire `BrowserSession` into `make_fag_search_fn`

**Goal:** `make_fag_search_fn()` accepts optional `BrowserSession` and
delegates lifecycle management to it instead of the closure state dict.
When BrowserSession is provided, the closure uses `session.search()` or
`session.page` instead of the internal state dict.

### Changes

1. `scripts/fag/fag_browser.py` — `make_fag_search_fn()` gains optional
   `session: BrowserSession | None = None` parameter. When provided:
   - Uses `session.page` instead of `state["page"]`
   - Delegates reset/recovery to `session.reset()`
   - Delegates throttle to `RequestGate` (via session)
   - Lock management stays (thread safety)

2. `scripts/fag/fag_browser.py` — add deprecation comment: the closure
   pattern is legacy; BrowserSession is the future.

### Success criteria
- `make_fag_search_fn(throttle=0.1)` still works (backward compat)
- `make_fag_search_fn(session=BrowserSession.open(...))` works
- `test_intra_strategy_throttle.py` passes

---

## Slice W4: Integration smoke test

**Goal:** prove the full scheduler path works end-to-end without breaking
the old path.

### Changes

1. `tests/test_scheduler_integration.py` (NEW):
   - `test_scheduler_path_runs_without_crashing`: mock FaG responses,
     run 3 pensioners through `run_batch_scheduler()`, verify state.jsonl
     has 3 rows
   - `test_old_path_still_works`: verify `run_batch()` still functions
     (import + smoke)
   - `test_scheduler_projection_matches_old_path`: same input, both paths,
     verify status fields agree (within tolerance)

### Success criteria
- `pytest tests/test_scheduler_integration.py -q` passes
- `pytest tests/ -m "not integration" -q` passes (no regressions)
