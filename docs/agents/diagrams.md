# Diagrams — Blackboard Data Model + Flows

> **Tier:** 1 (load when designing a new Knowledge Source,
> reading the schema, or wiring a new flow). Token cost: ~3K.
>
> Companion to [`blackboard-architecture.md`](blackboard-architecture.md).
> That doc explains *why*; this one shows *what* — the
> versioned data model, the per-pensioner flow, the self-
> learning loop, and the WorkItem lifecycle.

Renders inline on GitHub (issues, PRs, README). All four
diagrams are Mermaid.

---

## 1. Class diagram — Blackboard data model

```mermaid
classDiagram
    class RunManifest {
        +str manifest_id
        +str run_id
        +str parent_manifest_id
        +str policy_version
        +dict~str,str~ knowledge_source_versions
        +ManifestBudget scheduler_budget
        +ManifestBudget bot_budget
        +dict~str,str~ source_fingerprints
        +str created_at
        +to_dict() dict
        +from_dict(d) RunManifest
    }

    class ManifestBudget {
        +int|None max_requests
        +int|None max_wall_seconds
    }

    class Observation {
        +str observation_id
        +int pensioner_id
        +Kind kind
        +str source
        +str source_version
        +str run_id
        +str pass_id
        +str|None caused_by
        +str recorded_at
        +dict payload
        +to_dict() dict
        +from_dict(d) Observation
    }

    class Kind {
        <<enumeration>>
        FaGSearchPlan
        FaGCandidateFetch
        CGRCorroboration
        DixieDataMatch
        SpouseMatch
        BotWallObserved
        MemoryPressureObserved
        ParseError
        PensionerImported
        ScoreObserved
        DecisionObserved
    }

    class WorkItem {
        +str work_id
        +int pensioner_id
        +str knowledge_source
        +str|None plan_id
        +str pass_id
        +int input_revision
        +WorkState state
        +int attempt
        +str|None not_before
        +str|None leased_by
        +str|None completed_at
        +list~dict~ attempts
        +to_dict() dict
        +from_dict(d) WorkItem
    }

    class WorkAttempt {
        +int attempt
        +str leased_at
        +str leased_by
        +str completed_at
        +str|None error
    }

    class WorkState {
        <<enumeration>>
        READY
        LEASED
        SUCCEEDED
        RETRYABLE
        BLOCKED
        TERMINAL
    }

    class QueryPlan {
        +str plan_id
        +int pensioner_id
        +str strategy
        +dict params
        +PlanScope scope
        +str reason
        +int estimated_requests
        +str policy_version
        +to_dict() dict
        +from_dict(d) QueryPlan
    }

    class PlanScope {
        <<enumeration>>
        US
        OK
        Global
        MemorialDetail
        RegimentOrigin
        Texas
        Inferred
    }

    RunManifest "1" --> "1" ManifestBudget : scheduler_budget
    RunManifest "1" --> "1" ManifestBudget : bot_budget
    Observation "1" --> "1" Kind : kind
    WorkItem "1" --> "1" WorkState : state
    WorkItem "1" --> "*" WorkAttempt : attempts
    QueryPlan "1" --> "1" PlanScope : scope
    Observation "*" --> "1" RunManifest : run_id
    WorkItem "*" --> "1" RunManifest : run_id
    QueryPlan "*" --> "1" RunManifest : policy_version
    Observation "1" --> "0..1" Observation : caused_by
```

All envelopes carry `schema_version` (currently `1`) so a
replay can deserialize an older shape through the right
`from_dict`. The dataclasses are plain (no pydantic) — the
`to_dict()` / `from_dict()` pair owns the wire format.

---

## 2. Class diagram — Decision policy + calibration + ranking

```mermaid
classDiagram
    class DecisionPolicy {
        +float threshold_accept
        +float threshold_accept_no_death
        +float gap_min
        +float low_score
        +CalibratedClassifier|None classifier
        +PlanRanker|None ranker
        +classify(ctx, candidates) Decision
    }

    class DecisionContext {
        +list~dict~ candidates
        +str|None local_death_year
        +str|None local_birth_year
        +str|None local_state
        +dict extras
    }

    class Decision {
        +str status
        +str policy_version
        +float top_score
        +float second_score
        +int candidate_count
        +float gap
        +float threshold_used
        +str reason
        +dict evidence
        +to_dict() dict
    }

    class CalibratedClassifier {
        +float intercept
        +float coef
        +float base_rate
        +threshold_for_precision(target) float
        +predict_proba(score) float
        +save(path) None
        +load(path) CalibratedClassifier
    }

    class PlanRanker {
        +PriorRegistry priors
        +rank_strategies(plans, ctx) list~QueryPlan~
        +expected_information_gain(plan, ctx) float
    }

    class PriorRegistry {
        +dict state_likelihood
        +dict texas_likelihood
        +dict strategy_usefulness
        +dict match_probability
        +str version
        +update_from_labels(labels) None
        +save(path) None
        +load(path) PriorRegistry
    }

    class PairwiseWeightLearner {
        +dict weights
        +float learning_rate
        +int max_iter
        +train(pairs) None
        +apply(scorer) Scorer
        +save(path) None
        +load(path) PairwiseWeightLearner
    }

    DecisionPolicy "1" --> "0..1" CalibratedClassifier : classifier
    DecisionPolicy "1" --> "0..1" PlanRanker : ranker
    PlanRanker "1" --> "1" PriorRegistry : priors
    DecisionPolicy "1" --> "*" Decision : produces
    DecisionPolicy ..> DecisionContext : reads
```

`Decision` carries `policy_version` so a replay recovers the
exact rule that produced the verdict. The
`CalibratedClassifier` is a single-feature logistic regression
(Platt scaling); not a deep model. The `PlanRanker` is
**advisory** — never overrides safety gates (cooldown, budget,
dedup). The `PairwiseWeightLearner` is the offline corrector;
the `CalibratedClassifier` is the online threshold-setter.

---

## 3. Sequence diagram — per-pensioner flow

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant CLI as scripts/pipeline/<br/>run_unified.py
    participant Ingest as IngestionKS
    participant Planner as RegionalPlannerKS
    participant CGR as CGRFetcherKS
    participant Scraper as FaGScraperKS
    participant Scorer as CandidateScorerKS
    participant Refiner as DeepRefinerKS
    participant Proj as ProjectionKS
    participant Store as Blackboard Store<br/>(SQLite WAL)
    participant Repo as StateRepository

    Op->>CLI: --recipe run-recipe.json
    CLI->>Store: open(run_id)
    CLI->>Ingest: ingest(pensioners, cgr)
    Ingest->>Store: append Observation(PensionerImported × N)
    Ingest-->>CLI: RunManifest

    loop per pensioner
        CLI->>Planner: claim next WorkItem(RegionalPlanner)
        Planner->>Store: read CGR observations for pensioner
        Planner->>Store: append WorkItem(FaGScraper, plan)
        Planner->>Store: append WorkItem(CandidateScorer, plan)
        Planner->>Store: append WorkItem(DeepRefiner, plan) [optional]
        Planner-->>Store: complete WorkItem SUCCEEDED

        CLI->>CGR: claim WorkItem(CGRFetcher)
        CGR->>Store: append Observation(CGRCorroboration)
        CGR-->>Store: complete SUCCEEDED

        CLI->>Scraper: claim WorkItem(FaGScraper)
        Scraper->>Store: read QueryPlan
        Scraper->>Scraper: RequestGate.acquire()<br/>BrowserSession.goto(plan)
        Scraper->>Store: append Observation(FaGCandidateFetch)
        alt response is challenge
            Scraper->>Store: append Observation(BotWallObserved)
            Scraper-->>Store: complete RETRYABLE
        else response is normal
            Scraper-->>Store: complete SUCCEEDED
        end

        CLI->>Scorer: claim WorkItem(CandidateScorer)
        Scorer->>Store: read FaGCandidateFetch
        Scorer->>Scorer: DecisionPolicy.classify()
        Scorer->>Store: append Observation(DecisionObserved)
        Scorer-->>Store: complete SUCCEEDED

        opt score < LOW_SCORE_THRESHOLD
            CLI->>Refiner: claim WorkItem(DeepRefiner)
            Refiner->>Store: append WorkItem(FaGScraper, follow-up plan)
            Refiner-->>Store: complete SUCCEEDED
        end

        CLI->>Proj: claim WorkItem(Projection)
        Proj->>Repo: StateRepository.append(row)
        Proj-->>Store: complete SUCCEEDED
    end

    CLI->>Repo: flush + fsync state.jsonl
    CLI-->>Op: report_*.md
```

Notes:

- Steps are **parallelizable**: RegionalPlanner / CGRFetcher /
  FaGScraper emit independent work items; the Scheduler runs
  them in whatever order respects the budget.
- Steps **6b** (FaGScraper detect challenge) and **9**
  (DeepRefiner follow-up) are conditional; the rest always
  fire for a given pensioner.
- The store is the single coordination point — KSs never call
  each other directly.

---

## 4. Sequence diagram — self-learning loop

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant V2 as scripts/view/v2.html<br/>(browser)
    participant Side as decisions_&lt;run&gt;.json
    participant Train as scripts/learning/<br/>train.py
    participant Lbl as LabelExtractor
    participant Pri as PriorRegistry
    participant Cls as CalibratedClassifier
    participant WL as PairwiseWeightLearner
    participant Eval as EvaluationHarness
    participant NextRun as scripts/pipeline/<br/>run_unified.py

    Op->>V2: review + pick / no-match / needs-research
    V2->>Side: "Save decisions" button
    Op->>Train: --labels sidecar.json

    Train->>Lbl: from_decisions_file(sidecar)
    Lbl->>Lbl: LabelSnapshot per pensioner
    Lbl->>Lbl: temporal split<br/>(train = pre-policy-N, eval = post)
    Lbl-->>Train: (train_labels, eval_labels)

    Train->>Pri: update_from_labels(train_labels)
    Pri->>Pri: refresh state_likelihood<br/>texas_likelihood<br/>strategy_usefulness
    Pri->>Pri: write priors_v2.json

    Train->>Cls: train(train_labels)
    Cls->>Cls: fit Platt scaling
    Cls->>Cls: write classifier_v2.json

    Train->>WL: train(train_labels)
    WL->>WL: fit pairwise logreg on<br/>(picked, rejected) deltas
    WL->>WL: write weights_v2.json

    Train->>Eval: holdout_eval(eval_labels, Cls, Pri)
    Eval-->>Train: precision/recall report

    Op->>NextRun: --recipe + --priors priors_v2.json<br/>+ --classifier classifier_v2.json

    NextRun->>Pri: load(priors_v2.json)
    NextRun->>Cls: load(classifier_v2.json)
    Note over NextRun: PlanRanker reorders strategies<br/>DecisionPolicy uses calibrated threshold
    NextRun->>NextRun: per-pensioner flow (see §3)
```

The loop is **advisory** — the PlanRanker ranks plans but
never overrides the scheduler's hard constraints (cooldown,
budget, dedup). The CalibratedClassifier only swaps in when
the operator supplies `--classifier`; the fallback is the
canonical hardcoded threshold from
`scripts/pipeline/scoring_constants.py` (L9).

The `EvaluationHarness` is the gate: if the held-out
precision drops below the prior, the new priors are kept on
disk but not auto-loaded; the operator decides whether to
promote them.

---

## 5. State diagram — WorkItem lifecycle

```mermaid
stateDiagram-v2
    [*] --> READY : WorkItem created<br/>(KS emits plan)

    READY --> LEASED : Scheduler.claim_next_work()<br/>assigns lease + TTL
    LEASED --> SUCCEEDED : KS.invoke() returns OK<br/>observations persisted
    LEASED --> RETRYABLE : KS.invoke() raised<br/>attempts++ &lt; 3<br/>not_before = now + backoff
    LEASED --> BLOCKED : KS.invoke() raised<br/>attempts++ ≥ 3<br/>operator review
    LEASED --> TERMINAL : KS.invoke() raised<br/>fatal error<br/>(e.g. malformed payload)

    RETRYABLE --> LEASED : now &gt; not_before<br/>+ lease reclaimed<br/>(TTL or stale)
    RETRYABLE --> BLOCKED : 3 failed attempts<br/>attempts ≥ 3

    READY --> TERMINAL : operator cancel<br/>(--rollback-to)

    note right of LEASED
        Lease TTL = 60s default.
        Scheduler reclaims
        stale leases each cycle
        (L12).
    end note

    note right of RETRYABLE
        Backoff: 2^attempt seconds.
        attempts=0 → 1s
        attempts=1 → 2s
        attempts=2 → 4s
        then BLOCKED.
    end note

    SUCCEEDED --> [*]
    BLOCKED --> [*]
    TERMINAL --> [*]
```

The two non-obvious transitions:

- **RETRYABLE → LEASED** (not → READY): the WorkItem retains
  its lease history (`attempts` list). Re-leasing from
  RETRYABLE rather than READY is what makes the retry
  budget enforceable — going back to READY would lose the
  attempt count.
- **READY → TERMINAL** (operator cancel): the `--rollback-to`
  flag moves WorkItems to TERMINAL when an operator rolls
  back to a checkpoint; they don't re-fire.

`BLOCKED` is intentionally terminal — the operator reviews
and either re-queues (manual edit to `READY`) or accepts the
data loss.

---

## Where to read more

- [`blackboard-architecture.md`](blackboard-architecture.md) —
  the *why* + module map for every dataclass shown here
- [`search-abstraction.md`](search-abstraction.md) §"Engine-
  agnostic common shape" — the `CommonCandidate` projection
- [`cross-layer-contract.md`](cross-layer-contract.md) —
  the `state.jsonl` shape ProjectionKS writes
- `scripts/blackboard/schema.py` — the canonical class
  definitions (any drift from these diagrams is a bug)
- `scripts/blackboard/scheduler.py` — the lease + retry
  implementation
- `scripts/learning/train.py` — the self-learning CLI