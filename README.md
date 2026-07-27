# FindAGraveHelper

[![tests](https://github.com/valueforvalue/FindAGraveHelper/actions/workflows/test.yml/badge.svg)](https://github.com/valueforvalue/FindAGraveHelper/actions/workflows/test.yml)

Automated pipeline for matching Oklahoma Confederate pensioners to
[Find a Grave](https://www.findagrave.com) memorials. 1,527 tests, blackboard
architecture, engine-agnostic search abstraction.

## Project goal

Find **Confederate soldiers associated with Oklahoma** who are not yet in
Find a Grave. The 1915 Oklahoma Confederate Pension Act created a canonical
list of ~7,758 OK-associated CW soldiers and widows. We use this list as
input and FaG's `/memorial/search` as the lookup target.

## Quickstart

```bash
# Run a batch (Playwright + stealth; install chromium first)
python -m playwright install chromium
PYTHONPATH=. python scripts/pipeline/run_unified.py \
    --input docs/research/digitalprairie/ok_pensioners.json \
    --cgr docs/research/cgr/ok_vets_enriched.jsonl \
    --out output/my-run \
    --limit 25 \
    --throttle 2.5

# Open the review UI
open output/my-run/view.html
```

Or use a config file:

```bash
python scripts/pipeline/run_unified.py init-batch my-run
python scripts/pipeline/run_unified.py --config output/my-run/config.json --limit 25
```

## Pipeline modes

| Flag | Effect |
|---|---|
| `--mode conservative` | Max 2 refinement strategies (default) |
| `--mode standard` | Max 4 refinement strategies |
| `--mode aggressive` | Max 8 refinement strategies |
| `--mode none` | No refinement — fastest, saves FaG requests |
| `--relax-throttle-floor` | Allow throttle < 2.5s (slice runs, A/B tests) |

## Scoring features

The pipeline scores each candidate (FaG memorial) against the pensioner
record using weighted features:

| Feature | Weight | Signal |
|---|---|---|
| Last name match | 0.22 | Double Metaphone + Jaro-Winkler |
| First name match | 0.17 | Normalized string comparison |
| Middle name match | 0.11 | Initial or full name |
| OK burial | 0.15 | Candidate buried in Oklahoma |
| Death year era | 0.22 | CW veteran era (1861-1955) or exact match |
| Veteran flag | 0.18 | CSA/military markers in memorial text |
| Widow pension | 0.18 | Widow's husband in right era |
| State match | 0.05 | Regiment state = burial state |
| Maiden name | 0.12 | Widow's maiden name in memorial |

**Post-scoring boosts:**
- Spouse verification (+0.15): scrapes memorial detail page, confirms
  spouse name match for widow candidates
- Memorial CSA signals (+0.08): scrapes memorial page for Confederate
  military markers on borderline candidates
- Regiment-era bonus (+0.05): candidate death year in CW veteran window
- Cemetery type bonus (+0.03): Confederate/National/Veterans cemeteries

Auto-accept threshold: 0.85 (with 0.10 gap to #2 candidate).

## Architecture

Local-first blackboard pattern with SQLite-WAL store. Knowledge Sources
(KS) read observations, produce new ones, and claim work items. The
Scheduler dispatches based on eligible work rather than a fixed pipeline
order. See [`docs/agents/blackboard-architecture.md`](docs/agents/blackboard-architecture.md).

```
RegionalPlannerKS → FaGScraperKS → CandidateScorerKS
    → DeepRefinerKS (optional) → CalibratedDecisionKS
    → Spouse verification → Memorial signal check
    → ProjectionBuilder → state.jsonl → v2.html
```

## Review UI (v2)

`scripts/view/v2.html` — browser-only review UI (Alpine.js). Loads
`results.jsonl`, shows scored candidates per pensioner with evidence
breakdown bars, picks vs rank export, strategy badges, and spouse
verification badges. Feedback button posts to project maintainer.

## Pack runs for sharing

```bash
# Bundle H-surname runs + G-surname run into two review-ready .zips
PYTHONPATH=. python scripts/distribute.py \
    --group "H-surnames=ha,ho,he,hu,hi,h-rest" \
    --group "G-surnames=g-all"
# -> dist/H-surnames.zip  dist/G-surnames.zip
```

Each zip contains `<runname>/view.html` + `<runname>/results.jsonl`.
Source folders are never modified. Unzip anywhere and double-click
view.html to start reviewing — the v2 UI auto-fetches its sibling
results.jsonl. See `scripts/distribute.py --help` for
`--groups-file`, `--skip-view-html`, `--skip-results`, `--dry-run`.

## Run the tests

```bash
pytest tests/                              # full suite (1,527 tests)
pytest tests/test_<name>.py                # one file
pytest -m "not integration"                # skip real-browser tests
```

## Adding a search engine

Engine-agnostic: `FaGEngine` and `NewspapersComEngine` are the two
implementations of the `SearchEngine` Protocol. See
[`docs/agents/search-abstraction.md`](docs/agents/search-abstraction.md).

## Adding a strategy

A strategy is a function `(SearchContext) -> dict | None` that returns
FaG URL params. Register with `FunctionStrategy("name", fn)`. Template
DSL also available. See [`scripts/search/strategies.py`](scripts/search/strategies.py).

## Userscripts (legacy)

| Script | Purpose |
|---|---|
| [`FindaGraveScraper.user.js`](./FindaGraveScraper.user.js) | Scrapes individual FaG memorial pages to JSON |
| [`FindaGraveIterativeHelper.user.js`](./FindaGraveIterativeHelper.user.js) | Interactive search helper (v4.0) |

Install via Tampermonkey / Greasemonkey / Violentmonkey.

## Key docs

- [`CONTEXT.md`](CONTEXT.md) — domain glossary + laws
- [`AGENTS.md`](AGENTS.md) — agent conventions + file map
- [`docs/agents/`](docs/agents/) — architecture, testing, search abstraction
- [`docs/v5-design/`](docs/v5-design/) — strategy ladder design
- [`docs/research/digitalprairie/`](docs/research/digitalprairie/) — pensioner data

## License

[MIT](./LICENSE)
