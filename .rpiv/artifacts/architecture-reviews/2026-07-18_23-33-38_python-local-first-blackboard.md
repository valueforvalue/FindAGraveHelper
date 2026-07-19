---
template_version: 1
date: 2026-07-18T23:33:38-0500
author: Jeremy Morris
commit: ec8028c
branch: master
repository: FindAGraveHelper
target: Python program (`scripts/**/*.py`, `process_ledger.py`, `playwright_leak_fix.py`)
target_kind: module
layer_count: 7
phases:
  - { n: 1, title: "Correctness and dependency hygiene", depends_on: [], blast_radius: public-API, effort: M }
  - { n: 2, title: "Blackboard contracts and durable local store", depends_on: [1], blast_radius: on-disk, effort: L }
  - { n: 3, title: "Unified evidence and decision policy", depends_on: [2], blast_radius: cross-module, effort: L }
  - { n: 4, title: "Provider safety and browser lifecycle", depends_on: [2], blast_radius: cross-module, effort: L }
  - { n: 5, title: "Event-guided scheduler skeleton", depends_on: [2], blast_radius: cross-module, effort: M }
  - { n: 6, title: "Typed Knowledge Sources and multi-pass refinement", depends_on: [3, 4, 5], blast_radius: cross-module, effort: L }
  - { n: 7, title: "Projection and review migration", depends_on: [6], blast_radius: cross-module, effort: L }
unresolved_finding_count: 0
status: ready
tags: [architecture-review, python-harness, blackboard, playwright, persistence]
last_updated: 2026-07-18T23:33:38-0500
last_updated_by: Jeremy Morris
last_updated_note: ""
---

# Architecture review — Python program against Local-First Blackboard

Comprehensive review of 82 program-related Python files (~16,632 LOC), triggered by request to identify state tangles and refactor rigid batch processing toward local-first Blackboard architecture. Review covers operator entry points, orchestration, search planning, matching, Playwright retrieval, bot controls, CGR integration, persistence, ingestion, analysis, migrations, and root Python utilities. Existing `output/test-batch-25/view.html` deletion remains untouched.

---

## Conventions

### Finding shape

Each finding is a level-3 heading `### L<layer>-<seq> — <title>` followed by fields below.

| Field | Meaning |
|---|---|
| **Evidence** | `file.ext:lineA-lineB` (+ short quote when useful) |
| **Current state** | what code does today |
| **Desired state** | target architecture |
| **Proposed improvement** | concrete action |
| **Severity** | Low / Med / High |
| **Effort** | S / M / L |
| **Blast radius** | `internal` / `public-API` / `on-disk` / `cross-module` |
| **Class** | `polish` / `redesign` |
| **Status** | `open` / `accepted` / `rejected` / `deferred` / `withdrawn` |
| **Depends on** | prerequisite finding IDs |
| **Cross-cut tag** | cross-layer theme |

### Status legend

- `open` — flagged, not yet triaged
- `accepted` — selected for polish plan
- `rejected` — declined with reason
- `deferred` — accepted in principle, postponed
- `withdrawn` — diagnosis disproved during review

### Layers (top → down)

| # | Layer | Files |
|---|---|---|
| 0 | Operator surface + compatibility shims | `scripts/__init__.py`, package `__init__.py` files, `scripts/run_unified.py`, `scripts/search_fag.py`, `scripts/batch_config.py`, `process_ledger.py` |
| 1 | Batch + per-pensioner orchestration | `scripts/pipeline/run_unified.py`, `core.py`, `retry_errors*.py`, `dry_run.py`, `state_replay.py`, `leftover_investigation.py`, `scoring_constants.py` |
| 2 | Search planning + matching/scoring policy | `scripts/search/strategies.py`, `scripts/matching/*.py`, `scripts/fag/scoring.py`, policy portions of `filters.py` |
| 3 | FaG retrieval, DOM parsing + bot control | `scripts/fag/fag_browser.py`, `search.py`, `parser.py`, `inputs.py`, `state_io.py`, `pw_session.py`, `rss_watchdog.py`, `spouse_scrape.py`, both leak-fix modules, `soak_memory.py` |
| 4 | CGR adapters, enrichment + cross-reference | `scripts/cgr/*.py`, `scripts/spouse_cross_ref.py` |
| 5 | State schema, JSONL repository, checkpoints + reports | `scripts/state/*.py`, `scripts/pipeline/checkpoint.py`, `dd_marker*.py`, `backfill_backlinks.py`, `state_normalize.py` |
| 6 | Ingestion, analysis, migrations + one-shot tools | `scripts/ingest/*.py`, `scripts/analysis/*.py`, `rename_to_ok_names.py` and remaining prototypes/utilities |

---

## Methodology principles

### M1 — Facts are durable; conclusions are replayable

**Origin:** L1-02 — retries/refiners must append evidence rather than overwrite prior outcome.

**Rule.** Persist raw and normalized observations with source, policy/parser version, run/pass identity, causation, and timestamps before subsequent work. Scores, matches, statuses, reports, and review rows are deterministic projections that can be rebuilt after policy changes without repeating network retrieval.

**Apply to (keep):**
- Per-record `flush(); os.fsync()` durability.
- Raw CGR/FaG/Digital Prairie evidence and source backlinks.
- Human decisions as explicit observations.

**Apply to (drop / change):**
- In-place enrichment of canonical rows.
- Ad hoc `retried_at` fields as sole lineage.
- Silent corrupt-line skipping.

### M2 — Expensive external effects cross one gate

**Origin:** L3-02 — local sleeps across call paths cannot enforce provider-wide request safety.

**Rule.** Every request to same provider crosses one deep gate that owns minimum spacing, cooldown, bot-wall penalties, retries, and observability. Knowledge Sources propose work; they never sleep or navigate around gate. FaG 2.5s throttle remains non-negotiable floor.

**Apply to (keep):**
- Headful Playwright + stealth + warmup for FaG.
- Full page→context→browser teardown and reset.
- Conservative challenge/backoff behavior.

**Apply to (drop / change):**
- Direct `page.goto()` in spouse/probe paths.
- Post-request sleeps and bursty per-pass loops.
- Process-local cooldown that vanishes after restart.

### M3 — Blackboard store is source; projections are disposable

**Origin:** L5-05 — Python, report, and browser each rederive current truth differently.

**Rule.** Blackboard holds observations and work state. One projector emits compatibility `state.jsonl`, reports, and review data. Consumers render projection rather than mutating or independently normalizing domain truth. Projection can be deleted and rebuilt without losing knowledge.

**Apply to (keep):**
- Existing `state.jsonl`/`view.html` wire contract during migration.
- Stable key order and one-line-per-pensioner exports.
- Side-by-side dry-run/replay comparison.

**Apply to (drop / change):**
- Post-passes rewriting results in place.
- Mirrored Python/JS normalization policy.
- Full-file snapshots as only recovery mechanism.

---

## Layer 0 — Operator surface + compatibility shims

Files reviewed: `scripts/__init__.py`, package `__init__.py` files, `scripts/run_unified.py`, `scripts/search_fag.py`, `scripts/batch_config.py`, `process_ledger.py`.

### L0-01 — Package facade eagerly loads runtime graph

**Evidence**

`scripts/__init__.py:34-37`

```python
from scripts.pipeline.run_unified import run_batch
from scripts.search_fag import search_one_pensioner
from scripts.state_normalize import normalize_state_record
from scripts.state.report_generator import build_report
```

**Current state**

Importing any `scripts.*` leaf first executes package root and loads orchestration/search facades. Package init acts as eager service locator, widening dependency graph and making autonomous Knowledge Sources harder to load independently.

**Desired state**

Package root inert. Callers import explicit canonical modules; knowledge-source discovery must not initialize Playwright/search orchestration.

**Proposed improvement**

Remove eager root re-exports and update remaining callers to canonical module paths. Keep root docstring only.

- **Severity:** Med
- **Effort:** S
- **Blast radius:** public-API
- **Class:** polish
- **Status:** **accepted** — remove eager facade
- **Depends on:** L0-02
- **Cross-cut tag:** `T1-dependency-direction`

### L0-02 — Production modules depend on compatibility shims

**Evidence**

`scripts/fag/fag_browser.py:33-37`; `scripts/pipeline/retry_errors.py:31,176`

```python
from scripts.search_fag import search_one_pensioner, setup_browser, warmup_session
from scripts.run_unified import result_to_dict, now_iso
```

**Current state**

Back-compat shims correctly point inward, but production modules point back outward through those shims. This makes compatibility surface part of runtime topology and obscures true ownership.

**Desired state**

One-way graph: shims → canonical modules. Internal production code imports only canonical modules.

**Proposed improvement**

Change imports to `scripts.fag.search` and `scripts.pipeline.run_unified`; audit all remaining shim imports before deleting root facade.

- **Severity:** Med
- **Effort:** S
- **Blast radius:** internal
- **Class:** polish
- **Status:** **accepted** — fix import direction
- **Depends on:** none
- **Cross-cut tag:** `T1-dependency-direction`

### L0-03 — Batch config cannot identify Blackboard pass lineage

**Evidence**

`scripts/batch_config.py:51-68`

```python
class BatchConfig:
    runname: str
    input_path: Path
    cgr_path: Path
    start_row: int = 0
    end_row: Optional[int] = None
    throttle: float = 2.5
    low_score_threshold: float = 0.40
    fag_state_filter: str = "OK"
```

**Current state**

Config records invocation knobs but not strategy/policy version, pass identity, parent pass, event cursor, source fingerprints, or knowledge-source versions. Replay can recompute scores, but cannot establish which evidence/policy produced a decision.

**Desired state**

Local `RunManifest` provides immutable run identity, provenance, policy version, scheduler/bot budget, and pass lineage while state rows remain pensioner-centered.

**Proposed improvement**

Evolve `BatchConfig` into or pair it with versioned `RunManifest`. Persist manifest beside Blackboard store; reference `run_id`/`pass_id` from posted observations and decisions.

- **Severity:** High
- **Effort:** M
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — evolve config to run manifest
- **Depends on:** none
- **Cross-cut tag:** `T2-provenance-replay`

### Layer 0 — batch 0.1 (Facades/shims) — tally

| Status | Count |
|---|---|
| accepted | 2 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: `T1-dependency-direction`. Reused: none.

Dependency edges: L0-01 depends on L0-02.

### Layer 0 — batch 0.2 (Operator config/export) — tally

| Status | Count |
|---|---|
| accepted | 1 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: `T2-provenance-replay`. Reused: none.

Dependency edges: none.

### Layer 0 — roll-up

| Status | Count |
|---|---|
| accepted | 3 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

---

## Layer 1 — Batch + per-pensioner orchestration

Files reviewed: `scripts/pipeline/run_unified.py`, `core.py`, `scoring_constants.py`, `retry_errors.py`, `retry_errors_run.py`, `dry_run.py`, `state_replay.py`, `leftover_investigation.py`.

### L1-01 — Runner is scheduler, worker, projector, and publisher

**Evidence**

`scripts/pipeline/run_unified.py:516-990`

```python
for i, pensioner in enumerate(remaining):
    pipeline_result = run_pipeline_for_pensioner(...)
    state_repo.append(record)
...
run_dedup(...)
annotate_results_with_dd(...)
subprocess.call(cmd)
...
view_path.write_text(text, encoding="utf-8")
```

**Current state**

`run_batch` owns work selection, CGR index lifecycle, FaG invocation, error conversion, state writes, outlier projection, checkpoints, reporting, post-run mutations, subprocess lifecycle, and UI publication. Stage order is compile-time control flow. Adding a new refiner requires editing central loop or tail.

**Desired state**

Small local scheduler reads pending facts/work units, dispatches autonomous Knowledge Sources, and persists outputs. Reports/UI become projections subscribed to posted facts, not tail logic in live scraper.

**Proposed improvement**

Extract `BlackboardScheduler` with registered Knowledge Sources and explicit eligibility/cost/priority. Initial KS set: Ingestion, Regional Search Planner, FaG Scraper, Candidate Scorer, CGR Corroborator, Deep Refiner, Decision Projector, Review Exporter.

- **Severity:** High
- **Effort:** L
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — introduce scheduler
- **Depends on:** L0-03, L1-02, L1-03
- **Cross-cut tag:** `T3-blackboard-control`

### L1-02 — Refinement overwrites evidence instead of posting knowledge

**Evidence**

`scripts/pipeline/retry_errors.py:138-142`; `scripts/pipeline/leftover_investigation.py:489-493`

```python
existing.update(new_record)
existing["retried_at"] = now_iso()
...
JsonlStateRepository(state_path).replace_all(records)
```

**Current state**

Retries and follow-up passes rewrite current pensioner row. Some lineage survives as ad hoc timestamps or `leftover_pass`, but prior scores, statuses, strategy policy, query, and errors can be overwritten. A later classifier cannot reconstruct why current verdict changed.

**Desired state**

Immutable observations per Knowledge Source/pass/query plus materialized current projection. Retry and refinement append evidence; projector chooses current candidate/outcome deterministically.

**Proposed improvement**

Introduce observation envelope with `observation_id`, `pensioner_id`, `kind`, `source`, `source_version`, `run_id`, `pass_id`, `caused_by`, `recorded_at`, `payload`. Build `PensionerProjection` from append-only observations.

- **Severity:** High
- **Effort:** L
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — append observations
- **Depends on:** L0-03
- **Cross-cut tag:** `T2-provenance-replay`

### L1-03 — Resume cursor conflates durable row with completed work

**Evidence**

`scripts/pipeline/run_unified.py:223-254,600,679-697`

```python
self.completed_ids.add(pid)
...
not_done = [p for p in pensioners if not tracker.is_done(p["id"])]
...
state_repo.append(err_record)  # "done"
```

**Current state**

Any row makes pensioner globally complete. Error rows are deliberately durable, but resume skips them; explicit retry command is required. Multi-pass additions cannot express “scraped, not scored,” “regional plan exhausted, global plan pending,” or “blocked until cooldown.”

**Desired state**

Completion key is a work unit such as `(pensioner_id, knowledge_source, plan_id, pass_id, input_revision)`. Errors stay pending or become `blocked_until`, without losing durable failure evidence.

**Proposed improvement**

Persist work ledger states `ready | leased | succeeded | retryable | blocked | terminal`, with attempt count and `not_before`. Reclaim stale leases on startup. Keep pensioner projection independent from work completion.

- **Severity:** High
- **Effort:** L
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — track work units
- **Depends on:** L1-02
- **Cross-cut tag:** `T4-resume-work-ledger`

### L1-04 — Follow-up plans are computed then discarded

**Evidence**

`scripts/pipeline/leftover_investigation.py:338-355,392-425`

```python
s1 = _spouse_cross_search_params(...)
s2 = _birth_state_narrowing_params(...)
s4 = _regiment_bio_death_year_params(...)
...
cand, status = fag_search_fn(pensioner, None)
```

**Current state**

Follow-up code records strategy names and builds concrete parameter dictionaries, but generic `fag_search_fn` receives fake/original pensioner instead of planned params. Birth-state and regiment/death-year branches can therefore repeat default ladder rather than intended refinement. This is both coupling and likely behavior defect.

**Desired state**

Planner emits immutable `QueryPlan`; scraper executes that exact plan and returns observation tied to `plan_id`. Scorer/refiner consume stored raw candidates independently.

**Proposed improvement**

Define `QueryPlan(plan_id, pensioner_id, strategy, params, scope, reason, estimated_requests, policy_version)`. Remove fake-pensioner adaptation and route all first/follow-up searches through one scraper interface.

- **Severity:** High
- **Effort:** M
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — use QueryPlan
- **Depends on:** L1-01
- **Cross-cut tag:** `T3-blackboard-control`

### Layer 1 — batch 1.1 (Primary runtime) — tally

| Status | Count |
|---|---|
| accepted | 3 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: `T3-blackboard-control`, `T4-resume-work-ledger`. Reused: `T2-provenance-replay`.

Dependency edges: L1-01 depends on L0-03, L1-02, L1-03; L1-02 depends on L0-03; L1-03 depends on L1-02.

### Layer 1 — batch 1.2 (Replay/follow-up) — tally

| Status | Count |
|---|---|
| accepted | 1 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T3-blackboard-control`.

Dependency edges: L1-04 depends on L1-01.

### Layer 1 — roll-up

| Status | Count |
|---|---|
| accepted | 4 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

---

## Layer 2 — Search planning + matching/scoring policy

Files reviewed: `scripts/search/strategies.py`; `scripts/fag/scoring.py`, policy portions of `filters.py`; all nine `scripts/matching/*.py` modules.

### L2-01 — Search strategies are anonymous parameter dictionaries

**Evidence**

`scripts/search/strategies.py:5-8,227-238`

```python
# returns dict of FaG search-URL params or None
STRATEGIES = [("B1-exact", strategy_b1_exact), ...]
```

**Current state**

Strategy identity exists only as list label; output has no durable plan ID, policy version, rationale, prerequisites, geographic scope, expected request count, or terminal condition. Scheduler cannot dedupe/replay plans reliably.

**Desired state**

Regional Search Planner and Deep Refiner post typed, serializable `QueryPlan` facts. Plans remain adapter-neutral enough for persistence but retain provider-specific params.

**Proposed improvement**

Convert strategy functions to `StrategySpec.plan(subject, evidence) -> QueryPlan | None`; version ladder and persist plan before network execution.

- **Severity:** High
- **Effort:** M
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — typed strategy plans
- **Depends on:** L1-04
- **Cross-cut tag:** `T3-blackboard-control`

### L2-02 — Candidate scorer reaches into FaG representation

**Evidence**

`scripts/fag/scoring.py:11-19,32,119-122`

```python
from scripts.fag.filters import parse_slug, normalise, soundex, ...
slug_parts = parse_slug(candidate.get("slug", ""))
from scripts.fag.filters import _in_acw_window, _parse_int
```

**Current state**

Name/date math is pure at runtime but located behind FaG adapter and coupled to slug shape, underscored pensioner keys, nested `details`, and private filter functions. Re-scoring other evidence requires imitating scraper dicts.

**Desired state**

Source-neutral Scorer Knowledge Source consumes normalized `PensionerSnapshot` + `CandidateObservation`; adapter owns slug/DOM normalization only. Policy versions make offline replay exact.

**Proposed improvement**

Move feature extraction/weighting under `matching/candidate_scoring.py`; define typed score explanation and `scoring_policy_version`. Keep FaG normalizer mapping raw candidate to domain observation.

- **Severity:** High
- **Effort:** M
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — extract scorer policy
- **Depends on:** L1-02
- **Cross-cut tag:** `T5-pure-knowledge-sources`

### L2-03 — Decision thresholds and statuses contradict each other

**Evidence**

`scripts/fag/search.py:103-118`; `scripts/pipeline/scoring_constants.py:29-82`; `scripts/pipeline/leftover_investigation.py:79-80`

```python
AUTO_ACCEPT_THRESHOLD = 0.70
AUTO_ACCEPT_THRESHOLD_NO_DEATH = 0.60
# versus
AUTO_ACCEPT_THRESHOLD: float = 0.85
```

**Current state**

Live search, replay, outlier selection, follow-up eligibility, filters, and docs define overlapping status vocabularies and thresholds. Replaying existing candidates can produce verdict different from live run without explicit policy migration.

**Desired state**

One versioned `DecisionPolicy` owns score weights, auto-accept thresholds, dominance gap, status enum, refinement eligibility, and terminal rules. Search adapter returns evidence, never final domain verdict.

**Proposed improvement**

Centralize policy under matching/domain layer. Persist `policy_version` on every score/verdict; projector recomputes current verdict from immutable evidence.

- **Severity:** High
- **Effort:** M
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — unify policy
- **Depends on:** L2-02
- **Cross-cut tag:** `T2-provenance-replay`

### L2-04 — Corroborator uses separate name semantics

**Evidence**

`scripts/matching/both_match.py:73-94`; `scripts/matching/phonetic_match.py:43-130`

```python
def _normalise_name(...)
def _names_match(...):  # exact/prefix/initial
```

**Current state**

Candidate scoring, CGR matching, blocking, and BOTH MATCH use overlapping but different name rules. Same pair can be strong in one path and rejected in another, with no shared evidence envelope.

**Desired state**

One `NameEvidence` model records normalized values and exact/Jaro-Winkler/Metaphone/NYSIIS/Soundex/initial signals. Each Knowledge Source may apply its own declared threshold but not reimplement extraction.

**Proposed improvement**

Move all name feature extraction to `matching/name_evidence.py`; consume evidence in scorer, CGR matcher, blocker, and corroborator.

- **Severity:** Med
- **Effort:** M
- **Blast radius:** internal
- **Class:** polish
- **Status:** **accepted** — one name evidence model
- **Depends on:** L2-02
- **Cross-cut tag:** `T5-pure-knowledge-sources`

### L2-05 — Fellegi-Sunter interface hides logistic regression

**Evidence**

`scripts/matching/fellegi_sunter.py:145-178,207-212`

```python
from recordlinkage.classifiers import FellegiSunter
...
clf = LogisticRegression(...)
self._classifier = (scaler, clf)
...
data = pickle.load(f)
```

**Current state**

Class/module/docs promise Fellegi-Sunter m/u linkage, but implementation trains logistic regression. Imported FS class is unused except dependency probe. Saved artifact has no model/schema/version metadata.

**Desired state**

Actual Fellegi-Sunter model matching named interface and producing explainable per-field m/u weights, with versioned model provenance suitable for local replay.

**Proposed improvement**

Implement actual FS training/prediction; define versioned, validated model artifact and feature schema. Restrict load path to operator-owned local artifacts.

- **Severity:** Med
- **Effort:** M
- **Blast radius:** internal
- **Class:** redesign
- **Status:** **accepted** — implement actual Fellegi-Sunter
- **Depends on:** L2-04
- **Cross-cut tag:** `T5-pure-knowledge-sources`

### Layer 2 — batch 2.1 (Search/candidate policy) — tally

| Status | Count |
|---|---|
| accepted | 3 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: `T5-pure-knowledge-sources`. Reused: `T2-provenance-replay`, `T3-blackboard-control`.

Dependency edges: L2-01 depends on L1-04; L2-02 depends on L1-02; L2-03 depends on L2-02.

### Layer 2 — batch 2.2 (Linkage primitives) — tally

| Status | Count |
|---|---|
| accepted | 2 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T5-pure-knowledge-sources`.

Dependency edges: L2-04 depends on L2-02; L2-05 depends on L2-04.

### Layer 2 — roll-up

| Status | Count |
|---|---|
| accepted | 5 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

---

## Layer 3 — FaG retrieval, DOM parsing + bot control

Files reviewed: `scripts/fag/search.py`, `parser.py`, `inputs.py`, `state_io.py`, `fag_browser.py`, `pw_session.py`, `rss_watchdog.py`, `playwright_leak_fix.py`, `spouse_scrape.py`, `scripts/soak_memory.py`, root `playwright_leak_fix.py`.

### L3-01 — Search function crosses every architectural concern

**Evidence**

`scripts/fag/search.py:223-516`

```python
def search_one_pensioner(page, pensioner, ...):
    # build strategies
    page.goto(url, ...)
    parse_results_page(page)
    score_candidate(local, c)
    # decide status
```

**Current state**

One function owns planning, URL construction, request pacing, navigation, Cloudflare handling, DOM parsing, candidate merge, scoring, validation, and verdict. Browser state and decision state share same stack frame and return one denormalized state row.

**Desired state**

Web Scraper Knowledge Source executes exactly one persisted `QueryPlan`, then posts raw/normalized `FetchObservation`. Separate Scorer and Decision Projector react offline.

**Proposed improvement**

Replace interface with `execute(plan: QueryPlan, session: BrowserSession, gate: RequestGate) -> FetchObservation`. Move ladder iteration to scheduler; merge/scoring/verdict to pure Knowledge Sources.

- **Severity:** High
- **Effort:** L
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — one-plan scraper
- **Depends on:** L2-01, L2-02
- **Cross-cut tag:** `T5-pure-knowledge-sources`

### L3-02 — No process-wide request gate

**Evidence**

`scripts/fag/fag_browser.py:307-318`; `scripts/fag/search.py:323-324,650`; `scripts/fag/spouse_scrape.py:422-424`

```python
# wrapper sleep
# intra-strategy sleep
# standalone per-pensioner sleep
# spouse sleep after navigation
```

**Current state**

Throttle enforced at several call levels using wall clock and local state. Direct spouse navigation happens before its sleep. Future Knowledge Sources can issue requests without sharing last-request time. Safety depends on knowing every call path.

**Desired state**

One process-wide monotonic `RequestGate` mediates every FaG navigation, including search, memorial detail, warmup, retries, and refiners. Default 2.5s remains hard floor; no bypass path.

**Proposed improvement**

Create deep `RequestGate.acquire(request_kind)` interface with floor, adaptive penalty, persisted cooldown, jitter policy if desired, and metrics. BrowserSession exposes no ungated public navigation to Knowledge Sources.

- **Severity:** High
- **Effort:** M
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — central RequestGate
- **Depends on:** L3-05
- **Cross-cut tag:** `T6-request-safety`

### L3-03 — Bot-wall state blocks thread but not future schedule

**Evidence**

`scripts/fag/search.py:327-403`

```python
if "Error 1015" in title:
    time.sleep(120.0)
...
time.sleep(60.0)
```

**Current state**

Challenge detection occurs after `domcontentloaded` and title read. Fixed process-local sleeps hold worker; challenge classification/cooldown is not persisted. Crash or restart clears penalty and may immediately hit FaG again. Parse errors are guessed as Cloudflare after three failures.

**Desired state**

Dedicated response classifier posts `BotWallObserved(kind, evidence, observed_at, retry_after)`. Scheduler sets durable provider-wide `not_before`, pauses all FaG work, and exposes manual-release path for escalated challenge.

**Proposed improvement**

Centralize title/body/URL/status heuristics before result parsing. Replace sleeps with persisted cooldown + scheduler wake-up. Backoff policy remains conservative and never undercuts 2.5s throttle.

- **Severity:** High
- **Effort:** M
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — persist cooldown state
- **Depends on:** L1-03, L3-02
- **Cross-cut tag:** `T6-request-safety`

### L3-04 — Standalone state writer violates fsync law

**Evidence**

`scripts/fag/state_io.py:52-57`; `scripts/fag/search.py:632-650`

```python
f.write(line + "\n")
f.flush()
# no os.fsync
```

**Current state**

Legacy standalone CLI remains production-capable but bypasses canonical repository and L3 `flush(); os.fsync()` discipline. Crash can lose rows even though docs promise resume safety.

**Desired state**

Single persistence path through Blackboard store/`JsonlStateRepository`; no search adapter writes state.

**Proposed improvement**

Retire `append_state` and standalone loop as production path. Keep CLI as thin scheduler invocation if compatibility required.

- **Severity:** High
- **Effort:** M
- **Blast radius:** public-API
- **Class:** redesign
- **Status:** **accepted** — remove legacy writer
- **Depends on:** L1-01
- **Cross-cut tag:** `T4-resume-work-ledger`

### L3-05 — Browser lifecycle has two owners

**Evidence**

`scripts/fag/fag_browser.py:115-408`; `scripts/fag/pw_session.py:22-145`

**Current state**

Closure and class both manage Playwright/browser/context/page resets with different reset defaults, warmup behavior, leak-patch application, counters, and recovery. Only closure has target-closed/bot integration; only class presents explicit lifecycle.

**Desired state**

One deep `BrowserSession` owns stealth, warmup, gated navigation, page→context→browser→Playwright teardown, reset policy, and target-closed recovery.

**Proposed improvement**

Consolidate implementation; remove unused duplicate. Adapter interface stays small (`start`, `navigate`, `reset`, `close`) and emits session events.

- **Severity:** Med
- **Effort:** M
- **Blast radius:** internal
- **Class:** redesign
- **Status:** **accepted** — unify session owner
- **Depends on:** L0-02
- **Cross-cut tag:** `T1-dependency-direction`

### L3-06 — Leak-fix duplicate already diverged

**Evidence**

`scripts/fag/playwright_leak_fix.py:52-67,104-105`; `playwright_leak_fix.py:84-96`

**Current state**

Canonical package uses `_DummyTrace` because Playwright calls `.format()`; root copy sets `__pw_stack_trace__` to list and can fail on error path. Probe/real test still import root module.

**Desired state**

One implementation and one verified compatibility contract for installed Playwright version.

**Proposed improvement**

Delete root copy; update probes/tests to canonical package. Guard patch by supported Playwright versions and focused smoke.

- **Severity:** Med
- **Effort:** S
- **Blast radius:** internal
- **Class:** polish
- **Status:** **accepted** — delete root copy
- **Depends on:** L0-02
- **Cross-cut tag:** `T1-dependency-direction`

### L3-07 — RSS watchdog measures only Python process

**Evidence**

`scripts/fag/rss_watchdog.py:1-7,103-109`

```python
h = _kernel32.GetCurrentProcess()
return int(counters.WorkingSetSize)
```

**Current state**

Docs and thresholds describe aggregate Chromium + shell + Python pressure, but implementation samples current Python process only. Browser child growth can exceed memory wall without triggering reset/exit.

**Desired state**

Memory observer measures Python plus owned browser process tree and posts `MemoryPressureObserved` before scheduling reset/terminal stop.

**Proposed improvement**

Track child PIDs/process tree cross-platform where practical; report component and aggregate RSS. Scheduler responds with browser reset, then graceful checkpointed exit if pressure persists.

- **Severity:** High
- **Effort:** M
- **Blast radius:** internal
- **Class:** redesign
- **Status:** **accepted** — measure process tree
- **Depends on:** L3-05
- **Cross-cut tag:** `T6-request-safety`

### L3-08 — Parser exceptional paths reference missing symbols

**Evidence**

`scripts/fag/parser.py:48,89,103`

```python
except PWTimeout:
...
log.debug(...)
log.warning(...)
```

**Current state**

Module imports `Page` only and defines no `log`. Wait timeout or locator exception triggers `NameError`, masking original condition and producing avoidable error records.

**Desired state**

Parser handles expected timeout/locator failures fail-soft with defined exception type/logger; tests exercise exceptional paths.

**Proposed improvement**

Import Playwright `TimeoutError as PWTimeout`, define module logger, and add timeout/locator-failure regression tests before larger scraper extraction.

- **Severity:** High
- **Effort:** S
- **Blast radius:** internal
- **Class:** polish
- **Status:** **accepted** — fix parser defects
- **Depends on:** none
- **Cross-cut tag:** `T6-request-safety`

### Layer 3 — batch 3.1 (Search/DOM) — tally

| Status | Count |
|---|---|
| accepted | 3 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T4-resume-work-ledger`, `T5-pure-knowledge-sources`.

Dependency edges: L3-01 depends on L2-01/L2-02; L3-04 depends on L1-01.

### Layer 3 — batch 3.2 (Session/bot/memory) — tally

| Status | Count |
|---|---|
| accepted | 5 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: `T6-request-safety`. Reused: `T1-dependency-direction`, `T4-resume-work-ledger`.

Dependency edges: L3-02 depends on L3-05; L3-03 depends on L1-03/L3-02; L3-05/L3-06 depend on L0-02; L3-07 depends on L3-05.

### Layer 3 — roll-up

| Status | Count |
|---|---|
| accepted | 8 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

---

## Layer 4 — CGR adapters, enrichment + cross-reference

Files reviewed: all 19 `scripts/cgr/*.py` implementation files plus `scripts/spouse_cross_ref.py`.

### L4-01 — CGR client discards replayable source evidence

**Evidence**

`scripts/cgr/cgr_client.py:24-182`

**Current state**

Client combines request pacing, HTTP, decoding, endpoint URL construction, pagination, and parser invocation, returning parsed dicts only. Parser fixes cannot replay historical response; source hash/status/fetched-at/parser version are absent.

**Desired state**

CGR Fetcher Knowledge Source posts raw response observation/provenance. Pure CGR Parser/Enricher Knowledge Sources transform it locally and can rerun without network.

**Proposed improvement**

Split `fetch(CGRRequest) -> RawSourceObservation` from `parse(raw) -> CGRObservation`. Persist compact raw HTML or content-addressed cache plus URL, status, encoding, fetched timestamp, parser version.

- **Severity:** Med
- **Effort:** M
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — split fetch/parse
- **Depends on:** L1-02
- **Cross-cut tag:** `T5-pure-knowledge-sources`

### L4-02 — CGR linkage policy is triplicated and one call is malformed

**Evidence**

`scripts/cgr/cgr_matcher.py:45-286`; `cgr_dedup.py:106-279`; `cgr_fag_dedup.py:96-151`

```python
matches, _ = match_pensioner_to_cgr(...)
```

**Current state**

Three normalization/name/year/unit policies assign different strengths. `match_pensioner_to_cgr` returns one annotated list, but `cgr_fag_dedup.match_strength` unpacks two values; common path can throw and fall back to “different,” weakening valid matches.

**Desired state**

One shared `CGRMatchEvidence` extractor. CGR Corroborator and strict CGR Deduplicator apply explicit versioned policy over same features.

**Proposed improvement**

Adopt L2 `NameEvidence`, shared year/unit evidence, typed results. Delete duplicate ad hoc phonetic/normalization code and malformed adapter call.

- **Severity:** High
- **Effort:** M
- **Blast radius:** internal
- **Class:** redesign
- **Status:** **accepted** — unify CGR evidence
- **Depends on:** L2-04
- **Cross-cut tag:** `T5-pure-knowledge-sources`

### L4-03 — Post-passes rewrite canonical result rows

**Evidence**

`scripts/cgr/cgr_fag_dedup.py:379-390`; `dixiedata_match.py:354-357`; `spouse_compare.py:223-230`

**Current state**

CGR classification, DixieData comparison, and spouse corroboration each read all/current rows, mutate fields, then replace `results.jsonl`. Pass order controls row shape; crash can leave sidecar and projection out of sync; lineage is partial.

**Desired state**

Each pass posts immutable observations. Projector joins observations by pensioner/candidate and materializes review row. Knowledge Sources never mutate each other’s evidence.

**Proposed improvement**

Implement `CGRCorroborationObserved`, `DixieDataMatchObserved`, and `SpouseMatchObserved`; rebuild `results.jsonl`/view sidecars as disposable projections.

- **Severity:** High
- **Effort:** L
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — post observations
- **Depends on:** L1-02
- **Cross-cut tag:** `T2-provenance-replay`

### L4-04 — Spouse retrieval bypasses FaG safety controls

**Evidence**

`scripts/cgr/spouse_compare.py:113,169,224-225`

```python
page.goto("https://www.findagrave.com/", ...)
scrape_and_compare(..., throttle_seconds=0)
if total_attempted % 5 == 0:
    time.sleep(throttle_seconds)
```

**Current state**

Independent subprocess/browser performs up to five memorial navigations as burst, lacks shared Cloudflare 1015 cooldown/session recovery, and rewrites full results only after pass. Crash can lose whole in-flight pass.

**Desired state**

Deep Refiner emits memorial-detail plans. Same BrowserSession/RequestGate executes each request; each spouse fetch/parse/match posts durable observation; work ledger resumes candidate-level.

**Proposed improvement**

Fold spouse retrieval into Web Scraper Knowledge Source request kinds while preserving subprocess only if Playwright runtime forces it. If subprocess remains, coordinate through same persisted gate/work protocol.

- **Severity:** High
- **Effort:** M
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — unify spouse retrieval
- **Depends on:** L3-02, L3-03
- **Cross-cut tag:** `T6-request-safety`

### L4-05 — CGR long-run writers are not durable checkpoints

**Evidence**

`scripts/cgr/cgr_enrich.py:126-131`; `cgr_ok_scraper.py:163-170`; `cgr_xref_run.py:102-104`

**Current state**

Long runs claim resume safety but append using flush/close without `os.fsync`; done sets consider any row complete, including errors. Separate resume implementations repeat L1 flaw.

**Desired state**

CGR work uses same durable observation/work ledger semantics as FaG: fsync before next unit, retryable failures, per-source work key.

**Proposed improvement**

Route CGR outputs through durable Blackboard store. Keep source-specific request gate but shared work-state protocol.

- **Severity:** High
- **Effort:** M
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — use durable store
- **Depends on:** L1-03
- **Cross-cut tag:** `T4-resume-work-ledger`

### L4-06 — Cemetery limit flag does nothing

**Evidence**

`scripts/cgr/cgr_ok_scraper_run.py:57,73-78`

```python
parser.add_argument("--limit-cemeteries", ...)
records = scrape_ok_cemeteries(...)
if args.limit_cemeteries ...:
    pass
```

**Current state**

Operator can request smoke limit, but scraper still processes full state. Risk: unexpected thousands of polite-but-unintended CGR requests.

**Desired state**

Bound applied before first cemetery work unit; observable request count honors limit.

**Proposed improvement**

Add `max_cemeteries` to scraper config/scheduler selection and regression-test zero/one/N semantics.

- **Severity:** High
- **Effort:** S
- **Blast radius:** public-API
- **Class:** polish
- **Status:** **accepted** — fix limit
- **Depends on:** none
- **Cross-cut tag:** `T6-request-safety`

### Layer 4 — batch 4.1 (Client/parsers) — tally

| Status | Count |
|---|---|
| accepted | 1 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T5-pure-knowledge-sources`.

Dependency edges: L4-01 depends on L1-02.

### Layer 4 — batch 4.2 (Matching/dedup) — tally

| Status | Count |
|---|---|
| accepted | 3 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T2-provenance-replay`, `T5-pure-knowledge-sources`, `T6-request-safety`.

Dependency edges: L4-02 depends on L2-04; L4-03 depends on L1-02; L4-04 depends on L3-02/L3-03.

### Layer 4 — batch 4.3 (Enrichment/runners/prototypes) — tally

| Status | Count |
|---|---|
| accepted | 2 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T4-resume-work-ledger`, `T6-request-safety`.

Dependency edges: L4-05 depends on L1-03; L4-06 has none.

### Layer 4 — roll-up

| Status | Count |
|---|---|
| accepted | 6 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

---

## Layer 5 — State schema, JSONL repository, checkpoints + reports

Files reviewed: `scripts/state/schema.py`, `repository.py`, `state_check.py`, `report_generator.py`; `scripts/pipeline/checkpoint.py`, `dd_marker.py`, `dd_marker_run.py`, `backfill_backlinks.py`; `scripts/state_normalize.py`.

### L5-01 — Repository interface models mutable rows, not Blackboard facts

**Evidence**

`scripts/state/repository.py:100-148`

```python
append(record)
get(pensioner_id)
update(pensioner_id, mutate)
replace_all(records)
```

**Current state**

Good L3/L5 durability exists for pensioner JSONL. Interface centers one mutable record per pensioner and full-file replacement. It cannot atomically dedupe observation IDs, claim work, persist provider cooldown, or maintain projection cursor.

**Desired state**

Local `BlackboardStore` owns append-only observations, work ledger, run manifest, provider state, and projection checkpoints. `state.jsonl`/`results.jsonl` remains compatibility/review projection.

**Proposed improvement**

Add deep store interface (`append_observation`, `enqueue_work`, `claim_work`, `complete_work`, `set_provider_not_before`, `read_since`, `save_projection_cursor`). SQLite WAL is strong local-first adapter; append-only JSONL + lock files remains possible adapter. Do not replace wire projection until view contract migration is ready.

- **Severity:** High
- **Effort:** L
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — add Blackboard store
- **Depends on:** L1-02, L1-03
- **Cross-cut tag:** `T4-resume-work-ledger`

### L5-02 — Current typed schema cannot express pass provenance

**Evidence**

`scripts/state/schema.py:21,117-170`

```python
SCHEMA_VERSION = 1
class PensionerRecord: ...
extras: dict = field(default_factory=dict)
```

**Current state**

Typed fronts preserve unknown fields but type only current pensioner/candidate/BOTH MATCH projection. Schema version constant is not embedded in each record; plans, observations, policy versions, causation, attempts, and work states have no contract.

**Desired state**

Versioned typed envelopes for `RunManifest`, `QueryPlan`, `Observation`, `WorkItem`, `ScoreEvidence`, `Decision`, and `PensionerProjection`. Adapter payloads may carry provider-specific extras without polluting domain projection.

**Proposed improvement**

Create explicit schema modules and migration readers. Include `schema_version`, stable ID, source/version, run/pass/causation, and timestamps in every durable envelope.

- **Severity:** High
- **Effort:** M
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — version typed envelopes
- **Depends on:** L0-03, L5-01
- **Cross-cut tag:** `T2-provenance-replay`

### L5-03 — Checkpoint rollback consumes checkpoint

**Evidence**

`scripts/pipeline/checkpoint.py:127-145,170-193`

```python
snap_path.write_bytes(state_path.read_bytes())
...
os.replace(snap_path, state_path)
```

**Current state**

Snapshot copy lacks temporary-file fsync/checksum/manifest. Rollback moves selected snapshot over state, deleting named recovery point. Snapshot covers projection only, not sidecars or pass metadata.

**Desired state**

Non-destructive, verified snapshot of Blackboard state + manifest/cursors. Rollback selects a new projection head or copies snapshot, preserving source checkpoint and recording rollback event.

**Proposed improvement**

Snapshot transactionally, hash/check, fsync file + directory, preserve snapshot. Under append-only store, prefer projection cursor rollback and immutable snapshots for disaster recovery.

- **Severity:** Med
- **Effort:** M
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — non-destructive snapshots
- **Depends on:** L5-01
- **Cross-cut tag:** `T2-provenance-replay`

### L5-04 — Default reader silently drops corrupt evidence

**Evidence**

`scripts/state/repository.py:183-196`; `scripts/state/state_check.py:107-145`

```python
except json.JSONDecodeError:
    continue
```

**Current state**

Repository projections skip malformed lines silently while optional checker reports them. A truncated/corrupt observation can disappear from reports, resume sets, and rewrites; subsequent `replace_all` permanently erases it.

**Desired state**

Corruption visible and blocks mutation/projection past last verified cursor. Bad tail can be quarantined with explicit repair command.

**Proposed improvement**

Make strict iteration default; include path/line/offset in `CorruptStateError`. Provide explicitly named tolerant forensic reader only for recovery.

- **Severity:** High
- **Effort:** S
- **Blast radius:** internal
- **Class:** polish
- **Status:** **accepted** — fail visible
- **Depends on:** none
- **Cross-cut tag:** `T4-resume-work-ledger`

### L5-05 — Projection policy is reimplemented across Python and browser

**Evidence**

`scripts/state_normalize.py:7-9,116-186`; `scripts/state/report_generator.py:96-207`

**Current state**

Python normalizer says logic is mirrored in `view.html`; report generator separately counts statuses, outliers, score maxima, and BOTH MATCH. Changes require coordinated edits and can produce different current truth.

**Desired state**

One deterministic Projection Knowledge Source consumes observations + DecisionPolicy and emits canonical review rows/report facts. `view.html` renders projection; it does not normalize domain truth.

**Proposed improvement**

Build `ProjectionBuilder` in Python. Export stable `state.jsonl` key order for existing UI; reports derive from same typed projection. Keep browser-only decision fields as separate human-decision observations/import.

- **Severity:** High
- **Effort:** L
- **Blast radius:** cross-module
- **Class:** redesign
- **Status:** **accepted** — one projector
- **Depends on:** L2-03, L5-01, L5-02
- **Cross-cut tag:** `T2-provenance-replay`

### L5-06 — Backfill contains unreachable stale write path

**Evidence**

`scripts/pipeline/backfill_backlinks.py:83-89`

```python
return filled, skipped, missing
# unreachable; tmp_path undefined
tmp_path.replace(output_path)
```

**Current state**

Dead block survived repository migration; creates false second persistence implementation for readers/agents.

**Desired state**

One clear repository-backed path.

**Proposed improvement**

Delete unreachable block and enforce unreachable-code lint where toolchain allows.

- **Severity:** Low
- **Effort:** S
- **Blast radius:** internal
- **Class:** polish
- **Status:** **accepted** — delete dead block
- **Depends on:** none
- **Cross-cut tag:** `T1-dependency-direction`

### Layer 5 — batch 5.1 (State core) — tally

| Status | Count |
|---|---|
| accepted | 4 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T2-provenance-replay`, `T4-resume-work-ledger`.

Dependency edges: L5-01 depends on L1-02/L1-03; L5-02 depends on L0-03/L5-01; L5-03 depends on L5-01; L5-04 has none.

### Layer 5 — batch 5.2 (Projections/migrations) — tally

| Status | Count |
|---|---|
| accepted | 2 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T1-dependency-direction`, `T2-provenance-replay`.

Dependency edges: L5-05 depends on L2-03/L5-01/L5-02; L5-06 has none.

### Layer 5 — roll-up

| Status | Count |
|---|---|
| accepted | 6 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

---

## Layer 6 — Ingestion, analysis, migrations + one-shot tools

Files reviewed: all four `scripts/ingest/*.py` implementation files, all four `scripts/analysis/*.py` implementation files, `scripts/pipeline/rename_to_ok_names.py`.

### L6-01 — Ingestion cannot replay fetch/parse/merge independently

**Evidence**

`scripts/ingest/scrape_digitalprairie.py:288-430`

**Current state**

Concurrent fetch, parse, collection merge, progress rewrite, and final JSON/CSV generation live in one flow. Missing/network/parser outcomes are not durable per ID; periodic save rewrites full collection. Source response/parser provenance is absent.

**Desired state**

Ingestion Knowledge Source posts source fetch observations per collection/item. Parser and Pensioner Projector merge collections locally by application number with versioned rules; failed work remains retryable.

**Proposed improvement**

Use Blackboard work units for Digital Prairie IDs. Persist response metadata/content hash, fetch outcome, parser version, and normalized source observation before next work. Generate `ok_pensioners.json` + meta as projections.

- **Severity:** Med
- **Effort:** L
- **Blast radius:** on-disk
- **Class:** redesign
- **Status:** **accepted** — Blackboard ingestion
- **Depends on:** L5-01, L5-02
- **Cross-cut tag:** `T3-blackboard-control`

### L6-02 — Validation evaluates shadow algorithms

**Evidence**

`scripts/ingest/validate_v5_ladder.py:53-301`; `scripts/analysis/analyze_local_db.py`; `analyze_slug_shapes.py`; `match_broadened_to_local.py`

**Current state**

Offline scripts reimplement slug parser, normalization, Soundex, state extraction, and simulated strategy predicates. Validation may certify model unlike production ladder/scorer. Most scripts execute at import and hard-code `C:/tmp` paths.

**Desired state**

One evaluation harness consumes actual `StrategySpec`, name/score evidence, DecisionPolicy, and fixture/Blackboard observations. Throwaway reporting stays quarantine but does not define algorithms.

**Proposed improvement**

Extract fixture loaders + evaluator functions with CLI paths. Reuse production policy modules. Convert import-time scripts to `main()` or archive after lessons are codified.

- **Severity:** High
- **Effort:** M
- **Blast radius:** internal
- **Class:** redesign
- **Status:** **accepted** — one evaluation harness
- **Depends on:** L2-01, L2-02, L2-03
- **Cross-cut tag:** `T5-pure-knowledge-sources`

### L6-03 — Live FaG probe bypasses canonical safety seam

**Evidence**

`scripts/analysis/_probe_fag_filter.py:13-14,49-56`

```python
import playwright_leak_fix
...
page.goto(url, ...)
time.sleep(5)
```

**Current state**

Probe uses divergent root monkey patch and direct browser requests. It has fixed sleeps but no shared RequestGate, provider cooldown, complete challenge classifier, or session recovery.

**Desired state**

Every FaG request, including probes, crosses canonical BrowserSession + RequestGate. Probe is different plan set, not different transport safety.

**Proposed improvement**

Model probe cases as `QueryPlan`/diagnostic request kind; post results locally. Import canonical leak/session module only.

- **Severity:** Med
- **Effort:** S
- **Blast radius:** internal
- **Class:** polish
- **Status:** **accepted** — use canonical adapter
- **Depends on:** L3-02, L3-05, L3-06
- **Cross-cut tag:** `T6-request-safety`

### L6-04 — Rename migration lacks transaction/verification

**Evidence**

`scripts/pipeline/rename_to_ok_names.py:112-123`

```python
meta_dst.write_text(...)
data_dst.write_bytes(data_src.read_bytes())
data_src.unlink()
```

**Current state**

Meta, destination copy, and source deletion are separate non-fsynced steps. Interruption can leave mismatched data/meta or partial destination; no checksum confirms copied bytes.

**Desired state**

Migration is atomic/restartable and records source/destination hashes plus status.

**Proposed improvement**

Write temp destination/meta, fsync, verify hash/count, `os.replace`, fsync directory, then remove source only after committed manifest. Re-run detects completed/partial states safely.

- **Severity:** Med
- **Effort:** S
- **Blast radius:** on-disk
- **Class:** polish
- **Status:** **accepted** — make migration atomic
- **Depends on:** none
- **Cross-cut tag:** `T2-provenance-replay`

### Layer 6 — batch 6.1 (Ingestion) — tally

| Status | Count |
|---|---|
| accepted | 1 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T3-blackboard-control`.

Dependency edges: L6-01 depends on L5-01/L5-02.

### Layer 6 — batch 6.2 (Analysis/probes) — tally

| Status | Count |
|---|---|
| accepted | 2 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T5-pure-knowledge-sources`, `T6-request-safety`.

Dependency edges: L6-02 depends on L2-01/L2-02/L2-03; L6-03 depends on L3-02/L3-05/L3-06.

### Layer 6 — batch 6.3 (Migrations) — tally

| Status | Count |
|---|---|
| accepted | 1 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

Cross-cutting tags introduced: none. Reused: `T2-provenance-replay`.

Dependency edges: none.

### Layer 6 — roll-up

| Status | Count |
|---|---|
| accepted | 4 |
| rejected | 0 |
| deferred | 0 |
| withdrawn | 0 |

---

## Cross-cutting themes

### T1 — Dependency direction + compatibility cleanup (active)

**Findings:** L0-01, L0-02, L3-05, L3-06, L5-06.

Compatibility facades, duplicate lifecycle implementations, duplicate monkey patches, and stale dead code obscure canonical ownership. Closing thread makes internal graph one-way and lets each Knowledge Source import only required leaves.

### T2 — Provenance + deterministic replay (active)

**Findings:** L0-03, L1-02, L2-03, L4-03, L5-02, L5-03, L5-05, L6-04.

Current mutable rows and ad hoc pass fields cannot explain which source/query/policy created verdict. Thread delivers versioned run/pass lineage, immutable observations, one deterministic projector, and non-destructive recovery.

### T3 — Blackboard scheduler + typed plans (active)

**Findings:** L1-01, L1-04, L2-01, L6-01.

Rigid orchestration and anonymous dict strategies prevent event-guided refinement. Thread introduces typed plans, autonomous eligibility, scheduler dispatch, and ingestion/search/refinement work driven by local facts.

### T4 — Durable work ledger + checkpoint semantics (active)

**Findings:** L1-03, L3-04, L4-05, L5-01, L5-04.

Pensioner-level done sets and mixed writer durability cannot represent partial/multi-pass progress. Thread supplies durable per-Knowledge-Source work state, retryable errors, visible corruption, fsync discipline, and resumable local work.

### T5 — Pure source-neutral Knowledge Sources (active)

**Findings:** L2-02, L2-04, L2-05, L3-01, L4-01, L4-02, L6-02.

Decision logic currently reaches into provider dict/slug shapes, while matching/evaluation duplicates algorithms. Thread isolates fetch adapters from pure parsers, evidence extractors, scorers, corroborators, model training, and evaluation.

### T6 — Provider request safety + browser resilience (active)

**Findings:** L3-02, L3-03, L3-07, L3-08, L4-04, L4-06, L6-03.

FaG and CGR request safety varies by path; bot walls and memory pressure are process-local or mismeasured. Thread delivers one request gate per provider, persisted cooldowns, unified browser lifecycle, correct process-tree pressure, and bounded diagnostics/smokes.

---

## Consolidated polish plan

### Executive gap analysis

#### Current state tangles

1. **Retrieval ↔ decision ↔ output:** `scripts/fag/search.py:223-516` builds strategy params, sleeps, drives `page.goto`, detects Cloudflare, parses DOM, merges candidates, scores name/date evidence, assigns final status, and returns projection-shaped record. `scripts/pipeline/run_unified.py:516-990` then writes it, classifies outliers, reports, rewrites it through CGR/DD/spouse passes, and publishes `view.html`.
2. **Browser/session ↔ rate policy:** `scripts/fag/fag_browser.py` owns inter-pensioner timing/reset; `search.py` owns inter-strategy timing/backoff; spouse/probe/standalone paths navigate independently. Safety relies on every caller remembering throttle law.
3. **Evidence ↔ verdict:** score/status fields live beside raw candidates. Retry/refinement uses `dict.update` or full-file replacement, so prior verdict/evidence relationship is not reconstructable.
4. **Persistence ↔ completion:** presence of any pensioner row means done, including error. Durable write exists, but work state cannot say which source/strategy/pass remains.
5. **Post-processing ↔ canonical state:** CGR dedup, DixieData, spouse comparison, normalization, report generation, and UI each mutate or rederive “current truth.”

#### Blackboard decomposition

```text
                        Local RunManifest
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ BlackboardStore                                             │
│ observations · work_items · provider_state · projection head│
└─────────────────────────────────────────────────────────────┘
     ▲             ▲              ▲                 ▲
     │ posts       │ posts        │ posts           │ posts
┌────┴────┐  ┌─────┴─────┐  ┌─────┴──────┐  ┌──────┴──────┐
│Ingestion│  │Regional   │  │FaG Web     │  │CGR / DD /   │
│KS       │  │Planner KS │  │Scraper KS  │  │Spouse KS    │
└─────────┘  └───────────┘  └────────────┘  └─────────────┘
                    ▲             │ raw candidates
                    │ new plans   ▼
              ┌─────┴──────┐  ┌──────────────┐
              │Deep Refiner│  │Phonetic/Date │
              │KS          │  │Scorer KS     │
              └────────────┘  └──────┬───────┘
                                     ▼
                              ┌──────────────┐
                              │Decision +    │
                              │Projection KS │
                              └──────┬───────┘
                                     ▼
                         state.jsonl · reports · view
```

- **Ingestion KS:** posts source-backed Pensioner observations from Digital Prairie/CGR/local files.
- **Regional Search Planner KS:** emits low-cost, location-aware `QueryPlan`s from pensioner/regiment/spouse evidence.
- **FaG Web Scraper KS:** executes one plan through BrowserSession + RequestGate; posts raw/normalized candidates or bot-wall observation. No scoring/file writes.
- **Phonetic/Date Scorer KS:** computes versioned name/date/location/veteran evidence offline.
- **CGR Corroborator KS:** posts CGR, direct-link, DixieData, and spouse corroboration observations.
- **Deep Refiner KS:** reacts to ambiguous/no-results/low-information projections; emits spouse/global/nickname/regiment plans within request budget.
- **Decision/Projection KS:** applies versioned policy and emits disposable `state.jsonl`, reports, and review data.

Local-first constraint: no cloud broker or always-on daemon. Single-process scheduler over SQLite WAL or equivalent durable local adapter. Existing JSONL remains export/review contract during migration.

#### Bot detection, throttle, and checkpoint audit

- **Strong existing controls:** headful Chromium + stealth + homepage warmup; production default 2.5s; inter-strategy sleeps when called through `fag_browser`; 30s CAPTCHA, 60s sustained-parse, 120s 1015 backoffs; target-closed recovery; page→context→browser→Playwright teardown; periodic reset every 250 records; max 10 consecutive errors; production `JsonlStateRepository.append` flushes + fsyncs per pensioner.
- **Throttle gaps:** no provider-wide clock. Standalone `fag/search.py` calls `search_one_pensioner` without `throttle_seconds`, allowing strategy bursts, then sleeps once per pensioner. Spouse pass sleeps only every fifth attempt. Probes call Playwright directly.
- **Bot-state gaps:** title checks happen after page load; parse failures guess bot wall; cooldown is in-memory sleep only. Restart forgets penalty and can immediately re-hit provider.
- **Memory gap:** watchdog docs claim aggregate Chromium/shell/Python RSS, implementation measures current Python process only.
- **Checkpoint reality:** production main path does **not** require complete rerun after crash. Per-pensioner fsync + resume skip already protect completed pensioners; snapshots, dry-run, state replay, and retry-errors also exist. Main gap is granularity: an error row becomes globally done; strategy/pass progress is not checkpointed; retries/refiners rewrite evidence; provider cooldown is not durable. Standalone FaG and CGR writers also lack fsync.

Seven phases, ordered by dependency. Phases 3–5 can proceed in parallel after Phase 2; Phase 6 joins them.

### Phase 1 — Correctness and dependency hygiene

**Goal:** remove known defects and establish one-way canonical imports before structural work.

**Findings (7):** L0-01, L0-02, L3-06, L3-08, L4-06, L5-04, L5-06.

**Files touched (14):** `scripts/__init__.py`, `scripts/fag/fag_browser.py`, `scripts/fag/parser.py`, `scripts/fag/playwright_leak_fix.py`, `playwright_leak_fix.py` (delete), `scripts/pipeline/retry_errors.py`, `scripts/cgr/cgr_ok_scraper.py`, `scripts/cgr/cgr_ok_scraper_run.py`, `scripts/state/repository.py`, `scripts/pipeline/backfill_backlinks.py`, `scripts/analysis/_probe_fag_filter.py`, `tests/test_fag_parser_constants.py`, `tests/test_cgr_ok_scraper.py`, `tests/test_state_repository.py`.

**Blast-radius mix:** internal: 5; public-API: 2; on-disk: 0; cross-module: 0.

**Class mix:** polish: 7; redesign: 0.

**Coordination:** none.

**Risk callouts:** root facade removal needs caller/test import sweep. Keep CLI shims until explicit compatibility retirement.

**Success criteria:**
- Parser timeout/locator paths return fail-soft result without `NameError`.
- `--limit-cemeteries N` performs at most N cemetery work units.
- No production module imports `scripts.search_fag` or `scripts.run_unified` shims.
- Corrupt JSONL is visible and cannot be silently rewritten away.
- Targeted parser/CGR/repository suites and full `pytest tests/` pass.

### Phase 2 — Blackboard contracts and durable local store

**Goal:** establish versioned run/observation/work contracts and durable store while preserving state projection.

**Findings (7):** L0-03, L1-02, L1-03, L5-01, L5-02, L5-03, L6-04.

**Files touched (15):** `scripts/batch_config.py`, `scripts/blackboard/__init__.py` (new), `scripts/blackboard/schema.py` (new), `scripts/blackboard/store.py` (new), `scripts/state/schema.py`, `scripts/state/repository.py`, `scripts/pipeline/checkpoint.py`, `scripts/pipeline/retry_errors.py`, `scripts/pipeline/leftover_investigation.py`, `scripts/pipeline/rename_to_ok_names.py`, `tests/test_batch_config.py`, `tests/test_state_schema.py`, `tests/test_state_repository.py`, `tests/test_checkpoint_rollback.py`, `tests/test_loop_crash_safety.py`.

**Blast-radius mix:** internal: 1; public-API: 0; on-disk: 6; cross-module: 0.

**Class mix:** polish: 1; redesign: 6.

**Coordination:** none.

**Risk callouts:** new on-disk format. Use additive dual-write/import path; never switch `view.html` input in same step as store introduction.

**Success criteria:**
- RunManifest, Observation, WorkItem, QueryPlan envelope, provider state, and projection cursor carry schema/source/policy/run/pass/causation metadata.
- Completed observation survives forced kill before next work unit.
- Error work becomes retryable/blocked, not globally complete.
- Stale lease recovery and idempotent observation append tested.
- Snapshot rollback preserves checkpoint and records rollback provenance.
- Existing state JSONL projection remains byte-shape compatible where contract requires.

### Phase 3 — Unified evidence and decision policy

**Goal:** make matching/scoring pure, source-neutral, versioned, and evaluated through production code.

**Findings (6):** L2-02, L2-03, L2-04, L2-05, L4-02, L6-02.

**Files touched (15):** `scripts/matching/name_evidence.py` (new), `scripts/matching/candidate_scoring.py` (new), `scripts/matching/decision_policy.py` (new), `scripts/matching/phonetic_match.py`, `scripts/matching/name_utils.py`, `scripts/matching/both_match.py`, `scripts/matching/fellegi_sunter.py`, `scripts/fag/scoring.py`, `scripts/fag/filters.py`, `scripts/fag/search.py`, `scripts/pipeline/scoring_constants.py`, `scripts/cgr/cgr_matcher.py`, `scripts/cgr/cgr_dedup.py`, `scripts/cgr/cgr_fag_dedup.py`, `scripts/ingest/validate_v5_ladder.py` plus focused tests.

**Blast-radius mix:** internal: 3; public-API: 0; on-disk: 0; cross-module: 3.

**Class mix:** polish: 1; redesign: 5.

**Coordination:** none.

**Risk callouts:** score/verdict behavior changes. Run historical state replay and ground-truth threshold comparison before switching policy version.

**Success criteria:**
- One NameEvidence extractor feeds FaG score, CGR match, dedup, and BOTH MATCH.
- One DecisionPolicy owns weights, thresholds, dominance gap, statuses, and refinement eligibility.
- Live and replay projection under same policy version produce same verdict.
- Fellegi-Sunter implementation uses actual m/u evidence and versioned feature schema.
- Evaluation imports production strategy/policy code; no shadow slug/name algorithms.

### Phase 4 — Provider safety and browser lifecycle

**Goal:** guarantee every FaG request uses one durable throttle/cooldown/session seam.

**Findings (6):** L3-02, L3-03, L3-05, L3-07, L4-04, L6-03.

**Files touched (13):** `scripts/fag/request_gate.py` (new), `scripts/fag/browser_session.py` (new), `scripts/fag/response_classifier.py` (new), `scripts/fag/fag_browser.py`, `scripts/fag/pw_session.py` (delete/absorb), `scripts/fag/search.py`, `scripts/fag/spouse_scrape.py`, `scripts/fag/rss_watchdog.py`, `scripts/cgr/spouse_compare.py`, `scripts/analysis/_probe_fag_filter.py`, `scripts/soak_memory.py`, `tests/test_intra_strategy_throttle.py`, new request-gate/session tests.

**Blast-radius mix:** internal: 3; public-API: 0; on-disk: 1; cross-module: 2.

**Class mix:** polish: 1; redesign: 5.

**Coordination:** none.

**Risk callouts:** throttle is non-negotiable. Any test double must preserve gate invocation; no “fast” production bypass. Live FaG smoke manual only.

**Success criteria:**
- All FaG search, memorial, warmup, retry, spouse, and probe navigations acquire same gate.
- Monotonic request starts remain ≥2.5s apart by default, including process/subprocess coordination.
- 1015/challenge posts durable provider cooldown; restart honors `not_before` before browser request.
- Browser reset always closes page→context→browser→Playwright and clears refs.
- Process-tree RSS test triggers reset/graceful checkpointed exit at configured bounds.
- Manual memory soak and targeted throttle/bot tests pass.

### Phase 5 — Event-guided scheduler skeleton

**Goal:** replace central god-loop control with scheduler that dispatches registered Knowledge Sources from durable work.

**Findings (1):** L1-01.

**Files touched (8):** `scripts/blackboard/scheduler.py` (new), `scripts/blackboard/knowledge_source.py` (new), `scripts/pipeline/run_unified.py`, `scripts/pipeline/core.py`, `scripts/pipeline/retry_errors.py`, `scripts/pipeline/leftover_investigation.py`, `tests/test_run_unified.py`, new scheduler tests.

**Blast-radius mix:** internal: 0; public-API: 0; on-disk: 0; cross-module: 1.

**Class mix:** polish: 0; redesign: 1.

**Coordination:** none.

**Risk callouts:** start broad-but-shallow: scheduler, registration, claims, and no-op/sample KS first. Do not migrate every source in one commit.

**Success criteria:**
- Scheduler claims one work item, loads observations, invokes eligible KS, atomically posts outputs/completion.
- Eligibility, priority, estimated request cost, and terminal/retry states are explicit.
- Crash between post and completion is idempotently recoverable.
- Existing CLI can run scheduler while legacy projection remains available.

### Phase 6 — Typed Knowledge Sources and multi-pass refinement

**Goal:** migrate ingestion, planning, FaG/CGR retrieval, and refinement to autonomous typed Knowledge Sources.

**Findings (7):** L1-04, L2-01, L3-01, L3-04, L4-01, L4-05, L6-01.

**Files touched (18):** `scripts/knowledge/__init__.py` (new), `scripts/knowledge/ingestion.py` (new), `scripts/knowledge/regional_planner.py` (new), `scripts/knowledge/fag_scraper.py` (new), `scripts/knowledge/cgr_fetcher.py` (new), `scripts/knowledge/candidate_scorer.py` (new), `scripts/knowledge/cgr_corroborator.py` (new), `scripts/knowledge/deep_refiner.py` (new), `scripts/search/strategies.py`, `scripts/fag/search.py`, `scripts/fag/parser.py`, `scripts/fag/state_io.py`, `scripts/cgr/cgr_client.py`, `scripts/cgr/cgr_enrich.py`, `scripts/cgr/cgr_ok_scraper.py`, `scripts/ingest/scrape_digitalprairie.py`, `scripts/ingest/fetch_pensioncard_pages.py`, `scripts/pipeline/leftover_investigation.py` plus KS integration tests.

**Blast-radius mix:** internal: 0; public-API: 1; on-disk: 2; cross-module: 4.

**Class mix:** polish: 0; redesign: 7.

**Coordination:** none.

**Risk callouts:** largest phase. Land one vertical flow first: persisted pensioner → regional plan → gated scrape → candidate observation → score → projection. Then add CGR/deep refinement.

**Success criteria:**
- Scraper executes exact persisted QueryPlan; follow-up params cannot be discarded.
- Regional and deep-refiner plans dedupe by deterministic plan ID and obey request budget.
- Raw fetch observation persists before parser/scorer work; parser/scorer can replay offline.
- Strategy/pass completion resumes independently; no full pensioner rerun after downstream failure.
- Legacy standalone writers removed or reduced to scheduler CLI shims.
- Full test suite plus 50-record controlled smoke meets existing hit/error expectations without throttle violation.

### Phase 7 — Projection and review migration

**Goal:** make current rows, reports, DD/CGR/spouse badges, and review export disposable projections from Blackboard facts.

**Findings (2):** L4-03, L5-05.

**Files touched (12):** `scripts/blackboard/projector.py` (new), `scripts/state_normalize.py`, `scripts/state/report_generator.py`, `scripts/cgr/cgr_fag_dedup.py`, `scripts/cgr/dixiedata_match.py`, `scripts/cgr/spouse_compare.py`, `scripts/pipeline/dd_marker.py`, `scripts/pipeline/run_unified.py`, `scripts/view.html`, `tests/test_view_html.py`, `tests/test_view_unified.py`, new projection replay tests.

**Blast-radius mix:** internal: 0; public-API: 0; on-disk: 1; cross-module: 1.

**Class mix:** polish: 0; redesign: 2.

**Coordination:** downstream review UI update in same commit where projection schema changes.

**Risk callouts:** cross-layer wire contract and stable key order. Preserve decisions CSV consumer `dd_marker_run.py`; dual-read old/new state during migration.

**Success criteria:**
- Rebuilding projection from same observation cursor is deterministic.
- CGR/DD/spouse passes append observations and never rewrite evidence.
- `state.jsonl`/`results.jsonl`, reports, and view badges come from same projector/policy version.
- Browser no longer reimplements domain normalization.
- Existing view round-trip and DD marker tests pass; old state imports still render.

### Dependency graph (phase-level)

```text
Phase 1 (Correctness + hygiene)
   ↓
Phase 2 (Blackboard contracts + store)
   ↓
   ├──► Phase 3 (Evidence + policy) ──────────┐
   ├──► Phase 4 (Provider safety) ────────────┤
   └──► Phase 5 (Scheduler skeleton) ─────────┤
                                              ↓
                    Phase 6 (Typed Knowledge Sources)
                                              ↓
                    Phase 7 (Projection migration)
```

### Phase scope summary

| Phase | Findings | Source/test files | Blast radius | Coordination |
|---|---:|---:|---|---|
| 1 — Correctness + hygiene | 7 | 14 | public-API | none |
| 2 — Contracts + store | 7 | 15 | on-disk | none |
| 3 — Evidence + policy | 6 | 15+ | cross-module | none |
| 4 — Provider safety | 6 | 13+ | cross-module | none |
| 5 — Scheduler skeleton | 1 | 8+ | cross-module | none |
| 6 — Typed Knowledge Sources | 7 | 18+ | cross-module | none |
| 7 — Projection migration | 2 | 12+ | cross-module/on-disk | review UI same commit |
| **Total** | **36** | **~55 unique** | — | — |

### Risk callouts (cross-phase)

1. Never weaken FaG 2.5s throttle, headful stealth, warmup, or full browser teardown during refactor.
2. Keep per-pensioner fsync projection until Blackboard store durability has kill/restart proof.
3. Treat state projection/UI/decisions CSV as coordinated cross-layer contract.
4. Migrate vertical slices; avoid “rewrite all 82 files” branch. Dual-write/dual-read until each slice proves parity.
5. Keep current user deletion `output/test-batch-25/view.html` untouched unless explicitly requested.

### Final tally

| Layer | Findings | Accepted | Withdrawn |
|---|---:|---:|---:|
| L0 — Operator surface | 3 | 3 | 0 |
| L1 — Orchestration | 4 | 4 | 0 |
| L2 — Matching/policy | 5 | 5 | 0 |
| L3 — Playwright/retrieval | 8 | 8 | 0 |
| L4 — CGR/cross-reference | 6 | 6 | 0 |
| L5 — Persistence/projections | 6 | 6 | 0 |
| L6 — Ingestion/analysis/migrations | 4 | 4 | 0 |
| **Total** | **36** | **36** | **0** |

**Cross-cuts closed by completion:** T1–T6.

Plan ready for per-phase blueprinting.
