# Research — Current State, Constraints, Risks, Open Questions

> **Audience:** every agent or contributor landing on this
> repo. The synthesis of the v5.0 research phase (July 2026)
> lives in [`learnings/README.md`](learnings/README.md);
> this file is the **canonical current-state snapshot** for
> planning future work.
>
> Updated: 2026-07-20 (post Blackboard + self-learning refactor).
> Architecture has changed significantly since 2026-07-16;
> see [`agents/blackboard-architecture.md`](agents/blackboard-architecture.md).

## Current state

### What works (validated by real runs)

- **OK Digital Prairie pensioner index**: 7,709 unique records
  pulled and committed at
  [`research/digitalprairie/ok_pensioners.json`](research/digitalprairie/ok_pensioners.json).
  Each record has the soldier/widow name, regiment, company,
  application number, and backlinks to the source card on
  digitalprairie.ok.gov. Re-pull via
  `python scripts/ingest/scrape_digitalprairie.py`.
- **CGR (Confederate Graves Registry) blocker index**: 2,593
  OK veterans with death data at
  [`research/cgr/ok_vets_enriched.jsonl`](research/cgr/ok_vets_enriched.jsonl).
  Provides death-year for the 97% of pensioner records that
  don't have it natively.
- **Local-First Blackboard** (`scripts/blackboard/`):
  SQLite-WAL store, event-guided Scheduler, 7 Knowledge
  Sources (RegionalPlanner, FaGScraper, CGRFetcher,
  CandidateScorer, DeepRefiner, Ingestion, Projection).
  Bounded retries, deterministic ProjectionBuilder emits
  `state.jsonl` rows. Default CLI path.
- **SearchEngine abstraction** (`scripts/search/`):
  `FaGEngine` (1st implementation, 13 strategies including
  F4-follow-up) + `NewspapersComEngine` (2nd, 3 strategies).
  Engine-agnostic via `to_common_candidate()` for downstream
  consumers.
- **Browser safety + throttle** (`scripts/blackboard/` +
  `scripts/fag/`): `BrowserSession` (reverse-order teardown),
  `RequestGate` (monotonic throttle, 2.5s floor),
  `ResponseClassifier` (challenge / rate-limit detection).
  Bypasses FaG's Cloudflare Turnstile; recovers from
  closed-target errors.
- **v2 review UI** (`scripts/view/v2.html`, default since
  2026-07-19): engine-agnostic; reads `common` candidates;
  uses Alpine.js; drag-and-drop + chunked rendering + undo
  stack + keyboard shortcuts. "Save decisions" writes a
  sidecar JSON for resume; "Export picks (scraper shape)"
  for the FindaGraveScraper. Legacy `scripts/view.html`
  kept for past runs.
- **StateRepository** (`scripts/state/repository.py`):
  Protocol + JsonlStateRepository + InMemoryStateRepository.
  Owns the `state.jsonl` wire format; enforces L3 + L5 + L10.
  All call sites route through it (no bypass).
- **RunRecipe** (`scripts/pipeline/run_unified.py`):
  InputsConfig + EngineConfig + PipelineConfig + PostConfig.
  The config file IS the reproducibility artifact.
  `--init <runname>` scaffolds a v2 recipe; v1
  `config.json` auto-upgrades.
- **Reversibility flags**: `--dry-run`, `--state-replay`,
  `--rollback-to`, `--checkpoint-every`,
  `--write-checkpoint`, `--list-checkpoints`. Closes
  issue #21.
- **Self-learning loop** (`scripts/learning/`):
  PriorRegistry (versioned priors for state, Texas,
  strategy, match probability); LabelExtractor (versioned
  LabelSnapshot builder); PlanRanker (ranks QueryPlans by
  expected gain, advisory only); CalibratedClassifier
  (Platt scaling, precision-first); PairwiseWeightLearner
  (pairwise weight corrections). Trained from v2 view
  sidecars.
- **IIIF pension-card images embedded in v2.html** —
  uses the IIIF Image API to show the actual pension card
  scan inline. Working URL pattern documented in
  [`research/digitalprairie/README.md` § IIIF image embedding](research/digitalprairie/README.md#iiif-image-embedding--current-working-pattern-2026-07-17).
  Single-page items (73% of records) need a separate code
  path (use pcid as page_id) — see the README for the bug
  history that bit us twice.
- **88% rank-1 hit rate** validated against the local 577-pair
  ground-truth set (Run #0, 2026-07-15). 100% precision on
  the 29 auto-accepts.

### What's pending (the gap)

- **Spouse cross-reference** ([`learnings/future-work.md`](learnings/future-work.md)
  §1): the highest-impact future feature. Requires building
  the FaG spouse/children index (~38K requests, ~16h at 1.5s
  throttle). Effort: 3-5 days engineering + 2-4h indexing run.
- **NPS Soldiers & Sailors index integration**
  ([`learnings/future-work.md`](learnings/future-work.md) §5):
  adds officers, alternate names, non-regimental records to
  the broadened training set. Effort: ~1 week (JS-rendered
  scrape is harder than the NARA CMSR pull).
- **Bulk-export to dixiedata** ([`learnings/future-work.md`](learnings/future-work.md)
  §7): one-time tool that writes the decisions CSV back to
  `dixiedata.db`. The v2 "Export picks (scraper shape)"
  button is the canonical input.
- **Multi-state expansion** ([`learnings/future-work.md`](learnings/future-work.md)
  §8): make OK-burial scoring configurable to other states.
  Effort: ~1 day.
- **Newspapers.com end-to-end integration**: the engine works
  in tests; not yet wired into the default Blackboard run.
  Effort: ~1-2 days (UI sidecar + score calibration).
- **Self-learning production validation**: CalibratedClassifier
  + PairwiseWeightLearner ship but the training pipeline
  hasn't run against a real 7,709-batch sidecar yet.

### What's known broken / fragile

- **Playwright memory leak** — bounded by the Blackboard's
  `BrowserSession` (reverse-order teardown + per-request
  provider cooldown). Soak-test with
  `python scripts/soak_memory.py --max-slope-mb-per-10 50`
  after any change to `BrowserSession` or the FaG code.
- **Cloudflare 1015 detection** — works but only after the
  rate-limit page has fully loaded. A faster-detection
  heuristic would cut wasted time. Tracked in
  [`bug-catalog.md` §"Playwright layer"](agents/bug-catalog.md).
- **State.jsonl schema drift risk**: ProjectionBuilder emits
  v2-shape rows; legacy view.html reads only FaG-shaped
  `ranked_candidates`. New fields land together in
  [`cross-layer-contract.md`](agents/cross-layer-contract.md).

## Constraints

### External / unavoidable

- **FaG rate limits**: Cloudflare Turnstile blocks
  `requests.get()`, blocks `headless=True` Playwright, and
  rate-limits sustained > 1 req/sec. The 2.5s throttle is
  the floor; the 30s backoff on challenge is the only
  recovery (L1, L8).
- **digitalprairie.ok.gov stability**: the OK pension records
  are public domain (state archive), but the site has no API.
  The scraper is single-shot; if the site redesigns, the
  `ok_pensioners.json` snapshot is the fallback.
- **CW record completeness**: birth year + birthplace are
  absent from the OK pension records. Census cross-reference
  would help but is out of scope (no bulk census access).

### Project-internal

- **Single-operator runs**: the harness is a CLI; no
  multi-tenant queueing. A 7,709-record run takes ~5h
  single-threaded at 2.5s throttle.
- **Memory floor**: Playwright + Chromium consumes ~500MB
  RSS minimum. On a 4GB laptop a parallel run is impossible;
  even a single run risks OOM at the 7,000-record mark
  without the leak fix.
- **Tests require a real browser**: `tests/test_real_fag_memory.py`
  hits live FaG. CI without a browser sandbox can't run it;
  the rest of the suite (1,381 tests) runs without.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| FaG redesign breaks the scraper | High | Document the params + HTML structure in `docs/research/findagrave-params/`; commit a snapshot of `ok_pensioners.json` |
| Cloudflare escalation to a stronger challenge | Medium | Stealth config in `BrowserSession`; manual fallback to headful browser |
| OK Board of Pension records retracted | Low | Data is public domain + state archive; unlikely but possible |
| Browser-based run is not CI-friendly | Medium | Mock the browser in CI; run `test_real_fag_memory.py` only on manual trigger |
| Self-learning over-corrects and hurts precision | Medium | Held-out eval in `EvaluationHarness`; PlanRanker + CalibratedClassifier are advisory, never override safety gates |
| ProjectionBuilder deterministic drift after schema bump | Low | Schema versioned; replay-safe via `policy_version` field on every row |

## Open questions

1. **Spouse cross-ref or Newspapers.com integration first?**
   Spouse cross-ref is highest-impact for OK Confederate
   research; Newspapers.com broadens to non-FaG veterans.
   Sequence: spouse first (delivers value to existing
   reviewer flow), Newspapers.com as follow-up.
2. **Should the calibrated threshold replace 0.85 globally?**
   The CalibratedClassifier ships but defaults to "auto"
   only when the operator supplies `--classifier` to the
   CLI. The fallback is the canonical 0.85 hardcoded
   constant (L9). Decision pending: do we ship "auto" as
   default once we have a real 7,709-batch sidecar to
   calibrate against?
3. **How aggressive should the PlanRanker reorder be?**
   The PriorRegistry learns from past runs; an aggressive
   reorder (skip 8 of 13 strategies for low-priors pensions)
   would cut wall clock ~3x but risks missing matches.
   The scheduler currently caps the reorder at 50% of
   strategies skipped. Operator feedback needed.

## Reproduction

The full pipeline is documented in
[`learnings/how-to-use.md`](learnings/how-to-use.md). The
short version:

```bash
# 1. Re-pull the pensioner list (already committed)
python scripts/ingest/scrape_digitalprairie.py \
    --out-dir docs/research/digitalprairie \
    --min-id 1 --max-id 13000 --no-probe \
    --concurrency 15 --save-every 500

# 2. Scaffold + run the batch (Blackboard default path)
python scripts/pipeline/run_unified.py --init full-search-2026-07-20
python scripts/pipeline/run_unified.py --recipe run-recipe.json

# 3. Review in browser (v2 default; drag-and-drop)
open scripts/view/v2.html

# 4. (Optional) Re-train the self-learning loop from
# the v2 view's "Save decisions" sidecar
python scripts/learning/train.py --labels labels.jsonl
```