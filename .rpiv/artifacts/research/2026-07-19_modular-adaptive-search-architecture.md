---
date: 2026-07-19T01:55:02-05:00
author: Jeremy Morris
commit: dd9695d888c04e5f1df045bff37faa05a1f329d5
branch: master
repository: FindAGraveHelper
topic: "modular adaptive Find a Grave search architecture"
tags: [research, architecture, blackboard, playwright, search-strategies, concurrency, state, matching]
status: ready
last_updated: 2026-07-19T01:55:02-05:00
last_updated_by: Jeremy Morris
---

# Research: Modular Adaptive Find a Grave Search Architecture

## Research Question

How should the current Python/Playwright Find a Grave search tool evolve from a sequential collection of scripts into an extensible system that supports multiple search strategies, geography-aware fallback rules, adaptive planning, refinement passes, weighted candidate scoring, bounded execution slices, durable resume, and carefully controlled concurrency?

This investigation intentionally audited live code and external architecture/concurrency references. The latest plan artifact was not used as source material.

## Summary

The repository already contains useful module boundaries: strategy generation, query filtering, DOM parsing, candidate scoring, browser lifecycle, pipeline orchestration, state persistence, replay, and human review. The main architectural weakness is not absence of modules. It is absence of canonical contracts between them.

`search_one_pensioner()` still owns strategy execution, URL decoration, Playwright navigation, challenge handling, parsing, merge, scoring, ranking, ground-truth checks, and status classification (`scripts/fag/search.py:223-506`). The strategy registry is extensible only at its surface: strategy functions use positional arguments and the executor contains label-specific branches (`scripts/fag/search.py:291-314`). All applicable strategies run before candidates are scored, so the system cannot stop early or select the next plan based on evidence (`scripts/fag/search.py:376-423`).

A lightweight Blackboard is a good fit for this problem because later search plans depend on accumulated observations, candidate evidence, prior attempts, and human decisions. Blackboard should coordinate evidence, plans, work state, provenance, and refinement. It should not be treated as a request-concurrency mechanism.

Recommended target is a hybrid:

- SQLite WAL as operational Blackboard.
- JSONL as compatibility/export projection for current tooling and `view.html`.
- Explicit planner that emits one typed search plan at a time.
- Single-owner, actor-like Playwright provider with one global throttle/cooldown gate.
- Bounded queues and parallel workers only for local CPU, parsing, scoring, replay, and projection work.
- One shared decision policy for live classification, dry-run, replay, and evaluation.

Do not add network concurrency first. First make plans, observations, decisions, and policy versions explicit and durable. Then optimize local work around one serialized FaG provider.

## Scope and Method

### Repository scope

Audited live code under:

- `scripts/fag/`
- `scripts/search/`
- `scripts/pipeline/`
- `scripts/state/`
- `scripts/view.html`
- `tests/`
- `CONTEXT.md`
- relevant architecture and agent guidance

External research covered Blackboard systems, Playwright threading/async usage, bounded asyncio queues, SQLite WAL, and adaptive throttling patterns.

### Validation

Repository test baseline at audit time:

- `pytest -q`
- **999 passed**

Passing tests do not establish that live search, replay, browser recovery, parser error paths, UI normalization, and state semantics agree. Many tests are source-shape or wiring checks rather than behavioral end-to-end checks.

## Current Architecture Findings

### Existing module seams are valuable

The repository has already extracted several concerns from the original script collection:

- strategy functions: `scripts/search/strategies.py:1-238`
- filters and location/date helpers: `scripts/fag/filters.py:1-449`
- result parser and merge: `scripts/fag/parser.py:1-308`
- candidate scorer: `scripts/fag/scoring.py:1-225`
- Playwright browser adapter: `scripts/fag/fag_browser.py:1-405`
- unified pipeline: `scripts/pipeline/core.py:243-317`, `scripts/pipeline/run_unified.py:530-730`
- durable state repository: `scripts/state/repository.py:103-278`
- replay/dry-run: `scripts/pipeline/dry_run.py:71-178`, `scripts/pipeline/state_replay.py`
- static review projection: `scripts/view.html:531-653`

These should be preserved and deepened rather than replaced with a generic framework.

### Orchestration remains monolithic

`search_one_pensioner()` is the current retrieval engine, scorer, and decision engine in one function:

1. derive search context and state scope (`scripts/fag/search.py:243-284`)
2. iterate fixed strategies (`scripts/fag/search.py:291-299`)
3. inject location, ACW date window, and spouse filters (`scripts/fag/search.py:301-314`)
4. navigate and detect challenge/rate-limit pages (`scripts/fag/search.py:326-374`)
5. parse candidates (`scripts/fag/search.py:376-405`)
6. merge and score only after ladder exhaustion (`scripts/fag/search.py:415-423`)
7. derive status from score, candidate count, and top-two gap (`scripts/fag/search.py:459-504`)

This shape prevents adaptive next-step decisions. Strategy N has no structured access to strategy N-1 evidence.

### Strategy contract is too weak

`STRATEGIES` is an ordered list of `(label, function)` tuples (`scripts/search/strategies.py:227-238`). Strategy functions receive positional primitives. The executor handles special cases by comparing string labels (`scripts/fag/search.py:291-298`).

Observed consequences:

- adding a strategy requires coordination between registry labels and executor branches
- richer pensioner context cannot be expressed through the ordinary signature
- special strategies are hidden behind string comparisons
- positional argument mistakes can change query semantics
- strategy metadata such as cost, scope, information target, and stop conditions has no representation

Concrete defect: `strategy_with_birth_year()` declares its fifth argument as `exact=False` (`scripts/search/strategies.py:124-151`), while the generic executor passes death year as its fifth positional argument (`scripts/fag/search.py:297-298`). A truthy death year therefore accidentally selects exact birth-year filtering.

### Strategy ladder has no early stop or refinement

The implementation explicitly collects all successful strategy results and waits until the end to merge and score (`scripts/fag/search.py:407-423`). The fixed ladder currently has ten entries (`scripts/search/strategies.py:227-238`).

Current behavior does not support:

- stop after decisive candidate
- skip if existing evidence is sufficient
- choose next strategy based on candidate count or score
- target missing veteran/date/spouse evidence
- separate retrieval scope from query shape
- refine top-N candidates after merge
- resume at strategy level

The only adaptive search-scope behavior is optional OK-to-US auto-relax in the browser adapter (`scripts/fag/fag_browser.py:351-387`).

### Geography policy is partly present but hard-coded

The unified CLI defaults FaG state filtering to OK (`scripts/pipeline/run_unified.py:1347-1360`). The search function can also derive a state from regiment text when no explicit filter is supplied (`scripts/fag/search.py:246-249`). Filter application adds state/country, ACW date bounds, and spouse linkage to every strategy (`scripts/fag/filters.py:140-170`).

This supports the project’s intended priority direction but does not model it as a policy:

1. Oklahoma
2. regiment-origin or likely unit state
3. Texas when reconstruction/migration evidence supports it
4. other inferred likely states
5. US-wide fallback last

The current auto-relax path reruns the entire ladder at US scope and selects the broader result based on candidate count (`scripts/fag/fag_browser.py:369-387`). More candidates usually means more noise, so this is not a reliable quality comparison. The narrow and broad observations are not retained together as first-class search evidence.

There are also two contradictory location-ID maps:

- `scripts/fag/filters.py:18-33`
- `scripts/fag/search.py:145-177`

They disagree for several states. `apply_location_filter()` uses the filters module map (`scripts/fag/filters.py:151-160`), while compatibility imports can expose the search module map.

### Candidate harvesting and provenance are lossy

Each strategy parses at most 20 links (`scripts/fag/parser.py:15-17`, `94-101`, `247-248`). After merge, the legacy result retains at most 20 candidates (`scripts/fag/search.py:123-124`, `415-423`). The parser extracts a total count, but status uses merged candidate count rather than reliable total/truncation metadata (`scripts/fag/parser.py:64-89`, `scripts/fag/search.py:459-504`).

`merge_candidates()` deduplicates by `memorial_id` and keeps the first occurrence (`scripts/fag/parser.py:289-308`). Later observations add only a strategy name to `via_strategies`; later effective parameters, rank, result totals, warnings, and richer evidence are discarded.

This prevents high-quality adaptive decisions. The system cannot reliably distinguish:

- no results
- known small result set
- truncated result set
- parser warning
- candidate found by multiple independent queries
- candidate found only by broad noisy query

The natural seam is a typed harvest/observation contract that preserves count knowledge, truncation, candidate observations, effective query, rank, and parser warnings.

### Parser has error-path correctness gaps

`scripts/fag/parser.py` uses `PWTimeout` and `log` without importing or defining them (`scripts/fag/parser.py:11`, `48`, `89`, `103`). The ordinary successful path can avoid these names, so the defects remain latent until timeout, large-result, or locator-failure paths.

Cleanup is performed after candidate iteration rather than under a `finally` boundary (`scripts/fag/parser.py:250-280`). Unexpected extraction failures can retain Playwright locator references longer than intended.

These must be corrected before evaluating strategy performance or adding concurrency around local parsing.

### Scoring and status policies drift

Live scoring is implemented in `scripts/fag/scoring.py:22-173`. The effective weighted score ceiling is approximately 0.789 because feature values such as veteran, death, OK burial, and state are themselves below 1.0 before weights are applied. Comments claim a perfect score of 1.00 (`scripts/fag/scoring.py:143-153`), but the executable formula does not reach that value.

Live status thresholds are local to `scripts/fag/search.py`:

- `AUTO_ACCEPT_THRESHOLD = 0.70`
- `AUTO_ACCEPT_THRESHOLD_NO_DEATH = 0.60`
- `AUTO_ACCEPT_GAP = 0.10`

(`scripts/fag/search.py:109-124`)

Replay/dry-run uses separate constants:

- `AUTO_ACCEPT_THRESHOLD = 0.85`
- `LOW_SCORE_THRESHOLD = 0.40`

(`scripts/pipeline/scoring_constants.py:22-37`)

Live status additionally uses candidate cardinality and top-two gap (`scripts/fag/search.py:477-504`). Dry-run uses highest stored score and a score-only classifier (`scripts/pipeline/dry_run.py:93-118`). Therefore replay is not a faithful simulation of live decisions.

There is no score-policy or scorer-version field in persisted candidate evidence. Historical scores cannot be cleanly attributed to a scoring implementation without external repository history.

### Persistence is stronger in unified path than standalone path

Unified writes go through `JsonlStateRepository.append()`, which flushes and calls `os.fsync()` before returning (`scripts/state/repository.py:168-175`). The standalone FaG writer calls `flush()` but not `fsync()` (`scripts/fag/state_io.py:52-58`). This violates the project’s L3 durability law for standalone successful records.

Resume currently treats any valid row with `pensioner_id` as complete (`scripts/pipeline/run_unified.py:223-250`). That includes error rows and incomplete rows. Resume is pensioner-granular, not plan- or strategy-granular. A crash during one pensioner restarts its entire strategy ladder.

### Time slicing is record-based, not time-based

`run_batch()` processes remaining pensioners sequentially (`scripts/pipeline/run_unified.py:598-635`). `limit` bounds record count, while checkpoint cadence is also record-count based (`scripts/pipeline/run_unified.py:711-721`). A single pensioner can incur multiple 20-second navigation timeouts, 30/60/120-second backoffs, and an optional second ladder through auto-relax (`scripts/fag/search.py:326-405`, `scripts/fag/fag_browser.py:351-387`).

A work slice therefore needs both record and wall-clock budgets.

### Browser lifecycle is intentionally serialized

The unified browser adapter owns one Playwright page and places a lock around the entire call (`scripts/fag/fag_browser.py:176-186`, `288-405`). It throttles between pensioner search starts and passes throttle into the strategy ladder (`scripts/fag/fag_browser.py:307-319`). The standalone runner uses one browser without the adapter’s periodic reset/recovery protections (`scripts/fag/search.py:611-653`).

The adapter already implies the correct concurrency boundary: one owner for mutable browser state. It should become an explicit provider actor/worker rather than a closure with hidden lifecycle state.

Observed lifecycle gaps:

- `reset_browser_every=0` can cause modulo-zero (`scripts/fag/fag_browser.py:289-292`)
- warmup result is ignored when opening a replacement browser (`scripts/fag/fag_browser.py:227-235`)
- reset failure can leave unusable state
- target-closed recovery prepares the next record but does not retry the failed record (`scripts/fag/fag_browser.py:320-349`)
- auto-relax failures bypass normal recovery (`scripts/fag/fag_browser.py:368-377`)
- returned internal error statuses do not consistently trigger the configured fatal-error cutoff (`scripts/fag/fag_browser.py:389-405`)
- no explicit close/context-manager API is returned

## External Architecture Research

### Blackboard

Blackboard systems use a shared problem state, independent knowledge sources, and a control component. This maps well to adaptive pensioner search:

- shared state: pensioner facts, candidate evidence, prior observations, decisions
- knowledge sources: name strategies, unit-state rules, Texas migration rules, spouse rules, scoring rules, refinement rules
- control: planner deciding which eligible plan to execute next

Blackboard should remain small and explicit. A generic inference engine would add complexity without solving the primary bottleneck. Deterministic eligibility rules are preferable to independent knowledge sources polling and racing over shared state.

### Actor-like provider owner

An actor-like component is appropriate for the browser because it owns mutable state and receives commands. It should own:

- Playwright lifecycle
- page/context/browser references
- warmup and resets
- request gate and cooldown
- challenge/error classification
- cancellation and teardown

A full actor framework is unnecessary. One task or worker with a bounded mailbox gives the needed ownership boundary.

Playwright documents that its Python API is not thread-safe. If multiple threads are used, each requires its own Playwright instance. That is not a reason to create multiple FaG workers; separate browser instances would multiply origin activity and complicate global throttling.

### Queues and pipes

Queues are useful for backpressure, but a bounded queue is not a rate limiter. A semaphore limits active critical sections but does not guarantee spacing between operations. A separate monotonic time gate is required.

Pipes-and-filters fit deterministic local stages:

```text
raw observation → normalized candidate → score → projection
```

They are not sufficient as the primary controller because this workflow is not strictly linear. Search may fetch, inspect evidence, generate a new plan, or stop.

Adaptive throttling patterns are useful as inspiration: delays should increase after errors/latency and should not become more aggressive merely because recent operations succeeded. For this project, the existing empirical 2.5-second floor remains a hard minimum; adaptive behavior may only move slower.

## Recommended Target Architecture

### Domain model

Introduce typed internal models, using dataclasses or equivalent stable DTOs:

- `Pensioner`
- `SearchContext`
- `SearchPlan`
- `SearchObservation`
- `Candidate`
- `CandidateObservation`
- `Decision`
- `WorkItem`
- `ProviderHealth`

Keep compatibility conversion at boundaries so `view.html` and existing JSONL consumers do not force dictionaries through the entire core.

### Search strategy protocol

Replace positional tuple strategies with a protocol that receives `SearchContext` and returns a `SearchPlan` or no plan. Strategy metadata should include:

- stable strategy ID
- phase/category
- applicability predicate
- scope requirements
- expected evidence target
- estimated request cost
- parent/refinement relationship
- policy/version identifier

A strategy proposes a query. It does not own Playwright navigation, parsing, scoring, or final status.

Effective query decoration should be explicit. Store both:

- base query proposed by strategy
- effective query after location/date/spouse policy

This makes every request auditable and lets future policy change distinguish strategy intent from global filter behavior.

### Planner and Blackboard

Planner loop:

1. load pensioner context and prior observations
2. select next eligible plan
3. send plan to provider actor
4. persist raw/normalized observation
5. merge candidate evidence
6. score and classify locally
7. stop or generate next refinement

Do not enqueue the entire ladder at startup. Generate one plan at a time so the next decision uses current evidence.

Persist at least:

- plan identity and lineage
- rationale and expected information gain
- effective query
- observation status
- candidate observations
- work state
- retry/cooldown deadline
- policy/scorer versions
- provider health events
- decision history

### Geographic policy

Represent search scopes as ranked policy rules rather than branches embedded in `search_one_pensioner()`:

1. Oklahoma
2. known burial/residence state
3. regiment-origin state
4. Texas when migration evidence applies
5. other inferred likely states
6. US-wide fallback

Each rule should declare applicability, priority, rationale, evidence source, and cost. A candidate’s burial outside Oklahoma should not be treated as negative identity evidence merely because Oklahoma was first scope. Scope should influence retrieval priority and evidence provenance, not dominate identity scoring.

### Provider actor and gate

Use one provider owner for all FaG operations. Required controls:

- one active top-level navigation
- one process-wide/provider-wide gate
- minimum 2.5-second spacing or slower
- no burst allowance
- all strategies, scopes, detail pages, and refinement passes share gate
- cooldown state becomes durable and origin-wide within the application
- browser reset closes page, context, browser, drops references, and collects garbage
- explicit close method/context manager

Local concurrency may operate around this owner:

- input preprocessing
- name normalization
- historical feature calculation
- parsing of already captured data
- scoring
- replay
- report/projection generation

Do not run multiple workers against the same browser page. Do not use separate processes that share one state file or independently maintain throttle state.

### Observation and candidate model

Replace `(total, candidates)` with a structured harvest result containing:

- total count
- whether total count was known
- candidates
- links examined
- truncation flag
- parser warnings
- effective query
- fetch timestamp

Candidate identity remains `memorial_id`, but candidate evidence becomes many-to-many. Preserve every observation with strategy, query, rank, timestamp, raw/normalized evidence, and parser version. Merge should aggregate evidence rather than retain only the first occurrence.

### Shared decision policy

Create one decision function used by live search, replay, dry-run, and evaluation. Inputs should include:

- ranked candidate scores
- candidate count
- top-two gap
- truncation state
- date compatibility
- local death-year availability
- evidence completeness
- parser/provider warnings
- policy version

The decision must not auto-accept a candidate solely because it has a high score when result harvesting was truncated or provider/parser state is uncertain.

### SQLite operational Blackboard and JSONL projection

Use SQLite WAL as the operational store. It provides indexed lookup, transactional state transitions, durable work items, plan lineage, candidate observation deduplication, and safer local coordination than append-only JSONL.

Suggested operational entities:

- `pensioners`
- `derived_facts`
- `search_plans`
- `work_items`
- `observations`
- `candidates`
- `candidate_observations`
- `decisions`
- `provider_events`
- `policy_versions`

Keep JSONL as an outward projection during migration:

```text
SQLite Blackboard → results.jsonl → view.html
```

The projection preserves current review tooling while removing operational dependence on full-file scans and append-only row semantics. Existing JSONL should remain importable for replay and rollback during transition.

## Adaptive Search Policy

### Preprocessing

Compute once before network work:

- normalized name variants
- nickname candidates
- slug-shape expectations
- birth/death confidence
- regiment and company facts
- unit-origin state candidates
- Oklahoma association facts
- spouse facts
- Texas/migration evidence
- prior search observations

Derived facts require a version so a policy change does not silently reinterpret old evidence.

### Plan selection

A plan should be eligible only when it has a reason to add information. Examples:

- Oklahoma returned no candidates → try unit-origin state
- name candidate found but no veteran evidence → try veteran/context query
- two candidates have close scores → target missing date/spouse evidence
- state result weak and migration evidence exists → try Texas
- narrow scopes exhausted → try US-wide last
- result page truncated → refine or mark review-required

Deduplicate equivalent effective queries before sending them to the provider.

### Stop conditions

Stop when the decision policy is satisfied, for example:

- score exceeds calibrated acceptance threshold
- top-two gap is sufficient
- candidate evidence is not truncated
- dates are compatible
- no unresolved parser/provider warning
- per-pensioner request and time budgets remain respected

Stop also on terminal provider conditions. Do not continue a ladder through a known cooldown/challenge state merely because plans remain queued.

### Refinement passes

Refinement should be first-class work, not an implicit second call to the entire ladder. Triggers include:

- no candidates
- only impossible-date candidates
- weak name but strong year evidence
- strong name but missing veteran/date evidence
- top-two scores too close
- known spouse not represented
- narrow scope exhausted
- harvest truncated
- parser warning

Each refinement records target evidence, parent observation, expected benefit, and maximum cost. This prevents repetitive searches that cannot change the decision.

## Self-Learning Boundary

Start with versioned deterministic priors, not autonomous strategy mutation. Useful initial priors include:

- state likelihood conditioned on regiment/unit
- Texas likelihood conditioned on migration evidence
- strategy usefulness conditioned on pensioner data shape
- match probability conditioned on scored evidence

Training labels can come from:

- human review decisions
- ground-truth CSV
- CGR corroboration
- confirmed spouse links
- accepted/rejected candidate history

The learner should rank eligible plans and scopes. It should not bypass hard constraints, throttle, evidence requirements, or terminal safety states.

A later calibrated classifier can improve candidate ranking, but it requires scorer/policy versioning, held-out evaluation, precision-first acceptance criteria, and leakage controls. Historical labels must not be used to tune and evaluate the same decision boundary without separation.

## Migration Sequence

### Phase 0 — Correctness baseline

Resolve existing defects before architectural expansion:

- parser imports and exception-path cleanup
- legacy writer fsync
- single location-ID catalog
- typed strategy invocation context
- positive reset interval validation
- explicit browser teardown
- retryable versus terminal error state
- score ceiling and threshold reconciliation
- behavioral status/replay tests

### Phase 1 — Canonical contracts

Introduce typed plan, observation, candidate-evidence, and decision contracts while retaining compatibility adapters for current dicts and JSONL.

### Phase 2 — Incremental ladder

Change execution from:

```text
run all strategies → merge → score → decide
```

to:

```text
propose → fetch → parse → merge → score → decide → next plan or stop
```

Add early stop, per-pensioner request budget, per-pensioner time budget, strategy applicability metadata, and full provenance.

### Phase 3 — Durable operational Blackboard

Add SQLite WAL storage for plans, work items, observations, decisions, and provider state. Keep JSONL projection and current review UI.

### Phase 4 — Geography rules

Move Oklahoma, unit-origin, Texas, inferred-state, and US-wide ordering into configurable policy rules with rationale and evidence sources.

### Phase 5 — Replay and learning

Make replay invoke the shared scorer and decision policy against historical observations. Add evaluation reports and only then use confirmed outcomes to rank future plan selection.

## Verification Notes

The following claims need actionable tests or probes during implementation:

- **Strategy context contract:** test every registered strategy through one typed invocation path; cover strategies requiring pensioner metadata.
- **Incremental decision loop:** fake provider observations and verify early stop, refinement, no duplicate effective queries, and per-pensioner budgets.
- **Geography ordering:** given a pensioner with regiment state and Texas evidence, verify OK → regiment-origin → TX → US ordering and rationale persistence.
- **Throttle ownership:** concurrent local callers must still produce one serialized provider sequence with monotonic minimum spacing.
- **Provider recovery:** test target-closed errors, failed reopen, auto-relax recovery, reset interval validation, and explicit teardown.
- **Harvest contract:** test known/unknown totals, truncation, duplicate links, richer duplicate observations, and parser exceptions with cleanup.
- **Decision parity:** run same candidate evidence through live classification, replay, and dry-run; require identical result for same policy/version.
- **Score calibration:** test theoretical score maximum, breakdown values, scorer version, and threshold reachability.
- **Resume semantics:** retryable error rows must not be treated as terminal; interrupted work must resume from durable plan/work state.
- **Slice budgets:** verify wall-clock and request budgets stop work before next plan and persist `not_before`/resume state.
- **SQLite projection:** round-trip SQLite records to JSONL and load them in current `view.html` without changing review decisions.
- **State durability:** preserve L3/L4/L5 tests for JSONL projection while testing SQLite transaction recovery separately.

## Precedents & Lessons

### Precedent: centralized scoring/status constants

**Commit:** `c3ce65b9bdfe69b0519aa6728dfeb512a374dc1e` — `refactor(pipeline): extract scoring + status constants to scoring_constants.py` (2026-07-17)

**Lesson:** the repository already recognized duplicated thresholds and status strings as drift risk. The extraction improved one path but did not unify live FaG classification with replay. A future canonical policy must be consumed by both paths, not merely centralize dry-run constants.

### Precedent: durable replay and rollback controls

**Commit:** `57225ddc5818e56e5c2dc55603a4f7851c5eac75` — `feat(run_unified): add --dry-run, --state-replay, --rollback-to` (2026-07-17)

**Lesson:** reversibility and offline replay are existing project priorities. The next design should preserve these affordances while making replay evidence-based and policy-faithful.

### Precedent: auto-relax scope fallback

**Commit:** `741c99d0fa08c24433fbe9e336355a11be1b548e` — `Enhancements #14 + #15: top-N spouse scrape + auto-relax state filter` (2026-07-16)

**Lesson:** geography broadening is already a domain requirement, but the current implementation is environment-gated, reruns a full ladder, and selects by candidate count. This behavior should become explicit planner policy with retained narrow and broad observations.

### Composite lessons

- Existing refactors extract modules successfully, but no single canonical contract yet governs live search, replay, state, and UI.
- Reversibility is valuable; durable observations are more useful than only durable final rows.
- Search scope and identity evidence are different concepts and should not be collapsed into one score feature.
- Concurrency around a protected browser is the wrong optimization target; eliminate redundant plans and parallelize local work instead.

## Architecture Insights

- **Blackboard is a coordination model, not a rate-limit model.** It should answer “what evidence exists and what should happen next?” The provider gate answers “when may one browser operation happen?”
- **The key unit should become a plan observation, not a script invocation.** A plan has intent, scope, cost, lineage, and expected evidence. An observation records what actually happened.
- **Candidate provenance is part of evidence, not display metadata.** Strategy, scope, effective query, rank, and truncation affect decision confidence.
- **A score without policy/version context is not reproducible.** Persist scorer and decision versions with candidate evidence and decisions.
- **JSONL is a good projection and recovery format, but a poor coordination database.** SQLite should own operational transitions; JSONL should remain a stable interchange/review surface.
- **Time budget is a first-class constraint.** Record count alone cannot bound a slice when timeout and cooldown paths are long.

## Code References

- `scripts/fag/search.py:223-506` — monolithic per-pensioner ladder, scoring, and status path.
- `scripts/search/strategies.py:1-238` — pure strategy functions and ordered registry.
- `scripts/fag/filters.py:140-170` — global location/date/spouse query decoration.
- `scripts/fag/parser.py:28-308` — Playwright harvest, cap, cleanup, and candidate merge.
- `scripts/fag/scoring.py:22-173` — candidate score and breakdown calculation.
- `scripts/fag/fag_browser.py:115-405` — browser owner, throttling, reset, recovery, and auto-relax.
- `scripts/fag/state_io.py:14-58` — standalone JSONL resume and writer.
- `scripts/state/repository.py:103-278` — durable JSONL repository contract and implementation.
- `scripts/pipeline/run_unified.py:223-250` — ID-based resume tracker.
- `scripts/pipeline/run_unified.py:530-730` — sequential unified batch loop and checkpoints.
- `scripts/pipeline/dry_run.py:71-118` — score-only replay classifier.
- `scripts/pipeline/scoring_constants.py:22-130` — separate replay thresholds and status helpers.
- `scripts/view.html:531-653` — legacy/unified state normalization.
- `tests/` — 999-test regression baseline; behavior gaps noted above.

## Integration Points

### Inbound references

- `scripts/pipeline/core.py:289-305` — invokes FaG adapter and stores returned candidates/status.
- `scripts/pipeline/run_unified.py:1342-1361` — constructs browser adapter and injects it into batch config.
- `scripts/fag/fag_browser.py:14-20` — imports legacy search entry points.
- `scripts/search_fag.py:1-14` — compatibility facade re-exports search symbols.
- `scripts/view.html:531-653` — consumes legacy and unified candidate shapes.
- `scripts/pipeline/state_replay.py` — consumes persisted records for offline transformation.

### Outbound dependencies

- Playwright sync API in `scripts/fag/search.py:611-653` and `scripts/fag/fag_browser.py:166-238`.
- `playwright-stealth` in `scripts/fag/search.py:168-194`.
- CGR matching/indexing in `scripts/pipeline/core.py:270-317`.
- State repository in `scripts/pipeline/run_unified.py:554-664`.
- Scoring and name utilities in `scripts/fag/scoring.py:11-19`.

### Infrastructure wiring

- `scripts/pipeline/run_unified.py:1342-1361` — FaG browser construction.
- `scripts/pipeline/run_unified.py:635-721` — sequential processing, state append, outlier append, and checkpoint cadence.
- `scripts/fag/fag_browser.py:288-405` — lock, throttle, reset, recovery, and result conversion.
- `scripts/state/repository.py:168-175` — flush/fsync append contract.
- `scripts/view.html:567-653` — browser-side record normalization and compatibility projection.

## Developer Context

**Q (`scripts/state/repository.py:168-175`, `scripts/view.html:531-653`): Should operational Blackboard storage target SQLite, JSONL first, or remain open?**

A: Use SQLite WAL as operational Blackboard. Keep JSONL as compatibility/export projection for current state readers and `view.html` during migration.

## Related Research

- External architecture references listed under `Sources`.
- Live-code audit findings are consolidated in this artifact; no latest plan artifact was used.

## Open Questions

- Which SQLite schema and migration mechanism best fits the project’s current single-operator workflow?
- Should one operational run have one SQLite database, or should multiple runs share a database with run IDs?
- What exact evidence threshold is required for auto-accept, and should thresholds be calibrated from confirmed human decisions before changing live behavior?
- Which geographic priors can be supported by existing pensioner/unit data, and which require a separate historical data-ingestion step?
- Should the first migration preserve the existing `search_one_pensioner()` facade or introduce a new planner/provider API alongside it?
- What is the desired policy for retrying records currently written with `status="error"`?

## Sources

- [Nii, Blackboard Systems](https://ojs.aaai.org/aimagazine/index.php/aimagazine/article/view/537)
- [Playwright Python library usage and threading](https://playwright.dev/python/docs/library)
- [Python asyncio queues](https://docs.python.org/3/library/asyncio-queue.html)
- [Scrapy AutoThrottle](https://docs.scrapy.org/en/latest/topics/autothrottle.html)
- [SQLite WAL concurrency](https://sqlite.org/wal.html#concurrency)
- [Akka Typed actor introduction](https://doc.akka.io/libraries/akka-core/current/typed/guide/actors-intro.html)
- [Azure Queue-Based Load Leveling](https://learn.microsoft.com/en-us/azure/architecture/patterns/queue-based-load-leveling)
- [Azure Pipes and Filters](https://learn.microsoft.com/en-us/azure/architecture/patterns/pipes-and-filters)
