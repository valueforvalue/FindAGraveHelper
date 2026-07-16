# Cross-Layer Contract

> **Audience:** every agent that lands on a slice touching
> more than one of the three runnable surfaces (Python
> harness, userscripts, browser review UI). The contract
> is the wire format that holds them together. Treat
> breaking changes here as breaking the build.

The three layers share one repository but each is deployed
independently:

| Layer | Lives in | Deployed as |
|---|---|---|
| **Python harness** | `scripts/*.py` | local CLI |
| **Userscripts** | `*.user.js` | paste into Tampermonkey |
| **Review UI** | `scripts/view.html` | open in browser |

The Python harness writes a `state.jsonl`. The review UI
reads the same `state.jsonl`. The userscripts have their
own browser-local storage and don't talk to the harness
directly (the export is manual: scrape → JSON export →
Python `process_ledger.py`).

## The wire format: `state.jsonl`

One JSON object per line, written by Python, consumed by
`view.html`. Schema (Python keys, JSON values):

```json
{
  "pensioner_id": "1234",
  "name": "William Pickney Looney",
  "first_name": "William",
  "middle_name": "Pickney",
  "last_name": "Looney",
  "unit": "Co. I, 4th TN Cav. Rgmnt., C.S.A.",
  "death_year": "1907",
  "outcome": "BOTH_MATCH",
  "ranked_candidates": [
    {
      "memorial_id": "50923719",
      "slug": "william_pickney-looney",
      "name": "William Pickney Looney",
      "score": 0.92,
      "match_strength": "high",
      "burial_location": "...",
      "death_date": "1907",
      "url": "https://www.findagrave.com/memorial/50923719/william-pickney-looney"
    }
  ],
  "auto_accept": true,
  "decided": false,
  "decided_choice": null,
  "scraped_at": "2026-07-16T14:32:10.000Z"
}
```

### Required keys

| Key | Type | Notes |
|---|---|---|
| `pensioner_id` | string | The pensioner ID from `digitalprairie/unified.json`. Stable across runs. |
| `outcome` | enum | `BOTH_MATCH`, `auto_accept`, `too_many`, `ambiguous`, `no_results`, `error`. |
| `ranked_candidates` | array | Empty for `no_results` and `error`. |
| `scraped_at` | ISO 8601 | When this record was written. |

### Optional keys

| Key | Type | Notes |
|---|---|---|
| `decided` | bool | `view.html` flips to `true` after a human picks. |
| `decided_choice` | string \| null | The memorial_id the human picked. |
| `auto_accept` | bool | High-confidence score, ≥0.85. Set by harness, reviewable in UI. |

### Constraints

- **One line per pensioner.** The harness flushes per-
  pensioner so a crash mid-run leaves a reloadable file.
- **Stable JSON key order.** Not enforced, but `view.html`
  assumes the order matches the input; alphabetical works.
- **No nested JSON arrays inside `ranked_candidates[i]`.**
  Each candidate is a flat object. Adding a nested array
  breaks `view.html`'s CSV export.

## The review-UI input: `state.jsonl`

`view.html` opens the file with `File` → `Pick`, parses one
JSON object per line, and shows:

- The pensioner metadata (name, unit, death year)
- The ranked candidates as a clickable list
- A "Pick" button per candidate that sets `decided_choice`
- A "Export decisions" button that downloads `decisions.csv`

The CSV schema:

| Column | Source |
|---|---|
| `pensioner_id` | state.jsonl |
| `decided_choice` | state.jsonl |
| `decided_choice_slug` | state.jsonl |
| `decided_choice_url` | state.jsonl |
| `score` | state.jsonl |
| `decided_at` | view.html timestamp |

If the schema changes, **update both ends in one commit**
(Python writer + `view.html` reader). The
`tests/test_view_html.py` round-trip test catches a drift.

## The review-UI output: `decisions.csv`

`scripts/dd_marker_run.py` reads this CSV and writes back to
the user's local dixiedata DB (`record_type`, `app_id`,
`details`). The CSV schema is consumed verbatim — adding or
renaming columns requires a coordinated change in
`dd_marker_run.py`.

## The userscript export: `memorials_archive.json`

`FindaGraveScraper.user.js` exports via `GM_download` (or a
data-URI fallback) when the user clicks **Export Data (N)**.
The Python `process_ledger.py` reads the file and writes:

- `memorials.csv` — flat summary, one row per memorial
- `memorials/<id>-<slug>.md` — per-record Markdown for
  static-site generators

The export schema is documented in
[`../../README.md`](../../README.md) §"Output schema". Adding
fields is allowed (Python reader is tolerant); removing or
renaming is breaking.

## Error contract

The Python harness writes `outcome: "error"` and includes an
`error` key with a short message. `view.html` shows the error
inline and offers to skip the pensioner. Errors are NOT
fatal; the harness logs and continues.

Errors that mean "the run is wedged" (Cloudflare 1015,
Playwright closed-target loop) trigger a hard reset
(browser reopen) at the next opportunity. After
`--max-consecutive-errors` (default 10) in a row, the
harness raises and exits. The outer loop in
`scripts/run_unified.py` catches and writes a final report.

## Performance contract

| Surface | Target | Measured |
|---|---|---|
| Python harness per-pensioner | <3.5s | Run #1, Run #2 averages |
| Python harness full 7,758-record run | <8h | Run #1 ETA |
| `view.html` first-paint for 7,758 records | <2s | n/a (loads file lazily) |
| Userscript scrape per page | <1s | smoke test |

Performance regressions in the Python harness are usually
Playwright memory leaks. Run
`scripts/soak_memory.py --max-slope-mb-per-10 50` after any
change to `fag_browser.py`.

## Cross-references

- [`bug-catalog.md`](bug-catalog.md) — bugs that broke the
  wire format
- [`addenda/python-playwright-userscript.md`](addenda/python-playwright-userscript.md)
  — stack-specific laws
- [`../../docs/learnings/`](../../docs/learnings/) — run logs
  that surfaced these contracts