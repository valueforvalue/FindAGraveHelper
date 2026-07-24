# Design: Extract Post-Pass Observers from `run_unified.py`

> **Status:** Proposed
> **Date:** 2026-07-22
> **Author:** Jeremy Morris (valueforvalue)
> **Follows from:** [`docs/research/runner-audit.md`](../research/runner-audit.md)
> §"Improvements worth making" §1.

---

## Context

`scripts/pipeline/run_unified.py` has grown to 1,326 lines despite
two recent cleanup PRs (#86, #87) that already removed 483 lines of
legacy. The remaining weight lives in two distinct responsibilities
that share a single file:

1. **CLI orchestration** — argument parsing, KS registration, the
   per-pensioner loop, state.jsonl projection (the right place).
2. **Post-pass enrichment** — four blocks of code that run AFTER the
   main scheduler loop closes:
   - DixieData match (`_match_pensioner_to_dd` + `PostPassObserver`)
     — lines ~1075–1107.
   - Spouse cross-reference (`annotate_records_via_session`)
     — lines ~1110–1127.
   - Observation enrichment of state rows
     (`_enrich_state_rows_with_observations`) — lines ~1133–1139,
     implementation at ~1199–1265.
   - Pensioncard pages sidecar
     (`_annotate_pensioncard_pages`) — lines ~1142–1146,
     implementation at ~1267–1326.
   - View.html copy (`copy_view_html_if_missing`) — lines ~1151,
     implementation at ~168–276.
   - Label collection (`_collect_labels_if_enabled`) — line ~1158.

**Forces in tension:**

- `run_unified.py` is the only place a contributor learns the
  end-to-end shape of a run. Splitting it makes the orchestrator
  harder to grok on first read.
- Each post-pass is independently skippable (env-var gates), has its
  own failure mode (logged + non-fatal), and has its own
  dependencies (DD needs `DIXIEDATA_DB`, spouse needs
  `FAG_SCRAPE_SPOUSE`, etc.). They are not coupled to each other.
- Testing them in isolation currently requires booting
  `run_unified.py` — no unit-level entrypoint exists.
- The two-adapter rule from [`feature-protocol.md`](../agents/feature-protocol.md)
  applies: before splitting, confirm ≥ 2 callers. Today the only
  caller is `run_unified.py`. **However:** smoke_diff.py already
  reaches into `run_unified.run_batch_scheduler`; a future second
  caller (e.g. a `--postpass DD` debug flag, a `scripts/post_pass/dd.py`
  CLI entrypoint) is one PR away. The deletion test under
  §"Consequences" below proves the call count once the slice lands.

**Laws relevant:**

- L3/L5/L10 — per-pensioner fsync flush. Post-passes write
  observations to Blackboard or rewrite state.jsonl. Both paths
  must preserve fsync.
- L9 — single source for thresholds. Post-passes must NOT
  re-declare score thresholds.
- L11 — deterministic observation IDs. `PostPassObserver` currently
  uses `uuid.uuid4()`; L11 says deterministic IDs derived from
  payload. **See "Open question Q1" below.**

---

## Decision

Extract each post-pass into a single module under
`scripts/post_pass/`, each exposing one callable:

```python
def run(state_repo: StateRepository,
        store: BlackboardStore,
        *,
        browser: BrowserSession | None = None,
        run_id: str,
        log: logging.Logger) -> PostPassStats
```

`run_unified.py` replaces the four inline blocks with one
`for pass_fn in POST_PASSES: pass_fn(...)` loop.

### Module map

| New module | Replaces | Trigger |
|---|---|---|
| `scripts/post_pass/__init__.py` | — | `POST_PASSES = [dd, spouse, observation_enrichment, pensioncard_pages, view_copy, labels]` registry. |
| `scripts/post_pass/dd.py` | DD block in `run_unified.py` (~30 lines) | Always runs; no env-gate. |
| `scripts/post_pass/spouse.py` | Spouse block (~17 lines) | `FAG_SCRAPE_SPOUSE=1`. |
| `scripts/post_pass/observation_enrichment.py` | `_enrich_state_rows_with_observations` (~67 lines) | Always runs. |
| `scripts/post_pass/pensioncard_pages.py` | `_annotate_pensioncard_pages` (~60 lines) | Always runs. |
| `scripts/post_pass/view_copy.py` | `copy_view_html_if_missing` call site (function moves to `scripts/post_pass/view_copy.py`) | Always runs. |
| `scripts/post_pass/labels.py` | `_collect_labels_if_enabled` call site | Existing config flag. |

`scripts/pipeline/post_pass_observer.py` (the `PostPassObserver`
class) **stays where it is.** It's a Blackboard-writing utility
shared by `dd.py`, `spouse.py`, and the main loop. Moving it would
be a Tier 3 churn with no payoff.

### Shape of the public seam

```python
@dataclass(frozen=True)
class PostPassStats:
    name: str
    skipped: bool = False
    matched: int = 0
    attempted: int = 0
    errors: int = 0
    duration_s: float = 0.0
    notes: str = ""


def run(
    state_repo: StateRepository,
    store: BlackboardStore,
    *,
    browser: BrowserSession | None = None,
    run_id: str,
    config: PostPassConfig,  # thin dataclass, see Q2
    log: logging.Logger,
) -> PostPassStats:
    """Run one post-pass; never raises (logged + counted).
    """
```

Each module:

- Imports `PostPassStats` and `run` from `scripts.post_pass.types`.
- Wraps its work in `try/except`, logging warnings (matches the
  current "non-fatal" discipline).
- Returns a stats object for `run_unified.py` to log uniformly.
- Sets `skipped=True` when its env-gate or config flag is unset.

### Why a registry, not a plugin system

The `POST_PASSES` list is a static list. No discovery, no entry
points. A `pass_fn(state_repo, store, ...)` signature is enough.
Adding "the spouse pass" means appending one entry to the list and
importing one module — no metaprogramming, no decorator magic.

This deliberately rejects two over-designs:

- **Strategy pattern with `BasePostPass` abstract class.** Three of
  six passes share zero state; an ABC forces ceremony with no
  payoff. The shared shape is the `PostPassStats` return value, not
  a base class.
- **Entry-point discovery (`pkg_resources`, `importlib.metadata`).**
  No third-party plugins. The list IS the registry.

---

## Decisions (locked by user 2026-07-22)

### Q1 — observation ID determinism (L11 conflict) ✅ **(a) Derive deterministic IDs**

`PostPassObserver` will derive IDs from
`sha256(kind|pid|source|version|run_id|pass_id)[:12]`. Slice 8 in
the slice plan now blocks Slice 1; the deterministic-ID change
ships with the extraction, not as a follow-up. Grep confirms no
external caller hard-codes `obs-dd-<uuid>`.

### Q2 — `PostPassConfig` shape ✅ **(c) Per-pass config dataclasses**

Each module exposes `config_from(parent: UnifiedRunnerConfig) ->
PassConfig` (where `PassConfig` is a frozen dataclass with the
fields that pass needs). `POST_PASSES` is
`list[tuple[Callable, Callable[[UnifiedRunnerConfig], BasePassConfig]]]`.
Type-safe; no god-config; no `**kwargs`.

### Q3 — view.html copy: post-pass or main loop? ✅ **(a) Keep as post-pass**

`copy_view_html_if_missing()` moves into
`scripts/post_pass/view_copy.py`. The placeholder-embedding logic
(`EMBEDDED_DATA_PLACEHOLDER` etc.) is private to that module.

---

## Slice plan

### Slice 1 (tracer bullet — fully detailed)

**Goal:** Prove the registry shape with the smallest pass moved.

- **Files:**
  - NEW `scripts/post_pass/__init__.py` (registry + types stub).
  - NEW `scripts/post_pass/types.py` (`PostPassStats`, `BasePassConfig`).
  - NEW `scripts/post_pass/observation_enrichment.py`
    (moves `_enrich_state_rows_with_observations` verbatim,
    renames to `run`).
  - NEW `scripts/post_pass/_ids.py` (deterministic ID helper —
    `sha256(kind|pid|source|version|run_id|pass_id)[:12]` per Q1).
  - MODIFY `scripts/pipeline/post_pass_observer.py`
    (replace `uuid.uuid4()` with the helper — Q1 lands here, not in
    Slice 8).
  - MODIFY `scripts/pipeline/run_unified.py` — delete
    `_enrich_state_rows_with_observations`; replace inline call
    with `from scripts.post_pass import observation_enrichment as oe;
    oe.run(state_repo, store, ..., log)`. Same try/except, same
    log message, same return.
- **Success criterion:** running
  `python scripts/pipeline/run_unified.py --limit 5` produces a
  `state.jsonl` whose rows are enriched with CGR/DD/spouse
  observations identically to before the slice, AND post-pass
  observation IDs are deterministic across runs (the same
  `(kind, pensioner_id, source, version, run_id, pass_id)` produces
  the same ID).
- **Regression net:** NEW `tests/test_post_pass_observation_enrichment.py`
  — pins the success criterion by:
  1. Building a real `JsonlStateRepository` with 3 fixture rows.
  2. Pre-seeding the `BlackboardStore` (in-memory) with one
     CGRCorroboration, one DixieDataMatch, one SpouseMatch.
  3. Calling `observation_enrichment.run(...)`.
  4. Asserting `state_repo.iter_all()` rows now carry the three
     fields. Idempotent re-run asserted.
  5. NEW `tests/test_post_pass_observer_ids.py` — calls
     `PostPassObserver.observe_dixiedata_match(pid=42, ...)`
     twice with the same payload; asserts both calls produce
     identical `observation_id` values.
- **Tier:** Tier 3 apply-site unit.
- **Risk:** Low — pure mechanical move; no logic change. Q1 fix is
  contained to one helper function.

### Subsequent slices (stub only)

- Slice 2: Extract `pensioncard_pages.py`. Same shape.
- Slice 3: Extract `view_copy.py`. Same shape; also moves
  `EMBEDDED_*_PLACEHOLDER` constants if needed.
- Slice 4: Extract `dd.py`. Same shape; imports
  `PostPassObserver` (stays put).
- Slice 5: Extract `spouse.py`. Same shape; gated by env var.
- Slice 6: Extract `labels.py`. Same shape; gated by config.
- Slice 7: Build `POST_PASSES` registry in
  `scripts/post_pass/__init__.py`; replace the inline calls in
  `run_unified.py` with one loop. Run full smoke suite.
- Slice 8: Address Q1 — deterministic observation IDs in
  `PostPassObserver`. Independent of post-pass extraction but
  the right time to do it (after all callers are visible).
- Slice 9 (deferred, plan only): `BrowserConfig` dataclass.
- Slice 10 (deferred, plan only): `ProviderRegistry` for
  multi-provider `RequestGate`.

### Plan for Slice 9 — `BrowserConfig`

After the post-pass extraction lands, the second improvement from
the audit is unifying the 9 browser params
(`throttle`, `reset_every`, `headless`, `state_filter`, `auto_relax`,
`max_consecutive_errors`, `user_agent`, `enforce_throttle_floor`,
`reset_every`).

- **Files:** NEW `scripts/fag/browser_config.py`
  (dataclass). MODIFY `scripts/fag/browser_session.py`
  (`__init__(config: BrowserConfig)`). MODIFY
  `scripts/pipeline/run_unified.py` (build `BrowserConfig` from
  `UnifiedRunnerConfig`).
- **Success criterion:** `BrowserSession` constructor accepts a
  `BrowserConfig`; all 9 params read from it; same `enforce_throttle_floor`
  ValueError behaviour preserved.
- **Regression net:** `tests/test_browser_session_teardown.py`
  already covers lifecycle; add a `test_browser_config.py` that
  asserts each field is read.
- **Open:** Should `BrowserConfig` live in `scripts/fag/` (close to
  the consumer) or `scripts/pipeline/` (close to the producer)?
  Recommendation: `scripts/fag/browser_config.py` — deep module
  pattern keeps `BrowserSession` self-contained.

### Plan for Slice 10 — `ProviderRegistry`

After Slice 9. Pre-emptive infrastructure for any future engine
that hits a different provider.

- **Files:** NEW `scripts/network/__init__.py`. NEW
  `scripts/network/gates.py` (`ProviderRegistry.for(name) ->
  RequestGate`, `register(name, gate)`). MODIFY
  `scripts/fag/browser_session.py` (look up `findagrave.com` gate
  from registry, not construct in-place). NEW
  `scripts/network/_default_registry.py` (pre-registers FaG gate).
- **Success criterion:** FaG and any future engine share the
  registry. `RequestGate.default_fag()` still works (factory for
  backward compat); new code calls
  `ProviderRegistry.for("findagrave.com")`.
- **Regression net:** `tests/test_request_gate.py` (already exists)
  covers `default_fag`; add a `test_provider_registry.py` that
  asserts lookup is idempotent and lookup of unregistered name
  raises.
- **Open:** Sync vs async registry. Today all gates are sync
  (`time.sleep` blocking). If/when an async engine is added, the
  registry must return the right gate type per caller. For now,
  sync-only; revisit when a second async engine is added.

---

## Consequences

### Positive

- `run_unified.py` shrinks from 1,326 → ~900 lines. The remaining
  ~900 is the actual CLI + scheduler wiring, which is what a
  contributor needs to read on day one.
- Each post-pass becomes unit-testable in isolation (no
  `run_unified.py` boot required).
- The "non-fatal post-pass" discipline is encoded once
  (`scripts/post_pass/types.py`); new passes inherit it.
- The `POST_PASSES` list becomes a single audit surface: "what
  happens after the main loop?" is one grep away.

### Negative

- **Indirection tax.** Six new modules; each post-pass call is
  now `oe.run(state_repo, store, ...)` instead of an inline block.
  Cost: ~5 seconds per contributor to learn the registry. Mitigated
  by keeping the function signatures flat and the registry list
  small.
- **Two-adapter-rule risk.** With only one caller
  (`run_unified.py`), the modules are borderline premature
  extractions. **Mitigation:** Slice 7's `POST_PASSES` loop makes
  the extraction pay off immediately; if a future caller (debug
  flag, CLI) materialises, the extraction is already done.
- **L11 fix scope creep.** Slice 8 adds work that wasn't strictly
  needed for the extraction. **Mitigation:** Slice 8 is an
  independent slice; user can defer or reject.

### When to revisit

- **If a post-pass grows to > 200 lines:** split it further (e.g.
  `dd/loader.py`, `dd/matcher.py`).
- **If the registry hits 10+ passes:** migrate to a
  `BasePostPass` ABC; the polymorphism starts to pay off.
- **If `BrowserConfig` (Slice 9) and `ProviderRegistry` (Slice 10)
  have not landed within 6 months of this design:** deprioritise;
  the audit's win was "keep in-house" — these are nice-to-haves.

### Deletion test (per `feature-protocol.md` §"Module discipline")

After Slice 7 lands, deleting
`scripts/post_pass/observation_enrichment.py` would break:

1. `scripts/post_pass/__init__.py:POST_PASSES` (the registry entry).
2. `tests/test_post_pass_observation_enrichment.py`.

N = 2. **Earning its keep.** Same test passes for each of the six
new modules. None of them have N=1 after Slice 7.

### Related

- [`docs/research/runner-audit.md`](../research/runner-audit.md) §1.
- [`docs/agents/feature-protocol.md`](../agents/feature-protocol.md) — slice discipline + 3-tier commit rule.
- [`docs/agents/tdd.md`](../agents/tdd.md) — RED-first slice-internal loop.
- [`CONTEXT.md` §L11](../../CONTEXT.md) — observation ID determinism.
- [`CONTEXT.md` §L3/L5/L10](../../CONTEXT.md) — fsync discipline.
- PRs #86, #87 — the cleanup PRs that set the precedent.