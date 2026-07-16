# Research — Current State, Constraints, Risks, Open Questions

> **Audience:** every agent or contributor landing on this
> repo. The synthesis of the v5.0 research phase (July 2026)
> lives in [`learnings/README.md`](learnings/README.md);
> this file is the **canonical current-state snapshot** for
> planning future work.
>
> Updated: 2026-07-16 (Run #2).

## Current state

### What works (validated by real runs)

- **OK Digital Prairie pensioner index**: 7,558 unique records
  pulled and committed at
  [`research/digitalprairie/ok_pensioners.json`](research/digitalprairie/ok_pensioners.json).
  Each record has the soldier/widow name, regiment, company,
  application number, and backlinks to the source card on
  digitalprairie.ok.gov. Re-pull via
  `python scripts/scrape_digitalprairie.py`.
- **CGR (Confederate Graves Registry) blocker index**: 2,593
  OK veterans with death data at
  [`research/cgr/ok_vets_enriched.jsonl`](research/cgr/ok_vets_enriched.jsonl).
  Provides death-year for the 97% of pensioner records that
  don't have it natively.
- **Playwright + stealth harness** (`scripts/fag_browser.py`):
  bypasses FaG's Cloudflare Turnstile with the warmup dance.
  Survives Cloudflare 1015 rate-limit detection and
  closed-target errors with the auto-recovery loop.
- **`scripts/search_fag.py` v4.x**: the iterative search
  harness. Runs at 1.5–2.5s throttle. Resume-safe via
  per-pensioner flush. Survives long runs (Run #2 hit
  ~4,400 records before the memory-leak fix).
- **`scripts/view.html` review UI**: opens the state.jsonl,
  shows ranked candidates, lets a human pick, exports
  decisions.csv. Round-tripped via
  `scripts/dd_marker_run.py` to write back to the user's
  local dixiedata DB.
- **88% rank-1 hit rate** validated against the local 577-pair
  ground-truth set (Run #0, 2026-07-15). 100% precision on
  the 29 auto-accepts.
- **v5 strategy ladder** (designed in
  [`v5-design/playbook.md`](v5-design/playbook.md)): 13
  strategies in execution order. Validated at 100% cold-start
  hit rate on the local 577 pairs; not yet shipped as the
  production harness.

### What's pending (the gap)

- **v5 strategy ladder → production**: the v5 design is
  validated but not implemented in `scripts/search_fag.py`.
  The current production code uses v4.x. Conversion effort:
  ~1-2 days.
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
  `dixiedata.db`. Effort: ~1 day.
- **Multi-state expansion** ([`learnings/future-work.md`](learnings/future-work.md)
  §8): make OK-burial scoring configurable to other states.
  Effort: ~1 day.

### What's known broken / fragile

- **Playwright memory leak** — partially fixed in Run #2 (the
  `gc.collect()` + locator cleanup); further soak testing
  needed via `scripts/soak_memory.py` to confirm the slope is
  bounded on runs > 5,000 records.
- **`view.html` lazy-load** — current implementation loads the
  full state.jsonl synchronously. A 7,758-record file freezes
  the tab for 30+s. Tracked in
  [`bug-catalog.md` §"Review UI layer"](agents/bug-catalog.md).
- **Cloudflare 1015 detection** — works but only after the
  rate-limit page has fully loaded. A faster-detection
  heuristic would cut wasted time. Tracked in
  [`bug-catalog.md` §"Playwright layer"](agents/bug-catalog.md).

## Constraints

### External / unavoidable

- **FaG rate limits**: Cloudflare Turnstile blocks
  `requests.get()`, blocks `headless=True` Playwright, and
  rate-limits sustained > 1 req/sec. The 2.5s throttle is
  the floor; the 30s backoff on challenge is the only
  recovery.
- **digitalprairie.ok.gov stability**: the OK pension records
  are public domain (state archive), but the site has no API.
  The scraper is single-shot; if the site redesigns, the
  `ok_pensioners.json` snapshot is the fallback.
- **CW record completeness**: birth year + birthplace are
  absent from the OK pension records. Census cross-reference
  would help but is out of scope (no bulk census access).

### Project-internal

- **Single-operator runs**: the harness is a CLI; no
  multi-tenant queueing. A 7,758-record run takes ~3.2h
  single-threaded.
- **Memory floor**: Playwright + Chromium consumes ~500MB
  RSS minimum. On a 4GB laptop a parallel run is impossible;
  even a single run risks OOM at the 7,000-record mark
  without the leak fix.
- **Tests require a real browser**: `tests/test_real_fag_memory.py`
  hits live FaG. CI without a browser sandbox can't run it.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| FaG redesign breaks the scraper | High | Document the params + HTML structure in `docs/research/findagrave-params/`; commit a snapshot of `ok_pensioners.json` |
| Cloudflare escalation to a stronger challenge | Medium | Stealth config in `fag_browser.py`; manual fallback to headful browser |
| OK Board of Pension records retracted | Low | Data is public domain + state archive; unlikely but possible |
| Browser-based run is not CI-friendly | Medium | Mock the browser in CI; run `test_real_fag_memory.py` only on manual trigger |
| v5 strategy ladder doesn't reach 88% on the full 7,758 set | Medium | Validation on 50-record smoke before the full run; sample of 500 before committing to 7,758 |

## Open questions

1. **Spouse cross-ref or batch-first?** Both are high-impact;
   the spouse cross-ref requires a 16h indexing run, the
   batch is a 3.2h run. Sequence: batch first (delivers value
   now), then spouse cross-ref as a follow-up.
2. **Should the v5 strategy ladder replace v4.x or coexist?**
   The v5 design is validated at 100% on the local 577 pairs;
   v4.x is what's running in production. Replacing v4.x is
   the natural next step but requires re-validation on the
   7,758 set.
3. **Auto-accept threshold** (currently 0.85): should it stay
   at 0.85 for the full 7,758 set, or should we tune it per
   outcome (lower for `BOTH_MATCH`, higher for `auto_accept`)?
4. **OK burial scoring weight**: the current 0.15 weight makes
   OK burial a tiebreaker, not a hard requirement. Is the
   project's "OK-connection" definition (residency + family
   ties, not just burial) the right operational form?

## Reproduction

The full pipeline is documented in
[`learnings/how-to-use.md`](learnings/how-to-use.md). The
short version:

```bash
# 1. Re-pull the pensioner list
python scripts/scrape_digitalprairie.py --out-dir docs/research/digitalprairie --min-id 1 --max-id 13000 --no-probe --concurrency 15 --save-every 500

# 2. Run the batch FaG search
python scripts/search_fag.py --input-url https://raw.githubusercontent.com/valueforvalue/FindAGraveHelper/master/docs/research/digitalprairie/ok_pensioners.json --state C:/tmp/full_search.jsonl

# 3. Review in browser
# Open scripts/view.html, load the JSONL, click Pick on candidates

# 4. Export decisions and mark in dixiedata
python scripts/dd_marker_run.py --decisions C:/tmp/decisions.csv
```

## Sources

The research phase drew on:

- [Find a Grave Memorial Search help](https://support.findagrave.com/s/article/Memorial-Search)
- [Searching the bio field using keywords](https://support.findagrave.com/s/article/Searching-the-bio-field-using-keywords)
- [freecivilwarrecords.org](https://freecivilwarrecords.org/)
- [NPS Civil War Soldiers & Sailors System](https://www.nps.gov/civilwar/search-soldiers.htm)
- [NARA Confederate Pensions guide](https://www.archives.gov/research/military/civil-war/confederate-pension-records)
- [Talisman phonetics library](https://yomguithereal.github.io/talisman/phonetics/)
- [FamilySearch Confederate Soldiers' Home Records](https://www.familysearch.org/en/wiki/Confederate_Soldiers_Home_Records)