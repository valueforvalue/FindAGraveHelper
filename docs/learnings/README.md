# Learnings — Find a Grave Helper Project

This is the **synthesized** knowledge from the v5.0 research and
development effort (July 2026). It captures the empirical
findings, the lessons learned, and the practical how-to for
anyone using or extending these tools.

## The project goal

**Find Confederate soldiers associated with Oklahoma who are not
yet in Find a Grave.** The Oklahoma Board of Pension Commissioners
(1915 act) documented every Confederate veteran (or widow) who
applied for an OK state pension — a canonical list of OK-associated
CW soldiers. We use this list as the input, and Find a Grave's
search API as the lookup target.

> **Architecture note (2026-07-19):** The default CLI path runs
> through a Local-First Blackboard (`scripts/blackboard/`):
> Scheduler dispatches Knowledge Sources (KS) that read
> Observations, write new ones, and project to `state.jsonl`.
> The legacy per-pensioner god-loop is preserved for the
> leftover-investigation and retry-errors scripts. The v2
> review UI (`scripts/view/v2.html`, Alpine.js) is the default
> view; legacy `scripts/view.html` is kept for past runs. See
> [`../agents/blackboard-architecture.md`](../agents/blackboard-architecture.md).

## Key empirical findings

### 1. The FaG slug encodes the middle name

The FaG memorial URL has a "slug" component like
`william_pickney-looney`. The slug is in the format
`first_middle-last` ~84% of the time, not `first_last`. Sending
only first + last to the FaG search misses the middle component.

This was the single biggest hit-rate improvement. The v5 strategy
ladder sends `middlename` as a primary search parameter, recovering
**24 of 41** exact-sniper failures in our validation.

### 2. The goal is OK-connection, not specifically OK burial

The pension records document that applicants had to provide proof
of at least 1 year's residency in OK. So every pensioner **lived
in OK**. But burial state could be anywhere — many veterans were
buried where they died.

The project goal is **OK-connection** (residency, family ties,
life history), not specifically OK burial. So we should not
require OK burial for high confidence in the match.

**Critical correction:** do NOT compare local `regiment state` to
candidate `burial state`. These are different things. Compare local
`pension_state` (e.g. "Oklahoma") or fall back to a default
OK-burial target. OK burial is a tiebreaker in scoring, not a
requirement.

### 3. The CW-era search needs three features

CW-era records need three signals for high-confidence matching:

1. **Name match** — last, first, middle
2. **Veteran flag** — the result card often has "V VETERAN" or
   "CSA" inline, which is a strong CW-era signal
3. **OK burial** — the killer feature for this project's goal

A candidate with all three (name match + VETERAN + buried in OK) is
**the right person** 95%+ of the time. Death-year matching is a
useful tiebreaker but not required.

### 4. FaG's bot detection blocks naive scraping

Plain `curl`/`requests` against `findagrave.com/memorial/search` get
a Cloudflare Turnstile challenge ("Just a moment..." page). This
works:

- **Playwright** with **playwright-stealth** (Python or Node)
- Browser launched with `headless=False` (Cloudflare detects
  headless mode; even with stealth, headless=True is blocked)
- **Warmup**: visit `https://www.findagrave.com/` before any search
  to establish a Cloudflare session cookie
- **30s backoff** on any CAPTCHA before retrying

What doesn't work:
- Plain `requests` / `curl` — Turnstile blocks
- Playwright with `headless=True` — Turnstile blocks
- Playwright with stealth but no warmup — first query blocks

### 5. FaG result links use relative URLs

The rendered HTML has `/memorial/...` (relative), not
`https://www.findagrave.com/memorial/...` (absolute). My first
parser used the absolute pattern and found 0 links even though
results were visible on the page. Use the relative pattern (or
both).

### 6. The result card has rich data — but the right level

Each result is a `<a>` tag. The link's `inner_text` has just the
name + veteran flag + dates. The **parent + 1** has the full card
including cemetery + city + county + state. Going up 2-3 levels
captures OTHER results' cards too, which corrupts the data.

**Use `link.parentElement.parentElement` — 2 levels up, not 4.**

### 7. State extraction has a "Co." trap

The unit string "Co. I, 4th TN Cav. Rgmnt., C.S.A." contains "Co"
which the state regex matches as Colorado (CO). Need to either:
- Skip "CO" in the abbreviation match
- Normalize "Co." → "Co" before matching
- Use full state names ("Tennessee") instead of abbreviations

The broadened approach: try abbreviations first, skip "CO"; fall
back to full state names. Tested on 8 representative unit strings,
all correct.

### 8. CW context strategy: don't use Boolean operators

`bio="Civil War" OR "CSA" OR "Confederate"` does NOT work — FaG's
bio search is full-text only, not Boolean. Use the most specific
narrowing term: `bio=Confederate States America` (4,312 hits)
beats `bio=Civil War` (495,958 hits).

## Hit-rate progression

| Approach | Hit rate at rank 1 | Notes |
|---|---|---|
| v4.0 (5 strategies, no middlename) | ~80% (estimated) | no middlename, no state, no death-year |
| v5.0 Strategy 1 only (exact sniper) | 92.9% | cold start, no metadata |
| v5.0 Strategies 1-2 (exact + middlename) | 97.1% | middlename-initial fuzzy |
| v5.0 full ladder (1-7) | 99.5% | validated against 577 local pairs |
| v5 with OK_burial as primary signal | 86% / 0 auto_accepts | OK burial required for high score |
| **v5 burial-agnostic (current)** | **88% / 29 auto_accepts (100% precision)** | OK burial is tiebreaker only |

The current harness doesn't hit 100% because:
- **Data quality** issues (local CSV missing middle names; spelling
  variants like "Robertson" vs "Roberson")
- **Search limits** (we surface top 20 candidates; some right answers
  fall outside that)
- **State extraction** doesn't catch all format variants
  ("Cherokee Indian Territory" has no state code)

The harness is a **first-pass filter** that surfaces 88% of
correct matches at rank 1 (and auto-accepts 29 of those with
100% precision). The HTML viewer is the human-review layer for
the remaining 11% (mostly close matches with no clear winner).

## File-by-file what each artifact does

```
docs/research/
├── README.md                           # research workspace index
├── local-data/                         # 575 CW veterans from dixiedata
│   ├── README.md
│   ├── local_soldiers_with_fag.csv      # input: 1,147 records with FaG URLs
│   ├── analysis_output.txt
│   ├── slug_shape_analysis.txt
│   ├── validation_results.md
│   └── validation_output.txt
├── findagrave-params/                  # verified FaG search parameters
│   └── README.md
├── cw-tactics/                         # CW genealogy playbook
│   └── README.md
├── phonetic-algorithms/                # name-matching algorithms
│   └── README.md
├── naming-conventions/                 # 1800-1860 naming culture
│   └── README.md
├── broadened-set/                      # 43,834-soldier CW dataset
│   ├── README.md
│   ├── broadened_cw_training.csv
│   ├── parse_output.txt
│   ├── match_output.txt
│   └── rosters/                         # source CSVs (gitignored)
├── digitalprairie/                     # 7,709 OK Confederate pensioners
│   ├── README.md
│   ├── ok_pensioners.json                     # canonical list (committed)
│   ├── ok_pensioners.csv
│   ├── ok_pensioners.meta.json
│   ├── ok_pensioners.pensioncard_pages.json   # sidecar
│   └── unified_sample_50.csv
└── learnings/                           # this directory
    ├── README.md                        # (this file)
    ├── how-to-use.md                    # operational guide
    ├── strategy-tuning.md                # scoring iteration log
    ├── 2026-07-16-run-1-learnings.md    # Run #1: DOM materialization crash
    ├── 2026-07-16-run-2-learnings.md    # Run #2: memory-leak investigation
    ├── 2026-07-16-j11-j15-features.md   # J11–J15 features + es-fresh-run
    ├── 2026-07-16-postrun-design.md     # post-run analysis design
    ├── 2026-07-16-checkpoint-audit.md   # checkpoint audit (historical)
    ├── algorithms-research.md           # Fellegi-Sunter + phonetic background
    ├── run-plan-2026-07-16.md           # 7709-record batch plan
    └── future-work.md                   # spouse cross-ref + other ideas

docs/v5-design/
├── README.md                            # design overview
├── playbook.md                          # master design doc
└── strategy-ladder.md                   # 13 strategies in execution order

scripts/                                 # Python harness + userscripts + view
├── pipeline/
│   ├── run_unified.py                   # CLI entrypoint (Blackboard default)
│   ├── core.py                          # legacy `run_one()` seam
│   ├── scoring_constants.py             # canonical thresholds (L9)
│   ├── checkpoint.py                    # auto-checkpoint + rollback
│   ├── state_replay.py                  # re-score old state.jsonl
│   ├── dry_run.py                       # --dry-run diff writer
│   └── dd_marker*.py / retry_errors*.py / leftover_investigation.py
├── blackboard/                          # Local-First Blackboard
│   ├── schema.py                        # versioned envelopes
│   ├── store.py                         # SQLite WAL + Jsonl fallback
│   ├── scheduler.py                     # event-guided dispatcher
│   ├── decision_policy.py               # single classify() for all paths
│   └── projector.py                     # deterministic state.jsonl writer
├── learning/                            # self-learning loop
│   ├── priors.py                        # PriorRegistry (state_likelihood, ...)
│   ├── label_extractor.py               # LabelSnapshot builder
│   ├── plan_ranker.py                   # ranks QueryPlans by expected gain
│   ├── calibrated_classifier.py         # logistic calibration + threshold
│   ├── weight_learner.py                # pairwise weight corrections
│   └── train.py                         # CLI: labels → priors + classifier
├── matching/                            # record-linkage primitives
│   ├── blocking.py / phonetic_match.py / name_evidence.py
│   ├── fellegi_sunter.py                # Fellegi-Sunter m/u model
│   ├── candidate_scorer.py / scoring.py
│   └── evaluation.py                    # held-out eval harness
├── fag/                                 # FaG-specific code (wrapped by FaGEngine)
│   ├── fag_browser.py / search.py / parser.py
│   ├── scoring.py / filters.py / strategies_fag.py
├── cgr/                                 # Confederate Graves Registry
│   ├── cgr_matcher.py / cgr_fag_dedup.py / spouse_compare.py
├── search/                              # engine-agnostic search abstractions
│   ├── engine.py / record.py / context.py / strategy.py
│   ├── ladder.py / template.py
│   ├── fag_engine.py                    # FaGEngine (1st implementation)
│   └── newspapers_engine.py             # NewspapersComEngine (2nd)
├── state/
│   ├── repository.py                    # StateRepository (L3, L5, L10)
│   ├── report_generator.py
│   └── state_check.py                   # low-level scanner
├── ingest/                              # input scrapers (run once)
│   ├── scrape_digitalprairie.py         # OK pensioner index → ok_pensioners.json
│   ├── fetch_pensioncard_pages.py       # IIIF sidecar
│   ├── cgr_ok_scraper.py / cgr_enrich.py
│   └── build_broadened_set.py
├── analysis/                            # throwaway analysis scripts
├── _archive/                            # empty archive scaffold
├── view/v2.html                         # engine-agnostic review UI (Alpine.js)
├── view.html                            # legacy v1 review UI
├── run_unified.py                       # canonical CLI shim
├── batch_config.py / soak_memory.py
└── spouse_cross_ref.py / state_normalize.py

FindaGraveScraper.user.js                # scrapes already-known FaG pages
FindaGraveIterativeHelper.user.js        # v4.0 search helper (will be replaced)
process_ledger.py                       # JSON export → CSV + Markdown
```

## Operational how-to

See [`how-to-use.md`](how-to-use.md) for the full step-by-step.
Quick summary:

```bash
# Scaffold a v2 recipe
python scripts/pipeline/run_unified.py --init full-search-2026-07-20

# Run the batch
python scripts/pipeline/run_unified.py --recipe run-recipe.json

# Review
open scripts/view/v2.html     # drag the state.jsonl onto the page
```

## Next: spouse cross-reference

**Idea:** many pension records are for **widows** who applied on
behalf of a deceased soldier. The pension card lists both the
soldier's name and the widow's name. If both are in FaG, the pair
is a very strong signal.

The OK pension index has **7,709 pensioners**; some fraction are
widows. For each widow, we can:

1. Find the widow in FaG (search by her name, optionally with
   "C.S.A. Widow" bio)
2. Find the soldier in FaG (search by his name, search by "husband
   of [widow name]" in bio)
3. Cross-link the two FaG records

This requires:
- Indexing FaG's "spouse" / "husband of" / "wife of" relationships
  (would need a one-time bulk fetch of memorial pages, ~7K × 1
  request each = 7K requests, ~3 hours at 1.5s throttle)
- Then for each widow in the pension index, lookup the spouse link
  and cross-reference

**Status:** idea only, not yet implemented. See
[`future-work.md`](future-work.md) for the design.