# Product Requirements Document

> **Audience:** every contributor picking up a feature or
> refactor. The PRD is the convergence from
> [`RESEARCH.md`](RESEARCH.md) into shippable behavior.
>
> Updated: 2026-07-20 (post Blackboard + self-learning refactor).
> Architecture has changed significantly since 2026-07-16; the
> shipped features below now describe the Local-First Blackboard
> pipeline. See
> [`agents/blackboard-architecture.md`](agents/blackboard-architecture.md)
> for the canonical architecture reference.

## Shipped

These features are live in the repo and working as of the
last tagged release (Run #2, 2026-07-16).

### Scraping (already-known memorials)

- **F1 — Memorial page scrape via userscript** —
  `FindaGraveScraper.user.js`. User pastes into Tampermonkey,
  visits a FaG memorial, clicks "Scrape Current Page", the
  record is added to the in-script ledger.
- **F2 — JSON export of the ledger** — Export Data (N) button
  downloads `memorials_archive.json` via `GM_download` (or
  data-URI fallback). Schema documented in
  [`README.md`](../README.md) §"Output schema".
- **F3 — JSON → CSV + Markdown** — `process_ledger.py` reads
  the export and writes `memorials.csv` (flat summary) + one
  Markdown file per memorial.

### Iterative search (v4.0, will be replaced)

- **F4 — Iterative search helper** —
  `FindaGraveIterativeHelper.user.js`. 5-strategy ladder (no
  middlename, no state, no death-year). ~80% hit rate at rank
  1. Will be replaced by F8.

### Batch harness (production)

- **F5 — OK pensioner index scrape** —
  `scripts/ingest/scrape_digitalprairie.py`. Pulls the OK Board of
  Pension Commissioners 1915-act index from
  digitalprairie.ok.gov. 7,709 unique records. Output:
  `docs/research/digitalprairie/ok_pensioners.json` (committed).
- **F6 — Batch FaG search (engine-agnostic)** —
  `scripts/pipeline/run_unified.py`. Iterates the
  ok_pensioners.json, dispatches through the Blackboard
  Scheduler, runs the FaGEngine (13 strategies) or any other
  SearchEngine implementation. Writes per-pensioner record to
  `state.jsonl` via the StateRepository (L3, L10). Resume-safe.
  Throttle-aware. Auto-accept at calibrated threshold (default
  0.85) or hardcoded fallback.
- **F7 — v2 browser review UI** — `scripts/view/v2.html`
  (default since 2026-07-19). Engine-agnostic; reads `common`
  candidates; uses Alpine.js; supports FaG + Newspapers.com.
  Drag-and-drop loading, chunked rendering, undo stack,
  keyboard shortcuts, dark mode. "Save decisions" writes a
  sidecar JSON for resume; "Export picks (scraper shape)"
  exports a CSV for FindaGraveScraper. Legacy
  `scripts/view.html` kept for past runs.
- **F8 — CGR blocking** — `scripts/cgr/`. Pre-narrows
  candidates against the Confederate Graves Registry index
  (2,593 OK vets). Provides death-year for the 97% of pensioner
  records missing it natively. The CGR + FaG BOTH_MATCH badge
  is a near-perfect signal surfaced in v2.
- **F9 — DD marker** — `scripts/pipeline/dd_marker_run.py`.
  Reads legacy decisions.csv, writes (soldier_id, fag_url)
  back to the user's local dixiedata DB. The v2 export shape
  is the canonical input going forward.
- **F10 — Browser safety + memory-leak resistance** —
  `scripts/blackboard/` provider layer: `BrowserSession`
  (reverse-order teardown, context manager), `RequestGate`
  (monotonic throttle, 2.5s floor), `ResponseClassifier`
  (challenge / rate-limit detection), `process-tree RSS
  watch`. Survives runs > 5,000 records.
- **F11 — Retry-errors post-run fix** —
  `scripts/pipeline/retry_errors.py`. After a wedged run,
  re-runs only the errored pensioners with the new code.
  Backed by the Blackboard's `BLOCKED` WorkItems.
- **F12 — v5 strategy ladder** — implemented; 13 strategies
  in `scripts/search/fag_strategies.py` + `scripts/search/
  strategies.py`. Cold-start hit rate ≥ 99.5% on the local
  577 pairs.
- **F13 — NewspapersComEngine** — 2nd SearchEngine
  implementation in `scripts/search/newspapers_engine.py`;
  proves the engine abstraction. Not yet wired to the
  default run; opt-in via the RunRecipe `engine` field.
- **F14 — Local-First Blackboard** —
  `scripts/blackboard/`. SQLite-WAL store, event-guided
  Scheduler, 7 Knowledge Sources (RegionalPlanner, FaGScraper,
  CGRFetcher, CandidateScorer, DeepRefiner, Ingestion,
  Projection). Deterministic ProjectionBuilder emits the
  `state.jsonl` rows. See
  [`agents/blackboard-architecture.md`](agents/blackboard-architecture.md).
- **F15 — Self-learning loop** — `scripts/learning/`.
  PriorRegistry (versioned priors for state, Texas, strategy,
  match probability); LabelExtractor (LabelSnapshot builder);
  PlanRanker (ranks QueryPlans by expected gain); calibrated
  classifier (Platt scaling, precision-first); pairwise
  weight learner. Trained from v2 view sidecars.
- **F16 — Reversibility flags** — `scripts/pipeline/
  run_unified.py`: `--dry-run`, `--state-replay`,
  `--rollback-to`, `--checkpoint-every`,
  `--write-checkpoint`, `--list-checkpoints`. Closes
  issue #21; ADR
  [`agents/adr/0006-reversibility-flags.md`](agents/adr/0006-reversibility-flags.md).
- **F17 — RunRecipe** — full reproducibility artifact.
  `InputsConfig` + `EngineConfig` + `PipelineConfig` +
  `PostConfig`. `python scripts/pipeline/run_unified.py
  --init <runname>` scaffolds a v2 recipe. v1 config.json
  auto-upgrades.
- **F18 — StateRepository** — Protocol + JsonlStateRepository
  + InMemoryStateRepository. Owns the `state.jsonl` wire
  format (L3, L5, L10). All call sites route through it.

### Research + design

- **F19 — Broadened CW training set** —
  `scripts/ingest/build_broadened_set.py`. 43,834-soldier
  dataset from 21 regimental rosters on freecivilwarrecords.org.
  Surfaces local-data biases (TX/MO/SC cavalry
  underrepresented).
- **F20 — Fellegi-Sunter matcher** —
  `scripts/matching/fellegi_sunter.py`. Proper probabilistic
  record linkage with m/u estimation. Selected via
  `recipe.scoring.method: fellegi_sunter` instead of the
  default multi-feature scorer.
- **F21 — Spouse/children extraction prototype** —
  `scripts/cgr/spouse_compare.py`. Validates that FaG's
  Spouse + Children sections can be parsed reliably; the
  output feeds `PostPassObserver` badges.

## Candidate next-up

Picked from [`learnings/future-work.md`](learnings/future-work.md)
plus the gaps in
[`RESEARCH.md`](RESEARCH.md#whats-pending-the-gap). Order is
impact × effort.

### P0 — Run the full batch on the 7,709 pensioner list

**Why:** everything is in place. The next batch search is the
production step that delivers value to the user.

**Acceptance:**

- Full 7,709-record run completes in <8h with <2% error rate
- Hit rate at rank 1 ≥ 88% (validation threshold)
- v2 view sidecar exported with ≥ 80% of pensioners picked
- `dd_marker_run.py` writes back to dixiedata.db successfully

**Estimate:** ~1 day operator time + ~5h run + ~30min human review.

### P1 — v5 strategy ladder → production ✅ SHIPPED 2026-07-10

The v5 ladder is live in `scripts/search/fag_strategies.py`
(13 strategies: B1–B5, C1, F1a–F1d, F2, F3, F4-follow-up). 50-
record smoke tests routinely hit ≥ 95% rank-1. Cold-start hit
rate on local 577 pairs: ≥ 99.5%. No further work.

### P2 — Spouse cross-reference

**Why:** highest-impact future feature. Doubles verification
on widow records (49% of the unified set).

**Acceptance:**

- FaG spouse/children index built for the top-5 candidates
  per pensioner (~38K memorial fetches)
- For each pensioner pair (soldier + widow), cross-reference
  FaG spouse section against the pension card widow name
- New state.jsonl key `spouse_match_verified: bool`
- Hit rate boost: ≥ 6 percentage points on widow records

**Estimate:** ~3-5 days engineering + ~2-4h indexing run.

### P3 — NPS Soldiers & Sailors index integration

**Why:** broadens the training set; adds officers +
alternate names + non-regimental records.

**Acceptance:**

- NPS CWSS index pulled (JS-rendered scrape)
- Combined dataset (NPS + NARA CMSR) re-validates the v5
  ladder
- v5 strategy ladder updated if NPS reveals new patterns

**Estimate:** ~1 week (JS-rendered scrape is harder than
NARA CMSR).

### P4 — `view.html` lazy-load

**Why:** 7,758-record state.jsonl freezes the tab on load.

**Acceptance:**

- Lazy-load in chunks of 500
- "Loading... N of M" indicator
- First-paint < 2s for any file size

**Estimate:** ~1 day.

### P5 — Cemetery name match

**Why:** the local CSV has `burial_cemetery` for ~95% of
records. Direct match would be a near-perfect signal.

**Acceptance:**

- New scoring component `cemetery_match_score`
- Weight: 0.20 (additive to the existing per-feature scoring)
- Validated on the local 577 pairs: ≥ 5 percentage point hit
  rate boost

**Estimate:** ~1-2 days.

### P6 — Phonetic surname expansion

**Why:** surname variants (Rozell / Rozzell / Roussel) are
a known miss source. Generating 3-5 variants per surname
and searching each would recover these.

**Acceptance:**

- Surname variant generator (Double Metaphone + manual
  Southern-name list)
- New strategy in the v5 ladder: "phonetic surname variants"
- Validated on the broadened 43,834-set: ≥ 3 percentage
  point hit rate boost

**Estimate:** ~2-3 days.

### P7 — Multi-state expansion

**Why:** OK is one of ~15 states with Confederate pension
records. Making the state configurable opens the tool to
TX, AR, MO, etc.

**Acceptance:**

- `--target-state` CLI flag
- Pension list pulls for TX/AR/MO committed to
  `docs/research/<state>/ok_pensioners.json`
- End-to-end test on a TX sample

**Estimate:** ~1 day for the flag + ~1 day per state for
the pull.

## Feature template (use this for new candidates)

When proposing a new feature, fill this in:

```markdown
### P<n> — <feature name>

**Why:** <one sentence — the value this delivers>

**User story:** as a <user>, I want to <action> so that
<outcome>.

**Locked decisions:**
- <decision 1, with rationale>
- <decision 2, with rationale>

**Apply sites:**
- [ ] <file or surface that needs to change>
- [ ] <file or surface>

**Acceptance criteria:**
- <observable behavior 1>
- <observable behavior 2>
- <regression net (test name, smoke probe)>

**Estimate:** <effort>

**Slice plan:** <one-paragraph decomposition into commits>
```

## Out of scope

These are deliberately not in the PRD. Documenting here so
contributors don't propose them.

- **Real-time monitoring of FaG additions** — out of scope
  for a single-operator tool. The state.jsonl is a snapshot
  in time; re-running the batch is the way to pick up new
  memorials.
- **FaG account creation / memorial submission** — the tool
  finds existing memorials; it does not create new ones.
- **Multi-user / shared-state** — the harness is single-
  operator. The state.jsonl file is the only shared state.
- **Cloud deployment** — the harness runs locally on the
  operator's machine. No server-side component.
- **Real-time CAPTCHA solving** — manual intervention is the
  recovery path for escalated Cloudflare challenges. Out of
  scope for an automated tool.