# Blackboard Architecture — Local-First Coordination

> **Tier:** 1 (load when touching the Scheduler, Knowledge
> Sources, DecisionPolicy, ProjectionBuilder, or the
> self-learning loop). Token cost: ~4K.

This document is the canonical reference for the Local-First
Blackboard that replaced the legacy per-pensioner god-loop.
For the visual how-the-parts-fit see
[`pipeline-architecture.md`](pipeline-architecture.md); for the
search abstraction (the layer the Blackboard wraps), see
[`search-abstraction.md`](search-abstraction.md).

---

## Why a Blackboard

The legacy pipeline ran a single tight loop:

```
for pensioner in ok_pensioners:
    cgr = blocking_lookup(pensioner)
    candidates = fag_search(pensioner)        # 12 strategies × 2.5s
    both_match = detect(cgr, candidates)
    decision = classify(both_match, candidates)
    write_state_row(pensioner, decision)      # flush + fsync
```

That worked but had three structural problems:

1. **Single-threaded, all-or-nothing.** A wedged FaG
   request blocked every pensioner behind it. There was no
   way to bound the blast radius of one bad record.
2. **No durable intermediate state.** A crash at record
   4,500 left no record of what strategies had fired or
   what candidates were on the shelf. The next run started
   from scratch.
3. **No separation of "what to do" from "how to do it."**
   The FaG-specific orchestration (CAPTCHA waits, 1015
   backoff, per-strategy throttle) was tangled with the
   per-record scoring and decision logic. Adding a 2nd
   engine meant editing the god-loop.

The Blackboard pattern fixes all three by separating **durable
state** (SQLite observations + work items) from **dispatch**
(the Scheduler) from **work** (Knowledge Sources).

---

## The four moving parts

```
   Knowledge Sources          Scheduler          ProjectionBuilder
   ─────────────────          ─────────          ─────────────────
   RegionalPlannerKS                              deterministic
        │                        │                reduce observations
        ▼                        │                → state.jsonl rows
   work item:                   │                  + stats + badges
   "plan a query"    ─────────►│
                          claims eligible
                          work items; honours
                          leases + cooldowns
                              │
                              ▼
                         FaGScraperKS
                              │
                              ▼
                         observations
                         (FaGSearchExecuted,
                          CGRCorroboration, etc.)
                              │
                              └────────► durable store (SQLite WAL)
```

### 1. Schema (`scripts/blackboard/schema.py`)

The Blackboard's data contracts. Versioned (`schema_version: int`)
so a replay can recover the exact shape.

- `RunManifest` — run configuration + lineage. Carries the
  `policy_version`, KS versions, and source-data fingerprints.
- `Observation` — a typed envelope written by a KS. Carries a
  `kind` from the `Kind` enum:
  `FaGSearchPlan`, `FaGSearchExecuted`, `CGRCorroboration`,
  `DixieDataMatch`, `SpouseMatch`, `ScoreObserved`,
  `DecisionObserved`, etc. Immutable; new state comes from
  appending a new observation, never mutating an old one.
- `WorkItem` — a unit of durable work. States:
  `READY → LEASED → SUCCEEDED / RETRYABLE / BLOCKED / TERMINAL`.
  Carries `attempts` and `last_error` so the Scheduler can
  bound retries and surface blocked work for human review.
- `QueryPlan` — a typed strategy execution plan. Carries the
  geographic scope (`OK → regiment → Texas → US`), the
  strategy name to run, the budget, and the planner that
  emitted it. Emitted by `RegionalPlannerKS`, consumed by
  `FaGScraperKS`. The PlanRanker reorders these per-pensioner.
- `ManifestBudget` — resource budget for one run dimension
  (`max_requests`, `max_wall_seconds`).

### 2. Store (`scripts/blackboard/store.py`)

Durable persistence. Two implementations behind the same
Protocol:

- `SqliteBlackboardStore` — production. WAL journal,
  IMMEDIATE transactions, leases with TTL.
- `JsonlBlackboardStore` — fallback for tests / read-only
  replay.

Methods: `append_observation`, `claim_next_work`,
`complete_work`, `reclaim_stale_leases`,
`load_manifest`, `iter_observations_by_kind`.

The store's `append_observation` enforces deterministic IDs
(L11): the ID is derived from the payload hash so a resume
never doubles the same logical event.

### 3. Scheduler (`scripts/blackboard/scheduler.py`)

Event-guided dispatcher. Loop:

```
1. claim next eligible work item (TTL-bound lease)
2. dispatch to the KS that owns the work kind
3. KS invokes → returns list of observations
4. persist observations
5. complete work item (SUCCEEDED / RETRYABLE / BLOCKED)
```

Honours cooldowns (provider rate limits), dedup (don't fire
the same plan twice for one pensioner), and budget
(`max_requests`, `max_wall_seconds`). On `RETRYABLE`, backs
off with a delayed retry; after 3 failed attempts the
work item transitions to `BLOCKED` for operator review.

### 4. DecisionPolicy (`scripts/blackboard/decision_policy.py`)

Single `classify()` entry point for **all** paths: live runs,
replays, dry-runs. Returns a `Decision` (status, top_score,
gap, threshold_used, policy_version).

When a `CalibratedClassifier` is supplied and threshold is
`"auto"`, uses the calibrated probability threshold instead
of the hardcoded constant. Imports all thresholds and status
strings from `scripts/pipeline/scoring_constants.py` (L9).

---

## Knowledge Sources

Seven domain agents registered with the Scheduler. Each KS
declares an `eligible_work_kinds` set, an `invoke(work_item) →
observations` method, and cooldown / budget gates.

| KS | Reads | Emits | Notes |
|---|---|---|---|
| `RegionalPlannerKS` | pensioner record, CGR index | `QueryPlan` × N | `OK → regiment → Texas → US` scope expansion. |
| `FaGScraperKS` | `QueryPlan`, BrowserSession | `FaGSearchExecuted`, `ScoreObserved` | Throttle + CAPTCHA waits inside; throttle lives here, not in the scheduler. |
| `CGRFetcherKS` | pensioner record | `CGRCorroboration` | Fast local lookup; no network. |
| `CandidateScorerKS` | `FaGSearchExecuted` | `ScoreObserved` (if missing) | Re-scoring when weights change. |
| `DeepRefinerKS` | `ScoreObserved` < threshold | `FaGSearchPlan` (follow-up) | Spouse + broadened-surname fallback. |
| `IngestionKS` | source-data fingerprints | `RunManifest` | Runs once at start; emits lineage. |
| `ProjectionKS` | all observations | writes `state.jsonl` | Deterministic; runs at checkpoint boundaries. |

A KS does **not** know about other KSs. The Blackboard is the
only shared state. Adding a new KS = declare its eligible
work kinds, write `invoke()`, register with the Scheduler.

### Provider safety (`scripts/blackboard/decision_policy.py`)

`BrowserSession` and `RequestGate` wrap the Playwright
session so KSs ask for a request instead of holding the
browser ref. Reverse-order teardown (`page → context →
browser`); cooldown between requests; classify response
(`normal`, `challenge`, `rate-limit`) before parsing.

These enforce L1 (throttle is the rate limit), L2 (browser
reset on closed-target), and L8 (no `requests.get()`) from
inside the Blackboard rather than scattering the discipline
across callers.

---

## ProjectionBuilder (`scripts/blackboard/projector.py`)

Deterministic reducer: observations → state.jsonl rows + per-
run stats + badges. Pure function. Idempotent (same
observations produce the same bytes). Called by `ProjectionKS`
at checkpoint boundaries (every N WorkItem completions, plus
at run end).

The builder emits one row per pensioner:

```
{
  "pensioner_id": ...,
  "common": { id, url, name, score, evidence, engine, media },
  "ranked_candidates": [...],   # engine-specific legacy
  "outcome": "auto_accept" | "ambiguous" | "too_many" | "no_results" | "error",
  "badges": ["cgr_match", "spouse_match", "dd_match", "needs_research", "follow_up"],
  "decision": {...},
  "scraped_at": ISO8601,
  "policy_version": "1",
}
```

`common` is the engine-agnostic shape every candidate gets
mapped into (see `SearchEngine.to_common_candidate()` in
[`search-abstraction.md`](search-abstraction.md)). The legacy
FaG fields stay alongside `common` for back-compat.

The `badges` array is the visible signal that drives v2 view's
filter chips (CGR-strong, spouse-match, follow-up, etc.).

### PostPassObserver (`scripts/blackboard/projector.py`)

After `ProjectionKS` writes the canonical row, `PostPassObserver`
runs read-only CGR / DD / spouse comparison passes and annotates
each row with the comparison status. **Read-only** — never
mutates the canonical row. The badges from this pass feed the
v2 view's "needs research" filter.

---

## The self-learning loop

After every batch the v2 view (in-browser) emits a sidecar
JSON with pick-vs-rank comparison data: `_picked_rank`,
`_score_gap_to_top`, `_winning_strategy`, `_feature_deltas`.

`scripts/learning/train.py` ingests that sidecar:

1. `LabelExtractor.from_decisions_file()` reads the sidecar
   + ground-truth CSV + CGR/spouse evidence, builds
   `LabelSnapshot` records, and stores them in SQLite
   with a temporal split (train = decisions before policy
   version N; eval = after).
2. `PriorRegistry.update_from_labels()` updates the four
   lookup tables (`state_likelihood`, `texas_likelihood`,
   `strategy_usefulness`, `match_probability`) and writes
   `priors_v2.json`.
3. `CalibratedClassifier.train()` fits a logistic regression
   on the labeled (top_score, accepted?) pairs and writes
   `classifier_v2.json`. The classifier exposes
   `threshold_for_precision(target=0.95)`.
4. `PairwiseWeightLearner.train()` fits logistic regression
   on the feature-delta pairs and outputs scoring-weight
   corrections that close the gap between auto-rank and
   human-decided rank.

The next run loads `priors_v2.json` + `classifier_v2.json`
and the `PlanRanker` reorders strategies per-pensioner while
`DecisionPolicy` auto-selects the calibrated threshold.

This loop is **advisory** — it ranks plans and tunes
thresholds, but it never overrides a hard safety gate (cooldown,
budget, dedup).

---

## Running the Blackboard

The CLI lives at `scripts/pipeline/run_unified.py`. Since
2026-07-19 it dispatches through the Blackboard by default
(`run_batch_scheduler`); the legacy god-loop
(`run_batch_scheduler` ← previous default `run_batch`) is
still importable for `leftover_investigation.py` and
`retry_errors.py` but is no longer the production path.

```bash
# Scaffold a v2 recipe
python scripts/pipeline/run_unified.py --init my-run-2026-07-20

# Run with default (Blackboard) path
python scripts/pipeline/run_unified.py --recipe my-run-recipe.json

# Dry-run (no FaG network): exercise non-FaG pipeline against
# an existing state.jsonl
python scripts/pipeline/run_unified.py --dry-run --recipe my-run-recipe.json

# State replay: re-score an old state.jsonl against the
# current scoring weights, write new state.jsonl
python scripts/pipeline/run_unified.py --state-replay old/state.jsonl \
    --recipe my-run-recipe.json

# Rollback to a named checkpoint
python scripts/pipeline/run_unified.py --rollback-to latest
```

The Blackboard path also exposes the reversibility flags
(`--write-checkpoint`, `--checkpoint-every`, `--list-checkpoints`)
from issue #21 — see
[`docs/agents/adr/0006-reversibility-flags.md`](adr/0006-reversibility-flags.md).

---

## Adding a new Knowledge Source

1. **Pick a `kind`** (extend `Kind` enum in `schema.py`).
2. **Define the observation shape** as a dataclass with
   `to_dict()` / `from_dict()`.
3. **Write the KS class** with `eligible_work_kinds`,
   `invoke(work_item) -> list[Observation]`, and any
   provider cooldowns.
4. **Register with the Scheduler** in
   `scripts/blackboard/scheduler.py::__init__`.
5. **Tests**: behavior tests for each invocation path
   (success / blocked / retryable / provider-cooldown).
   See `tests/test_blackboard_scheduler.py` for the template.

A KS is the unit the Scheduler knows about. Don't add KS
coupling to other KSs; communicate by writing observations.

---

## What this architecture is NOT

- ❌ Not a distributed system. SQLite WAL is local; no
  cross-process locking.
- ❌ Not real-time. The Scheduler loops every N seconds;
  events are pulled, not pushed.
- ❌ Not a queue framework. The Blackboard has durable
  state; the Scheduler doesn't promise delivery, just
  eventually-consistent progress.
- ❌ Not a state machine. `WorkItem` carries a state field
  but transitions are KS-driven, not declarative.

---

## Where to read more

- [`pipeline-architecture.md`](pipeline-architecture.md) —
  Mermaid + ASCII visual of how the parts fit
- [`search-abstraction.md`](search-abstraction.md) — how
  the engine layer the Blackboard wraps works
- `scripts/blackboard/` — schema, store, scheduler,
  projector
- `scripts/learning/` — self-learning loop
- `tests/test_blackboard_scheduler.py` — the test template
  for new KSs
- [`../learnings/2026-07-16-postrun-design.md`](../learnings/2026-07-16-postrun-design.md)
  — the post-run analysis the projection step replaces