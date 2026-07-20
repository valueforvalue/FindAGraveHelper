# Agent Docs Index — 3-Tier Progressive Disclosure

> **Audience:** every agent that lands on a session for this
> repo. The 3-tier model protects the agent's attention
> budget. **Always load Tier-0 first.** Load Tier-1 by task
> role. Tier-2 on demand.

The budget per tier (per
[`core/docs-index-scheme.md`](https://github.com/valueforvalue/agent-stack/blob/main/core/docs-index-scheme.md)):

- **Tier-0:** ~2K tokens total. Always loaded.
- **Tier-1:** ~5K tokens per role. Task-role loaded.
- **Tier-2:** unbounded. Loaded on demand only.

Every doc in this index declares a `Token cost: ~N` line so
the agent and the maintainer can audit the budget on every PR.

---

## Tier-0 — always loaded (session start)

These cross-cut every task. Load at session start. The agent
should not start work without these in context.

| Doc | Token cost | Purpose |
|---|---|---|
| [`../../AGENTS.md`](../../AGENTS.md) | ~700 | File map, build/test, hard rules, Tier-0 wiring |
| [`../../CONTEXT.md`](../../CONTEXT.md) | ~2K | Glossary + 12 laws (L1–L12) earned by real bugs |

**Tier-0 budget:** ~2.7K tokens.

### When to load Tier-0

At session start. The two files together cover:

- The goal of the project (CONTEXT.md §"Project goal")
- The domain language (CONTEXT.md §"Language")
- The hard rules (CONTEXT.md §"Laws" + AGENTS.md §"Hard rules")
- The file map (AGENTS.md §"File map")
- The build/test commands (AGENTS.md §"Build + test")

If a session starts and Tier-0 isn't in context, **stop and
load it.** Don't skim; don't summarize; load.

---

## Tier-1 — loaded by task role

Pick the role that matches your task. Load **only** the docs
in that role. Don't load the whole table.

### Role: "Implementing a Python harness slice"

| Doc | Token cost | Purpose |
|---|---|---|
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline, vertical vs horizontal |
| [`tdd.md`](tdd.md) | ~1.5K | Red-green-refactor + contract anchor |
| [`testing-philosophy.md`](testing-philosophy.md) | ~1.5K | Test-quality bar (which tests earn their place, the saboteur test, find-bugs-once) |
| [`cross-layer-contract.md`](cross-layer-contract.md) | ~1.5K | state.jsonl wire format + view.html round-trip |
| [`bug-catalog.md` §"Python layer"](bug-catalog.md#python-layer-scriptspy-except-fag_browserpy) | ~700 | Python-specific bug patterns |
| [`addenda/python-playwright-userscript.md` §"Python"](addenda/python-playwright-userscript.md#python-scriptspy) | ~400 | Per-layer recipes |

**Tier-1 budget (Python harness role):** ~7K tokens.

### Role: "Implementing a Playwright browser slice"

| Doc | Token cost | Purpose |
|---|---|---|
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline |
| [`tdd.md`](tdd.md) | ~1.5K | Red-green-refactor + smoke harness pattern |
| [`testing-philosophy.md`](testing-philosophy.md) | ~1.5K | Test-quality bar (saboteur test, state-not-line coverage) |
| [`bug-catalog.md` §"Playwright layer"](bug-catalog.md#playwright-layer-scriptsfag_browserpy-scriptssearch_fagpy) | ~1K | Locator leaks, closed-target, Cloudflare 1015 |
| [`addenda/python-playwright-userscript.md` §"Playwright"](addenda/python-playwright-userscript.md#playwright-scriptsfag_browserpy) | ~500 | Stealth + warmup + locator hygiene |

**Tier-1 budget (Playwright role):** ~6K tokens.

### Role: "Implementing a userscript slice"

| Doc | Token cost | Purpose |
|---|---|---|
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline |
| [`bug-catalog.md` §"Userscript layer"](bug-catalog.md#userscript-layer-userjs) | ~600 | GM_setValue quota, version bump discipline |
| [`addenda/python-playwright-userscript.md` §"Userscripts"](addenda/python-playwright-userscript.md#userscripts-userjs) | ~400 | @match, no eval, GM_setValue vs localStorage |

**Tier-1 budget (userscript role):** ~2.5K tokens.

### Role: "Implementing a view.html slice"

| Doc | Token cost | Purpose |
|---|---|---|
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline |
| [`cross-layer-contract.md`](cross-layer-contract.md) | ~1.5K | Wire format this UI consumes + emits |
| [`bug-catalog.md` §"Review UI layer"](bug-catalog.md#review-ui-layer-scriptsviewhtml) | ~500 | CSV column rename + lazy-load |

**Tier-1 budget (view.html role):** ~3.5K tokens.

### Role: "Implementing the v2 review UI (Alpine.js)"

`scripts/view/v2.html` is the default view since 2026-07-19.
Engine-agnostic; reads `common` candidate shape; uses
Alpine.js for reactivity; chunked rendering + drag-and-drop
loading; undo stack; keyboard shortcuts.

| Doc | Token cost | Purpose |
|---|---|---|
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline |
| [`cross-layer-contract.md`](cross-layer-contract.md) | ~1.5K | The `common` candidate shape + badge fields |
| [`search-abstraction.md` §"Engine-agnostic common shape"](search-abstraction.md) | ~700 | `to_common_candidate()` contract |
| [`blackboard-architecture.md` §"ProjectionBuilder"](blackboard-architecture.md) | ~500 | Which fields the row carries |
| [`bug-catalog.md` §"Review UI layer"](bug-catalog.md) | ~500 | Drag-drop + sidecar persistence |

**Tier-1 budget (v2 view role):** ~4.7K tokens.

### Role: "Operating the Blackboard + scheduler"

The default CLI path. Covers Scheduler dispatch, KS
invocations, projection, and the self-learning loop.

| Doc | Token cost | Purpose |
|---|---|---|
| [`blackboard-architecture.md`](blackboard-architecture.md) | ~4K | Schema, store, Scheduler, KS, ProjectionBuilder, self-learning |
| [`diagrams.md`](diagrams.md) | ~3K | Class / sequence / state diagrams for the Blackboard + Self-learning loop |
| [`pipeline-architecture.md`](pipeline-architecture.md) | ~2.5K | Visual: where the Blackboard sits in the flow |
| [`cross-layer-contract.md`](cross-layer-contract.md) | ~1.5K | The state.jsonl wire format the ProjectionBuilder emits |
| [`search-abstraction.md`](search-abstraction.md) | ~3K | The engine layer the Blackboard wraps |
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline |
| [`bug-catalog.md` §"Python layer"](bug-catalog.md) | ~700 | Python-specific bug patterns |
| [`addenda/python-playwright-userscript.md` §"Python"](addenda/python-playwright-userscript.md) | ~400 | Per-layer recipes |

**Tier-1 budget (Blackboard role):** ~13.6K tokens.

### Role: "Tuning the self-learning loop"

| Doc | Token cost | Purpose |
|---|---|---|
| [`blackboard-architecture.md` §"Self-learning loop"](blackboard-architecture.md) | ~1K | PriorRegistry / LabelExtractor / CalibratedClassifier / WeightLearner roles |
| [`blackboard-architecture.md` §"Adding a new Knowledge Source"](blackboard-architecture.md) | ~500 | KS contract (where labels feed back in) |
| [`search-abstraction.md`](search-abstraction.md) | ~3K | The strategy shapes the PlanRanker re-orders |
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline |

**Tier-1 budget (learning-loop role):** ~6K tokens.

### Role: "Adding a new search engine or strategy"

| Doc | Token cost | Purpose |
|---|---|---|
| [`search-abstraction.md`](search-abstraction.md) | ~3K | How to add a strategy (function or template form), how to add a new engine (Protocol + 6 building blocks), worked examples |
| [`pipeline-architecture.md`](pipeline-architecture.md) | ~2.5K | Mermaid diagram showing the 3 abstraction layers + 2 engines (FaG, Newspapers.com) + pipeline composition |
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline for the new code path |
| [`tdd.md`](tdd.md) | ~1.5K | Behavior tests for the new strategy or engine |

**Tier-1 budget (new-engine role):** ~8.5K tokens.

### Role: "Designing a feature or refactor"

| Doc | Token cost | Purpose |
|---|---|---|
| [`rpci.md`](rpci.md) | ~1.5K | Research → Plan → Critique → Implement flow |
| [`complexity.md`](complexity.md) | ~2K | YAGNI vs broad-but-shallow reconciliation |
| [`pragmatic-principles.md`](pragmatic-principles.md) | ~3K | Hunt & Thomas field guide + warn+cite |
| [`feature-protocol.md`](feature-protocol.md) | ~1.5K | Slice discipline |

**Tier-1 budget (design role):** ~8K tokens.

---

## Tier-2 — on demand

Loaded when a specific question surfaces. Not pre-loaded.

| Doc | Token cost | When to load |
|---|---|---|
| [`../../docs/learnings/README.md`](../../docs/learnings/README.md) | ~1.5K | Hit-rate progression, project history |
| [`../../docs/learnings/future-work.md`](../../docs/learnings/future-work.md) | ~1K | Spouse cross-ref + other ideas |
| [`../../docs/learnings/run-plan-2026-07-16.md`](../../docs/learnings/run-plan-2026-07-16.md) | ~1K | Full-batch run plan template |
| [`../../docs/learnings/2026-07-16-run-1-learnings.md`](../../docs/learnings/2026-07-16-run-1-learnings.md) | ~1K | Run #1 DOM-crash forensics |
| [`../../docs/learnings/2026-07-16-run-2-learnings.md`](../../docs/learnings/2026-07-16-run-2-learnings.md) | ~1K | Run #2 memory-leak forensics |
| [`../../docs/learnings/strategy-tuning.md`](../../docs/learnings/strategy-tuning.md) | ~1K | Per-strategy scoring iteration log |
| [`../../docs/research/README.md`](../../docs/research/README.md) | ~1.5K | Research workspace index |
| [`../../docs/v5-design/playbook.md`](../../docs/v5-design/playbook.md) | ~2K | v5 strategy ladder master design |
| [`../../docs/v5-design/strategy-ladder.md`](../../docs/v5-design/strategy-ladder.md) | ~2K | 13-strategy execution order |
| [`../../docs/learnings/2026-07-16-j11-j15-features.md`](../../docs/learnings/2026-07-16-j11-j15-features.md) | ~3K | Spouse + DD features that fed the v2 view + Blackboard |
| [`../../docs/learnings/2026-07-16-postrun-design.md`](../../docs/learnings/2026-07-16-postrun-design.md) | ~2K | CGR dedup + leftover-investigation; superseded by Blackboard ProjectionBuilder |
| [`../../docs/learnings/algorithms-research.md`](../../docs/learnings/algorithms-research.md) | ~2K | Fellegi-Sunter + phonetic algorithm background |
| [`diagrams.md`](diagrams.md) | ~3K | Class / sequence / state diagrams for Blackboard + Self-learning |

---

## Cross-references

- [`../../AGENTS.md`](../../AGENTS.md) — Tier-0 wiring hub
- [`../../CONTEXT.md`](../../CONTEXT.md) — Tier-0 glossary + laws L1–L12
- [`blackboard-architecture.md`](blackboard-architecture.md) — Blackboard / Scheduler / KS / projection
- [`diagrams.md`](diagrams.md) — class + sequence + state diagrams (companion to blackboard-architecture.md)
- [`search-abstraction.md`](search-abstraction.md) — strategy + engine abstraction
- [`pipeline-architecture.md`](pipeline-architecture.md) — visual diagram
- [`bug-catalog.md`](bug-catalog.md) — bug patterns with citations
- [`cross-layer-contract.md`](cross-layer-contract.md) — wire formats
- [`addenda/`](addenda/) — per-stack rules

## Auditing the budget

When adding a new doc to Tier-0, the **total Tier-0 budget
must stay under 2K tokens**. The CI gate (when added) will
assert this on every PR. When the budget overflows, the new
doc goes to Tier-1 with a role entry.

When adding a new role, declare a token budget and a doc
list. The role should fit one of the existing role templates
(Python, Playwright, userscript, view.html, design) — don't
invent new roles without checking.