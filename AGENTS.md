# AGENTS.md

<!--
  Hand-curated per core/laws.md. Keep this file under ~50
  lines to start; grow only from real agent mistakes.
  Universal facts only here. Tool-specific quirks live in
  CLAUDE.md / .cursorrules / copilot-instructions.md.
  Claude Code auto-imports this file when present.
-->

## Project at a glance

**Goal:** find Confederate soldiers associated with Oklahoma who
are not yet in Find a Grave, using the OK Board of Pension
Commissioners 1915-act pensioner index as the input list and
FaG's `/memorial/search` as the lookup target. Read
[`CONTEXT.md`](CONTEXT.md) end-to-end before any schema-touching
or copy-writing work.

**Stack:** Tampermonkey userscripts (browser) + Python harness
(`scripts/*.py`, Playwright + stealth) + static-HTML review UI
(`scripts/view/v2.html`, default since 2026-07-19; legacy
`scripts/view.html` kept for past runs). Per-stack rules in
[`docs/agents/addenda/python-playwright-userscript.md`](docs/agents/addenda/python-playwright-userscript.md).

**Architecture is a Local-First Blackboard.** The CLI runs
through `scripts/pipeline/run_unified.py` → Scheduler →
Knowledge Sources → ProjectionBuilder. See
[`docs/agents/blackboard-architecture.md`](docs/agents/blackboard-architecture.md).

**Search is engine-agnostic.** Pipeline consumes `SearchEngine`
Protocol; `FaGEngine` + `NewspapersComEngine` are the two
implementations. See
[`docs/agents/search-abstraction.md`](docs/agents/search-abstraction.md).

**The runner self-learns.** After each batch, v2 view exports
pick-vs-rank deltas; `scripts/learning/train.py` retrains the
PlanRanker priors and CalibratedClassifier.

**File map:**
- `CONTEXT.md` — glossary + laws L1–L12 (Tier-0)
- `docs/agents/` — agent-facing docs (Tier-0 / Tier-1 / Tier-2)
- `docs/learnings/` — run logs that earned the laws (Tier-2)
- `scripts/` — Python harness + userscripts + view
- `scripts/search/` — Strategy / SearchEngine / SearchRecord
  abstractions + engine implementations
- `scripts/blackboard/` — schema, store, Scheduler,
  DecisionPolicy, ProjectionBuilder
- `scripts/learning/` — PriorRegistry, PlanRanker,
  CalibratedClassifier, PairwiseWeightLearner
- `scripts/pipeline/` — orchestrator + run CLI
  (`run_unified.py`)
- `scripts/matching/` — record-linkage primitives
- `scripts/fag/` — FaG-specific code (wrapped by `FaGEngine`)
- `scripts/cgr/` — Confederate Graves Registry integration
- `scripts/state/` — `state.jsonl` wire format +
  StateRepository
- `scripts/view/v2.html` — engine-agnostic review UI (Alpine.js)
- `scripts/ingest/` — input scrapers (digitalprairie, CGR,
  pensioncard pages)
- `tests/` — pytest regression net
- `docs/research/` — research workspace (Tier-2)
- `docs/v5-design/` — v5 strategy ladder design (Tier-2)

**Build + test:**
- `pytest tests/` — run all tests (~1,381 passing)
- `pytest tests/test_<name>.py` — run one file
- `python scripts/soak_memory.py` — manual Playwright leak smoke
- `python -m playwright install chromium` — first-time setup
- `python scripts/pipeline/run_unified.py --help` — runner CLI

## Hard rules

- **Never bypass the throttle.** Default 2.5s, configurable via
  `--throttle`. Bypassing causes a 30-minute Cloudflare backoff.
  See `CONTEXT.md` §L1.
- **Flush `state.jsonl` per-pensioner.** `f.flush();
  os.fsync(f.fileno())` before the next pensioner loads. See
  `CONTEXT.md` §L3.
- **Never close only the Browser in Playwright reset.** Close
  page → context → browser, then drop refs to None and
  `gc.collect()`. See `CONTEXT.md` §L2.
- **Never `requests.get()` FaG.** Always Playwright + stealth.
  See `CONTEXT.md` §L8.

## Agent conventions

This repo adopts the [agent-stack](https://github.com/valueforvalue/agent-stack)
framework. The framework's `core/` docs are ported under
[`docs/agents/`](docs/agents/) and are stack-agnostic; the
per-stack rules live in
[`docs/agents/addenda/`](docs/agents/addenda/). Per
[`docs/agents/bug-catalog.md §"Tier-0 docs have a size ceiling"`](docs/agents/bug-catalog.md),
this file stays short; for full guidance follow the links below.

- Feature protocol + slice discipline:
  [`docs/agents/feature-protocol.md`](docs/agents/feature-protocol.md)
- TDD + contract anchor:
  [`docs/agents/tdd.md`](docs/agents/tdd.md)
- Test-quality bar (which tests earn their place, saboteur
  test, find-bugs-once):
  [`docs/agents/testing-philosophy.md`](docs/agents/testing-philosophy.md)
- RPCI flow (Research, Plan, Critique, Implement):
  [`docs/agents/rpci.md`](docs/agents/rpci.md)
- Complexity management (YAGNI vs broad-but-shallow):
  [`docs/agents/complexity.md`](docs/agents/complexity.md)
- Pragmatic principles + warn+cite protocol:
  [`docs/agents/pragmatic-principles.md`](docs/agents/pragmatic-principles.md)
- Bug catalog + per-layer patterns:
  [`docs/agents/bug-catalog.md`](docs/agents/bug-catalog.md)
- Cross-layer contract (Python ⇄ view.html ⇄ userscripts):
  [`docs/agents/cross-layer-contract.md`](docs/agents/cross-layer-contract.md)
- Search abstraction (how to add strategies + engines):
  [`docs/agents/search-abstraction.md`](docs/agents/search-abstraction.md)
- Pipeline architecture (Mermaid diagram + ASCII):
  [`docs/agents/pipeline-architecture.md`](docs/agents/pipeline-architecture.md)
- 3-tier progressive disclosure index:
  [`docs/agents/INDEX.md`](docs/agents/INDEX.md)
- Domain glossary + laws: [`CONTEXT.md`](CONTEXT.md) — read
  end-to-end before any schema-touching or copy-writing work.
- [`CHANGELOG.md`](CHANGELOG.md) `[Unreleased]` block — update
  in the same commit as the change.

## Agent skills

### Issue tracker

GitHub Issues via `gh` CLI. External PRs are not a triage
surface. See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).

### Triage labels

Five canonical labels: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`. See
[`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

### Domain docs

Single-context layout: one `CONTEXT.md` at the root +
[`docs/agents/adr/`](docs/agents/adr/) for architectural
decisions. See [`docs/agents/domain.md`](docs/agents/domain.md).

<!--
  Optional @imports for tool-specific files. Uncomment as
  needed.

  @.claude/subagent-manifest.md
  @docs/agents/adr/0001-state-jsonl-format.md
-->