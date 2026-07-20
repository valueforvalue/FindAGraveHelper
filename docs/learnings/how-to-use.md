# How-To: Use These Tools

This is the practical operational guide. If you're picking up
the project for the first time, read this first.

> **Architecture note (2026-07-19):** The default path runs
> through a Local-First Blackboard (`scripts/blackboard/`).
> The CLI is `scripts/pipeline/run_unified.py`. The legacy
> god-loop is preserved as `scripts/leftover_investigation.py`
> and `scripts/retry_errors.py`. See
> [`../agents/blackboard-architecture.md`](../agents/blackboard-architecture.md).

## Quick reference: what to run for what

| Goal | Command |
|---|---|
| Re-pull the 7,709 OK pensioner list | `python scripts/ingest/scrape_digitalprairie.py ...` |
| Run the batch FaG search on all 7,709 | `python scripts/pipeline/run_unified.py --recipe run-recipe.json` |
| Scaffold a default recipe | `python scripts/pipeline/run_unified.py --init <runname>` |
| Run the batch on a small slice for testing | add `--limit 50` |
| Dry-run (no FaG network) against existing state.jsonl | `python scripts/pipeline/run_unified.py --dry-run --recipe ...` |
| Re-score an old state.jsonl against current weights | `python scripts/pipeline/run_unified.py --state-replay old.jsonl --recipe ...` |
| Rollback to a named checkpoint | `python scripts/pipeline/run_unified.py --rollback-to latest` |
| Review the results in browser (default) | open `scripts/view/v2.html`, drag the JSONL onto the page |
| Review with the legacy v1 layout | open `scripts/view.html` |
| Save / resume decisions (v2) | "Save decisions" button writes sidecar JSON |
| Export picks for FindaGraveScraper (v2) | "Export picks (scraper shape)" button |
| Re-train the self-learning loop | `python scripts/learning/train.py --labels labels.jsonl` |
| Re-scrape a different set of CW rosters | `python scripts/ingest/build_broadened_set.py` |

## The full pipeline

```
┌────────────────────────────────────────────────────────────┐
│ digitalprairie.ok.gov                                       │
│ (Oklahoma Confederate Pension Cards)                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ scripts/ingest/scrape_digitalprairie.py
                            │   ~5 min, ~7,709 records
                            │
┌─────────────────────────────────────────────────────────────┐
│ docs/research/digitalprairie/ok_pensioners.json                   │
│ 7,709 OK CW pensioners with regiment, company, name, app#   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ scripts/pipeline/run_unified.py
                            │   ~5 hours, throttled 2.5s
                            │   Blackboard Scheduler dispatches KSs
                            │   ProjectionBuilder writes state.jsonl
                            │
┌─────────────────────────────────────────────────────────────┐
│ state.jsonl  (e.g. C:/tmp/full_search/state.jsonl)          │
│ `common` engine-agnostic candidates + badges + decision     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ scripts/view/v2.html (browser)
                            │   engine-agnostic, Alpine.js
                            │   ~30 min of human review
                            │
┌─────────────────────────────────────────────────────────────┐
│ decisions_<run>.json   (sidecar; auto-loads on resume)      │
│ picks.csv  (scraper shape for FindaGraveScraper.user.js)    │
└─────────────────────────────────────────────────────────────┘
```

## Step-by-step: run the full batch

### Prerequisites

- Python 3.10+ (developed on 3.14)
- A Windows machine (or Linux with `xvfb-run`)
- A real Chromium browser (not just headless)
- A few hours of patience (2.5s throttle × 7,709 pensioners ≈ 5h)

Install:
```bash
pip install playwright playwright-stealth
playwright install chromium
```

### Run

```bash
# 1. Scaffold a v2 recipe (writes run-recipe.json)
python scripts/pipeline/run_unified.py --init full-search-2026-07-20
# Edit the recipe to point at your input + output paths.

# 2. Run the harness. The Blackboard Scheduler dispatches KSs
#    (RegionalPlanner → FaGScraper → CandidateScorer → Projection).
#    State persists per-pensioner (L3, L10); resume-safe.
python scripts/pipeline/run_unified.py --recipe run-recipe.json

# 3. Watch the logs. On CAPTCHA, the BrowserSession backs off 30s
#    and retries. On a long run, Cloudflare may eventually challenge
#    more aggressively — if so, kill the script, wait 5-10 minutes,
#    and re-run with the same recipe to resume (already-done
#    pensioners are skipped).
```

The state file is `C:/tmp/full_search/state.jsonl`. Each line is
a JSON record with:

```json
{
  "pensioner_id": 1234,
  "pensioner_app_number": "A5678",
  "pensioner_name": "John Smith",
  "pensioner_first": "John",
  "pensioner_middle": "W.",
  "pensioner_last": "Smith",
  "pensioner_birth_year": "1842",
  "pensioner_death_year": "1920",
  "regiment": "5th Texas Infantry",
  "company": "A & C",
  "pensioncard_backlink": "https://digitalprairie.ok.gov/...",
  "engine": "findagrave",
  "common": [
    {
      "id": "12345678",
      "url": "https://www.findagrave.com/memorial/12345678/john-w-smith",
      "name": "John W Smith V VETERAN ...",
      "score": 0.85,
      "evidence": {
        "match_strength": "high",
        "burial_location": "...",
        "death_date": "1920"
      },
      "engine": "findagrave",
      "media": "https://www.findagrave.com/iiif/2/..."
    }
  ],
  "ranked_candidates": [...],
  "outcome": "auto_accept",
  "badges": ["cgr_match"],
  "decision": {"status": "auto_accept", "top_score": 0.85, "gap": 0.18, "threshold_used": 0.85, "policy_version": "1"},
  "policy_version": "1",
  "scraped_at": "2026-07-20T14:32:10.000Z"
}
```

### Review in browser (v2, default)

1. **Open `scripts/view/v2.html`** in any browser (Chrome, Firefox, etc.)
2. **Drag the JSONL file** onto the page, or use the "Open" button
3. You'll see the loaded counts: `Total / Decided / Auto / Ambiguous / Too many / No results / Needs research`
4. **Filter** by badge chip (e.g. "CGR match", "Needs research") or by outcome
5. For each pensioner:
   - Read the regiment (if any)
   - Look at the candidates, sorted by score
   - Click **"Pick"** on the right one, or **"No match"** / **"Needs research"**
6. Decisions auto-save to a sidecar JSON in browser storage
7. **Click "Save decisions"** to download `decisions_<run>.json` (re-loadable on resume)
8. **Click "Export picks (scraper shape)"** to download the CSV for `FindaGraveScraper.user.js`
9. Keyboard: `j`/`k` next/prev, `p` pick top, `n` no-match. `Ctrl+Z` undo.

### Review in browser (legacy v1)

If your run produced a v1-shaped state.jsonl (FaG-only candidates,
no `common` array), open `scripts/view.html` instead.

## Step-by-step: re-pull the digitalprairie data

The `ok_pensioners.json` in the repo is already current. To re-pull
(faster than downloading the 30MB from GitHub):

```bash
python scripts/ingest/scrape_digitalprairie.py \
  --out-dir docs/research/digitalprairie \
  --min-id 1 --max-id 13000 --no-probe \
  --concurrency 15 --save-every 500
```

~5 minutes. Outputs `pensions.json`, `pensioncard.json`,
`ok_pensioners.json`, `ok_pensioners.csv` in the out-dir.

The pensions/ + pensioncard/ files are gitignored (reproducible).
The unified.{json,csv} files are committed (canonical list).

## What if Cloudflare starts blocking hard?

If you see many `captcha` outcomes in the state file:

1. **Slow down** — set a longer throttle in the recipe
   (`engine.throttle_seconds: 5.0` instead of 2.5).
2. **Run at off-peak hours** — Cloudflare is more lenient late at night.
3. **Use a different IP** — if your home/office IP is rate-limited,
   switch networks.
4. **Wait it out** — Cloudflare usually unblocks within a few hours.
5. **Re-run with the same recipe** — already-done pensioners are
   skipped, so the script picks up where it left off.

## FAQ

### Q: How long does the full run take?
A: 7,709 pensioners × 2.5s ≈ 5 hours. Plus warmup time.

### Q: Can I run it headless on a server?
A: Not directly — Cloudflare Turnstile blocks headless Chromium even
with stealth. On Linux, use `xvfb-run` (X virtual framebuffer).
On Windows, leave a visible browser window open.

### Q: What if I close the browser mid-run?
A: The Blackboard's `BrowserSession` survives a per-page close
(L2 enforces page → context → browser teardown + gc). A full
process kill is recoverable: re-run with the same recipe; the
SQLite store + state.jsonl have all done WorkItems marked
`SUCCEEDED`.

### Q: The "V Veteran" flag isn't showing up in the result
A: This means the FaG result doesn't have a VETERAN marker. Some
CW vets aren't marked on FaG. The death-year-match feature
(partially implemented) could help here. For now, rely on the
state-OK and death-year signals.

### Q: I see lots of "too_many" outcome
A: That's the harness telling you the name is common. The HTML
viewer surfaces all candidates. Use the score breakdown to find
the OK-buried ones. If none match, "Mark: no FaG match".

### Q: How do I add a new search strategy?
A: Write a `FunctionStrategy` or `TemplateStrategy` and append it
to the engine's ladder in `scripts/search/strategies.py` (generic)
or `scripts/search/fag_strategies.py` (FaG-specific, like F2/F3/F4).
See [`../agents/search-abstraction.md`](../agents/search-abstraction.md)
for the contract.
</content>
</invoke>