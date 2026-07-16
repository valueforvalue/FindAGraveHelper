# How-To: Use These Tools

This is the practical operational guide. If you're picking up the
project for the first time, read this first.

## Quick reference: what to run for what

| Goal | Command |
|---|---|
| Re-pull the 7,558 OK pensioner list | `python scripts/scrape_digitalprairie.py ...` |
| Run the batch FaG search on all 7,558 | `python scripts/search_fag.py --input-url ...` |
| Run the batch on a small slice for testing | add `--limit 50` |
| Run on local dixiedata records (with ground-truth) | use `--input-csv` and `--ground-truth-csv` |
| Review the results in browser | open `scripts/view.html`, load the JSONL state file |
| Export human decisions | click "Export decisions" in view.html |
| Re-scrape a different set of CW rosters | `python scripts/build_broadened_set.py` |

## The full pipeline

```
┌────────────────────────────────────────────────────────────┐
│ digitalprairie.ok.gov                                       │
│ (Oklahoma Confederate Pension Cards)                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ scrape_digitalprairie.py
                            │   ~5 min, ~7,758 records
                            │
┌─────────────────────────────────────────────────────────────┐
│ docs/research/digitalprairie/unified.json                   │
│ 7,558 OK CW pensioners with regiment, company, name, app#   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ search_fag.py (browser-driven)
                            │   ~3.2 hours, throttled
                            │   writes one JSON line per pensioner
                            │
┌─────────────────────────────────────────────────────────────┐
│ state.jsonl  (e.g. C:/tmp/full_search.jsonl)                │
│ ranked_candidates per pensioner with scores                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ view.html (browser)
                            │   ~30 min of human review
                            │
┌─────────────────────────────────────────────────────────────┐
│ decisions.csv  (exported from view.html)                    │
│ human picks per pensioner                                   │
└─────────────────────────────────────────────────────────────┘
```

## Step-by-step: run the full batch

### Prerequisites

- Python 3.10+ (developed on 3.14)
- A Windows machine (or Linux with `xvfb-run`)
- A real Chromium browser (not just headless)
- A few hours of patience (1.5s throttle × 7,758 pensioners = 3.2h)

Install:
```bash
pip install playwright playwright-stealth
playwright install chromium
```

### Run

```bash
# 1. Open a Chrome window first (Playwright needs a display, not headless)
#    On Windows: just have Chrome installed.
#    On Linux: xvfb-run python ...

# 2. Run the harness
python scripts/search_fag.py \
  --input-url https://raw.githubusercontent.com/valueforvalue/FindAGraveHelper/master/docs/research/digitalprairie/unified.json \
  --state C:/tmp/full_search.jsonl

# 3. Watch the logs. On CAPTCHA, the script backs off 30s and retries.
#    On a long run, Cloudflare may eventually challenge more aggressively —
#    if so, kill the script, wait 5-10 minutes, and re-run with the
#    same --state to resume (already-done pensioners are skipped).
```

The state file is `C:/tmp/full_search.jsonl`. Each line is a JSON
record with:

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
  "ranked_candidates": [
    {
      "memorial_id": "12345678",
      "slug": "john-w-smith",
      "name": "John W Smith V VETERAN ...",
      "backlink": "https://www.findagrave.com/...",
      "iiif_url": "https://www.findagrave.com/iiif/2/...",
      "score": 0.85,
      "score_breakdown": {"last": 1.0, "first": 1.0, "middle": 1.0, "ok_burial": 0.5, "state": 0.0, "veteran": 0.4, "death": 0.4},
      "details": {"is_veteran": true, "birth_year": "1842", "death_year": "1920", "state": "OK", "cemetery": "..."}
    },
    ...
  ],
  "status": "auto_accept" | "ambiguous" | "too_many" | "no_results" | "captcha" | "error" | "skip",
  "best_score": 0.85,
  "best_candidate": {"memorial_id": "...", "slug": "...", "score": 0.85},
  "strategies_run": ["B1-exact", "B3-first-initial-fuzzy", ...],
  "decision": null
}
```

### Review in browser

1. **Open `scripts/view.html`** in any browser (Chrome, Firefox, etc.)
2. **Click "File"** → select the JSONL state file
3. You'll see the loaded counts: `Total / Decided / Auto / Ambiguous / Too many / No results / Captcha`
4. **Filter** by status (e.g. "Auto-accept" to see the easy ones, "Ambiguous" to focus on the hard ones)
5. For each pensioner:
   - Read the regiment (if any)
   - Look at the candidates, sorted by score
   - Click **"Pick"** on the right one
   - Or click **"Mark: no FaG match"** if none of them are right
6. Decisions save to **localStorage** automatically
7. **Click "Export decisions"** to download `fag-decisions-YYYY-MM-DD.csv`
8. **Click "Import decisions"** to reload a previous decision set (so you can re-load the state file without losing work)

### Tips for review

- **Auto-accept (high score)** = the harness is confident. Quick skim, click pick.
- **Ambiguous (2-10 candidates)** = the harness has a short list. The right one is usually top-3. Click the candidate's `open` link in a new tab, verify on FaG, then pick.
- **Too many (>10 candidates)** = the name is common. Use the score breakdown to filter. Look for `ok_burial: 0.5` candidates first (they're buried in OK).
- **No results** = the soldier isn't in FaG. Skip.
- **Captcha** = the harness hit Cloudflare. Re-run later, those records will be retried.

## Step-by-step: test on local dixiedata first

This is the **fastest way to validate** the harness before running
on the full 7,558. We have 576 records with known FaG URLs.

### 1. Build a ground-truth CSV

```python
import csv, re
rows = list(csv.DictReader(open('C:/tmp/fag_soldiers.csv', encoding='utf-8')))
url_re = re.compile(r'findagrave\.com/memorial/(\d+)/([^/\s"\'#]+)', re.I)
out = []
seen = set()
for r in rows:
    if not r['first_name'] or not r['last_name']: continue
    for field in ('app_id', 'details'):
        m = url_re.search(r.get(field, '') or '')
        if m:
            mid, slug = m.group(1), m.group(2)
            if (r['s_id'], mid) in seen: continue
            seen.add((r['s_id'], mid))
            out.append({
                'id': r['s_id'],
                'first_name': r['first_name'],
                'middle_name': r.get('middle_name', ''),
                'last_name': r['last_name'],
                'unit': r.get('unit', ''),
                'death_year': r.get('death_year', ''),
                'memorial_id': mid,
                'slug': slug,
            })
            break
with open('C:/tmp/ground_truth.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['id','first_name','middle_name','last_name','unit','company','application_number','birth_year','death_year','memorial_id','slug'])
    w.writeheader()
    w.writerows(out)
```

### 2. Run the harness with ground-truth

```bash
python scripts/search_fag.py \
  --input-csv C:/tmp/ground_truth.csv \
  --state C:/tmp/gt_test.jsonl \
  --ground-truth-csv C:/tmp/ground_truth.csv \
  --limit 50
```

This takes ~2-3 minutes. Each state record will have a
`ground_truth` field showing whether the expected memorial_id was
found in the candidate list and at what rank.

### 3. Read the metrics

```python
import json
recs = [json.loads(l) for l in open('C:/tmp/gt_test.jsonl', encoding='utf-8')]
hit1 = sum(1 for r in recs if r.get('ground_truth', {}).get('rank') == 1)
hit5 = sum(1 for r in recs if 0 < r.get('ground_truth', {}).get('rank', 99) <= 5)
print(f'Rank 1: {hit1}/{len(recs)}')
print(f'Top 5:  {hit5}/{len(recs)}')
```

Currently: 84% at rank 1, 86% in top 5 (on 50 records from local
dixiedata).

## Step-by-step: re-pull the digitalprairie data

The `unified.json` in the repo is already current. To re-pull
(faster than downloading the 30MB from GitHub):

```bash
python scripts/scrape_digitalprairie.py \
  --out-dir docs/research/digitalprairie \
  --min-id 1 --max-id 13000 --no-probe \
  --concurrency 15 --save-every 500
```

~5 minutes. Outputs `pensions.json`, `pensioncard.json`,
`unified.json`, `unified.csv` in the out-dir.

The pensions/ + pensioncard/ files are gitignored (reproducible).
The unified.{json,csv} files are committed (canonical list).

## What if Cloudflare starts blocking hard?

If you see many `captcha` statuses in the state file:

1. **Slow down** — set a longer throttle in `scripts/search_fag.py`
   (search for `THROTTLE_SECONDS = 1.5`, change to 3.0 or 5.0)
2. **Run at off-peak hours** — Cloudflare is more lenient late at night
3. **Use a different IP** — if your home/office IP is rate-limited,
   switch networks
4. **Wait it out** — Cloudflare usually unblocks within a few hours
5. **Re-run with the same --state** — already-done pensioners are
   skipped, so the script picks up where it left off

## Output schema reference

See the in-line docstrings at the top of each script:
- `scripts/search_fag.py` — full state record schema
- `scripts/view.html` — decision export CSV format

## FAQ

### Q: How long does the full run take?
A: 7,758 pensioners × 1.5s = 3.2 hours. Plus warmup time.

### Q: Can I run it headless on a server?
A: Not directly — Cloudflare Turnstile blocks headless Chromium even
with stealth. On Linux, use `xvfb-run` (X virtual framebuffer).
On Windows, leave a visible browser window open.

### Q: What if I close the browser mid-run?
A: The script will fail on the next request. The state file is
flushed every `save_every` records (default 500), so you can re-run
to resume.

### Q: The "V Veteran" flag isn't showing up in the result
A: This means the FaG result doesn't have a VETERAN marker. Some
CW vets aren't marked on FaG. The death-year-match feature
(partially implemented) could help here. For now, rely on the
state-OK and death-year signals.

### Q: I see lots of "too_many" status
A: That's the harness telling you the name is common. The HTML
viewer surfaces all 20 candidates. Use the score breakdown to
find the OK-buried ones. If none match, "Mark: no FaG match".

### Q: How do I add a new search strategy?
A: Edit `STRATEGIES` in `scripts/search_fag.py`. Each entry is a
function that takes (first, middle, last, birth_year) and returns
a dict of FaG params (or None to skip). The strategy name in the
list shows up in the state output. Re-run the harness to test.
