# Runner Audit — Do We Build or Pull In An External Runner?

**Author:** Jeremy Morris (valueforvalue)
**Date:** 2026-07-22
**Scope:** Pipeline CLI runner + Playwright harness + Scheduler (per audit
request: "all of the above").
**Verdict:** **Keep the in-house runner. Do not adopt an external
orchestrator.** One optional lightweight wrap candidate is documented for
re-evaluation if scope grows.

---

## TL;DR

The current runner layer is purpose-built for this project's hard
constraints (L1 2.5 s throttle, L2 browser reset, L3/L5/L10 fsync
state.jsonl, L8 Playwright + stealth only, L11 deterministic obs-IDs,
L12 lease TTL). Every external runner candidate either (a) requires a
broker daemon we forbid, (b) is sized for thousands of scheduled DAGs
rather than 7.5 k sequential items, (c) is async-first and forces sync
Playwright into a thread adapter for no benefit, or (d) has a
built-in rate-limiter that fights the L1 floor. The Python standard
library already gives us everything we need (one `time.sleep` call
plus per-record fsync). No new dependency wins.

---

## Current runner layer — what's actually built

### Components

| File | Lines | Role |
|---|---:|---|
| `scripts/pipeline/run_unified.py` | 1,326 | Top-level CLI. Wires Pensioner inputs → Blackboard store → Scheduler → 7 KnowledgeSources → ProjectionBuilder → state.jsonl. Also owns the post-pass observers (DixieData, spouse, pensioncard pages, view.html copy). |
| `scripts/pipeline/core.py` | — | Per-pensioner pipeline (CGR blocking, outlier classification, FaG search call). Single function `run_pipeline_for_pensioner` is the contract target for the scheduler. |
| `scripts/blackboard/scheduler.py` | 100 | `BlackboardScheduler` — event-guided dispatcher. Loop: claim work → find eligible KS → invoke → persist observations → complete. |
| `scripts/blackboard/store.py` | 688 | `SqliteBlackboardStore` + `JsonlBlackboardStore` — durable work queue + observations. WAL mode. |
| `scripts/blackboard/decision_policy.py` | 232 | Single decision function for live + replay + dry-run. Imports thresholds from `scoring_constants` (L9). |
| `scripts/blackboard/projector.py` | 320 | Reduces Blackboard observations into `state.jsonl` rows. |
| `scripts/fag/browser_session.py` | 502 | `BrowserSession` — owns Playwright + stealth + warmup + throttle. L1 floor enforced in `__init__` (rejects < 2.5 s with `ValueError`). |
| `scripts/fag/request_gate.py` | 145 | `RequestGate` — provider-wide throttle seam. `acquire()` context manager with monotonic timing + cooldown support. |
| `scripts/fag/pw_session.py` | 110 | Older `PlaywrightSession` wrapper (kept for legacy paths; superseded by `BrowserSession` per cleanup PR #86). |
| `scripts/fag/playwright_leak_fix.py` | 80 | `apply_playwright_leak_fix()` — L2 in plain terms. |

### How the layers fit

```
                    run_unified.py (CLI)
                            │
                            ▼
                ┌──── BlackboardScheduler ────┐
                │      (loop, leases)         │
                │                             │
                │   register(KnowledgeSource) │
                └─────────────┬───────────────┘
                              │
         ┌────────┬──────────┼──────────┬────────────┐
         ▼        ▼          ▼          ▼            ▼
   RegionalPlannerKS FaGScraperKS CandidateScorerKS DeepRefinerKS
                       │
                       ▼
               BrowserSession (single owner)
                       │
                       ▼
               Playwright + stealth (sync API)
                       │
                       ▼
               RequestGate (throttle seam)
                       │
                       ▼
                findagrave.com
```

### 7 registered KnowledgeSources

1. `RegionalPlannerKS` — emits QueryPlans ranked by PlanRanker.
2. `FaGScraperKS` — runs BrowserSession per plan.
3. `CandidateScorerKS` — heuristic scoring.
4. `DeepRefinerKS` — DeepRefiner strategies after initial candidates.
5–7. Wired by post-pass observers (DixieData, spouse, pensioncard pages).

Lease semantics: 60 s TTL, max 3 attempts, exponential backoff
(`min(2 ** attempt, 60)`), `BLOCKED` after max attempts (L12).

### State + resume flow

```
pipeline.run_batch_scheduler (run_unified.py)
  ├── for each pensioner:
  │     ├── BlackboardStore.enqueue_work(WorkItem)
  │     ├── BlackboardScheduler.run()    ← drains all eligible work
  │     ├── BlackboardStore.read_observations_for_pensioner()
  │     ├── ProjectionBuilder.build_state_row()
  │     └── StateRepository.append(row)  ← flush + fsync per pensioner (L10)
  └── finally: browser_session.close()
```

Resume is dual-track:
- **WorkItem queue** — durable in SQLite-WAL. Crash mid-KS-invoke → lease
  expires → next run re-claims. (L12)
- **state.jsonl** — per-pensioner append. Crash mid-run → re-run with
  same `--state` path → `ResumeTracker.is_done(pid)` skips completed.
  (L3/L5/L10)

---

## Hard constraints (non-negotiable, from CONTEXT.md)

| # | Law | What it means for a runner |
|---|---|---|
| L1 | Throttle is the rate limit | Runner MUST enforce ≥ 2.5 s between FaG requests. `BrowserSession.__init__` already raises if asked below 2.5 s. |
| L2 | Browser reset on closed-target | Runner MUST support full page → context → browser teardown + `gc.collect()`. Periodic reset every 250 records is `BrowserSession.reset_every`. |
| L3/L5/L10 | Resume-safe state writes | Runner MUST fsync per pensioner. One JSON object per line. Wire format owned by `StateRepository`. |
| L8 | FaG via Playwright + stealth only | Runner MUST allow sync Playwright + `playwright-stealth` context. Async runners force an adapter. |
| L11 | Deterministic observation IDs | Runner MUST NOT pre-assign observation IDs; the store dedups. Huey/Prefect/etc. would have to be configured to defer ID assignment. |
| L12 | Lease TTL on dispatched work | Runner MUST recover crashed KS invocations within bounded time. No "fire and forget forever" model. |

---

## External candidate evaluation

**Scoring axes (0–5):**
- **A. Throttle** — enforce 2.5 s floor without fighting our own L1 limiter.
- **B. Resume** — per-item durable checkpoint + restart-from-done.
- **C. Integration** — host `KnowledgeSource` Protocol + `BlackboardScheduler`.
- **D. Overhead** — deps, daemon, memory.
- **E. Stealth/Playwright** — friction with browser lifecycle.

**Verdict key:** `drop-in` · `wrap in adapter` · `skip`.

### Comparison table

| # | Library | A | B | C | D | E | Verdict | Why |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| 1 | APScheduler | 3 | 1 | 2 | 5 | 4 | **skip** | Timer, not a queue. No durable per-job state, no leases. |
| 2 | Celery (eager mode) | 4 | 3 | 2 | 2 | 2 | **skip** | Serializes through one thread but pulls kombu/billiard/amqp/vine for 7.5 k items. Massive overkill. |
| 3 | RQ | 3 | 4 | 3 | 2 | 3 | **skip** | Requires Redis daemon — violates "no broker". |
| 4 | Dramatiq | 4 | 4 | 3 | 2 | 3 | **skip** | Same broker violation. Rate-limiter middleware operates per-task, not per-request. |
| 5 | Prefect 3 | 3 | 5 | 2 | 1 | 3 | **skip** | ~30 transitive deps, telemetry, replaces our SQLite blackboard. `global_concurrency_limit` has 30 s slot-decay — useless for 2.5 s floor. |
| 6 | Airflow | 2 | 5 | 1 | 0 | 2 | **skip** | DAG orchestrator + scheduler + webserver. Wrong scale entirely. |
| 7 | TaskTiger | 4 | 4 | 3 | 3 | 4 | **skip** | Requires Redis. Default fork-per-task hostile to a shared Playwright browser. |
| 8 | Invoke | 2 | 1 | 2 | 5 | 3 | **skip** | CLI runner, not a queue. No leases, no resume. Useful only as a wrapper around our existing CLI. |
| 9 | **Huey** | 4 | 4 | 4 | 4 | 3 | **wrap in adapter** | `SqliteHuey` + `immediate=True` = in-process, no daemon. Retries + revoke + `lock_task` map onto leases + 3-attempt cap. Adds 1 transitive dep (`python-dateutil`). |
| 10 | Procrastinate | 5 | 4 | 3 | 2 | 3 | **skip** | Postgres-only. Heavy broker ask for 7.5 k items. |
| 11 | arq | 4 | 4 | 2 | 3 | 2 | **skip** | Async-only → sync Playwright into `asyncio.to_thread`. Requires Redis. |
| 12 | Taskiq | 3 | 3 | 2 | 3 | 2 | **skip** | Async-first, broker overhead. No benefit over Huey. |
| 13 | **stdlib (`concurrent.futures`, `asyncio.Semaphore`)** | 5 | 1 | 5 | 5 | 4 | **drop-in** | What we already have. One `time.sleep(max(0, 2.5 - elapsed))` line. Zero new deps. |

### What external runners can't do for us

- **Per-URL floor vs per-task floor.** Every external rate-limiter we've
  inspected (Prefect `global_concurrency_limit`, Dramatiq rate-limit
  middleware, Celery `task_annotations.rate_limit`) operates at the
  *task* granularity. Our FaGScraperKS issues multiple `gate.wait()`
  calls per pensioner (one per strategy). A per-task limit would let
  us fire 13 strategies in < 1 second, then wait one task window — we
  would still trip Cloudflare 1015. Only the in-house `RequestGate`
  enforces per-URL monotonic spacing across the full process.
- **Lease-TTL recovery.** L12 is a domain-specific need (crashed
  Playwright KS wedging the queue). Huey's `lock_task` is close but
  still needs an adapter layer to expose `attempt`, `defer_retryable`,
  and `BLOCKED` transition.
- **Deterministic observation IDs (L11).** External runners assign
  their own IDs. The store dedups, but only because `append_observation`
  is the choke point — wrap any external runner in front of it and you
  end up calling our store anyway, at which point the runner adds zero
  value.

---

## Recommendation

### Primary: keep the in-house runner.

1. **Zero new dependencies.** Stdlib `time.sleep` + existing
   `RequestGate` + `BrowserSession` already give us L1 enforcement.
2. **Zero impedance mismatch.** `playwright-stealth` requires a sync
   context; every async-first runner (arq, Taskiq) forces an adapter.
3. **The cleanup is already happening.** PRs #86 and #87 (2026-07-22)
   just deleted 483 lines of legacy `run_batch()` and 15 orphan KS
   modules. The runner is shrinking, not stagnating.
4. **Resume + lease semantics are exactly right** for our domain
   (60 s lease, 3 attempts, fsync per record). External runners would
   require adapters to match.

### Optional follow-up (re-evaluate if scope grows):

- **Huey** is the only candidate that survives elimination. Its
  `SqliteHuey` + `immediate=True` mode is genuinely in-process and
  could replace `BlackboardScheduler.run()`'s inner loop. Worth a
  spike *only* if:
  - We add multiple engines running concurrently (currently
    sequential — one browser).
  - We want a richer retry policy (exponential + jitter, max
    attempts > 3).
  - We get tired of writing SQLite lease-TTL bookkeeping by hand.

  Even then, Huey *wraps* the SQLite blackboard rather than replacing
  it — adding a layer, not removing one. **Do not adopt today.**

### What NOT to build

- **A new orchestrator layer.** `run_unified.py` is already 1,326
  lines; further abstractions (DAGs, plugins) would add ceremony, not
  value, at 7.5 k items.
- **A CLI replacement.** Invoke / Fabric / Typer-style wrappers add no
  scheduling value. The current `argparse` CLI works.
- **A separate run-daemon.** The whole pipeline is single-process by
  design (one browser, one throttle, one state file). A daemon would
  split the throttle seam.

---

## Action items

- [ ] **No-op.** Documented this audit in `docs/research/runner-audit.md`.
- [ ] **If a Huey spike is desired:** open a new ticket in
      `docs/learnings/` with a 100-line prototype against
      `scripts/blackboard/scheduler.py`; do not change
      `run_unified.py` until the prototype passes the smoke suite
      (`tests/test_scheduler.py`, `tests/test_smoke_diff.py`).
- [ ] **Re-run this audit if any of these change:**
  - We add a second network provider with a different throttle.
  - We exceed ~50 k pensioners per run (where resume latency matters).
  - We add multiple concurrent workers (where lease semantics get
    contested).

---

## Sources

- [CONTEXT.md §L1–L12](../../CONTEXT.md) — project hard rules.
- [docs/agents/blackboard-architecture.md](../agents/blackboard-architecture.md)
  — Scheduler + Blackboard design.
- [docs/agents/search-abstraction.md](../agents/search-abstraction.md) —
  engine-agnostic search contract.
- [docs/agents/pipeline-architecture.md](../agents/pipeline-architecture.md)
  — Mermaid diagram of the current orchestration.
- [CHANGELOG.md #86, #87](../../CHANGELOG.md) — recent cleanup PRs.
- Huey library: <https://huey.readthedocs.io/en/latest/> (consulted for
  `SqliteHuey` + `immediate=True` mode).
- APScheduler 3.x docs: <https://apscheduler.readthedocs.io/en/3.x/>
  (consulted for in-process scheduling semantics).
- Prefect 3 docs: <https://docs.prefect.io/v3/> (consulted for
  `global_concurrency_limit` slot-decay behavior).