# CGR (Confederate Graves Registry) — Research Workspace

This directory holds data and tooling for cross-referencing our
OK Confederate pensioner list against the [Confederate Graves
Registry](https://cgr.scv.org/) (CGR), a SCV-maintained database
of CW veterans maintained since 2003.

## What CGR is

CGR (cgr.scv.org) is a public, free-to-use database of Confederate
veteran graves. As of July 2026 it contains:

- **204,288 veterans**
- **27,233 cemeteries**
- **50 states + 18 countries**

Each veteran record includes:

| Field | Example |
|---|---|
| First / Middle / Last | William G Looney |
| AKA / Nickname | Guy |
| Unit | 34 TX |
| Company | H |
| Rank | Pvt |
| Enlisted | 1862-03-08 |
| Birth | 1840-05-24 (MN) |
| **Death** | 1932-02-28 (**OK**) ← key burial-state field |
| Spouse | Martha Ann (Williams) |
| Source | "Okla. SCV Archives" |
| Cemetery | Rose Hill Cemetery, Chickasha, Grady, OK |

This is **gold** for our project: it gives us burial state,
cemetery, death date, rank, and enlistment date — fields our
local `unified.json` lacks.

## Site characteristics (verified July 2026)

- **Plain HTML** — no JavaScript rendering, no bot detection
- **No Cloudflare / Turnstile** — `curl` works
- **Standard HTTP GET** on `results.php` (search) and detail pages
- **No authentication required**
- **Site has rate-limit hints** (max 1000 records for state-wide
  queries) but **cemetery-browsing is unlimited**
- **Pagination** — 30 records per page; `offset=30` for page 2
- **No captcha, no rate-limiting observed** at modest request rates
- **Encoding**: ISO-8859-1 (not UTF-8)

## Endpoints

| URL | Purpose |
|---|---|
| `results.php?fname=&lname=&unit_state=&ordinal=&cem_state=&...` | Search veterans |
| `results.php?cemetery_id=X[&offset=N]` | List vets in cemetery (paginated) |
| `vetDetails.php?id=X` | Full veteran details |
| `cemDetails.php?id=X` | Cemetery details (lat/long, county) |
| `ajax_cemeteryDrop.php` (POST `state=OK`) | List cemeteries in a state |

## What's in this directory

**These files are COMMITTED to the repo.** They're valuable as
reference material and for future comparison (e.g. comparing
OK CW veterans to TX/AL/AR records as those become available).

- `ok_cemeteries.jsonl` — **bulk OK scrape**, 769 cemeteries,
  2,593 veterans. Each line is a JSON record:
  ```json
  {
    "state": "OK",
    "cemetery_id": 12754,
    "cemetery_name": "Rose Hill Cemetery",
    "county": "Grady",
    "raw_label": "Grady Co.: Rose Hill Cemetery",
    "veterans": [
      {"id": 88159, "name": "William G (Guy) Looney", "unit": "34 TX", "born": "May 24 1840"},
      ...
    ],
    "error": null,
    "timestamp": "2026-07-16T01:13:42"
  }
  ```
- `ok_vet_ids.txt` — list of 2,593 unique CGR veteran IDs in
  the OK scrape. One ID per line. Useful for cross-state
  scrapes that want to skip already-pulled vets.
- `ok_scrape.log` — the run log for the original scrape
  (timestamps, request counts, errors). Useful as provenance.

## Snapshot provenance

| Field | Value |
|---|---|
| Scraped | 2026-07-16 |
| State | OK (Oklahoma) |
| Source site | https://cgr.scv.org/ |
| Total cemeteries | 769 |
| Cemeteries with veterans | 768 |
| Total veterans captured | 2,593 |
| Largest cemetery | Rose Hill Cemetery, Carter Co. (313 vets) |
| Run command | `python scripts/cgr_ok_scraper_run.py --state OK --throttle 0.3 --no-vet-details` |
| Run duration | ~7 minutes |
| Pagination | Yes (added after smoke test found 30-record cap) |
| Vet details fetched | No (only names + units + birth dates) |

To re-run and refresh, see "How to regenerate" below.

## How to regenerate

The scraper is idempotent and resume-safe. To re-pull the data:

```bash
# Fetch the cemetery + veteran list (no vet details — fast)
python scripts/cgr_ok_scraper_run.py \
  --state OK \
  --out docs/research/cgr/ok_cemeteries.jsonl \
  --throttle 0.3 \
  --no-vet-details

# Then refresh the vet ID list:
python -c "
import json
recs = [json.loads(l) for l in open('docs/research/cgr/ok_cemeteries.jsonl', encoding='utf-8')]
ids = sorted({v['id'] for r in recs for v in r['veterans']})
open('docs/research/cgr/ok_vet_ids.txt', 'w', encoding='utf-8').write('\\n'.join(map(str, ids)))
print(f'Wrote {len(ids)} vet IDs')
"
```

If you want full vet details too (slower, ~3x bigger file):

```bash
python scripts/cgr_ok_scraper_run.py \
  --state OK \
  --out docs/research/cgr/ok_cemeteries_with_details.jsonl \
  --throttle 0.5
```

**Note:** A future run may differ from the committed snapshot if
CGR has added/removed/edited records. The committed file is the
**research snapshot** at time of scraping; the script output is
the **live state** at time of re-running. Replace the committed
file in place when refreshing.

The scripts that produce these files are in `scripts/` (committed):

- `scripts/cgr_client.py` — HTTP client with throttle + UA
- `scripts/cgr_results.py` — search-results parser
- `scripts/cgr_vet.py` — vet details parser
- `scripts/cgr_cem.py` — cemetery details parser
- `scripts/cgr_cemeteries.py` — cemetery list parser
- `scripts/cgr_matcher.py` — pensioner-to-CGR matcher
- `scripts/cgr_xref.py` + `cgr_xref_run.py` — per-pensioner
  cross-reference (search by name, fetch details)
- `scripts/cgr_ok_scraper.py` + `cgr_ok_scraper_run.py` —
  bulk cemetery-browser scraper

## How the bulk OK scrape was done (July 16, 2026)

**Why bulk-cemetery?** CGR's `?unit_state=OK` query caps at 1000
records (out of an unknown larger total). But cemetery-browsing
(`?cemetery_id=X`) is uncapped, with internal pagination.

**Workflow:**
1. POST `state=OK` to `ajax_cemeteryDrop.php` → 769 OK cemeteries
2. For each cemetery, GET `results.php?cemetery_id=X`
3. Parse "N records returned" + "(A-B of N Records)" to detect
   pagination
4. Fetch subsequent pages with `offset=30`, `offset=60`, ...
   until total reached
5. Optionally fetch `vetDetails.php?id=X` per veteran (skipped
   in the first OK run for speed)

**Command used:**
```bash
python scripts/cgr_ok_scraper_run.py \
  --state OK \
  --out C:/tmp/ok_cgr.jsonl \
  --throttle 0.3 \
  --no-vet-details
```

**Result:** 769 cemeteries × ~0.5s avg = **7 minutes total**.
2,593 unique OK CW veterans captured.

**Pagination discovery:** The first run without pagination
captured only 30 vets for "Carter Co. Rose Hill Cemetery"
when it actually has 313. The paginating version captures
all 313. Pagination was added after smoke test revealed the
cap.

## Next states to scrape

The same workflow works for any state. Just change `--state`:

| State | Cemeteries (approx) | Estimated time |
|---|---|---|
| OK | 769 | 7 min (done) |
| TX | 4,282 | ~40 min |
| AR | ~1,500 | ~15 min |
| AL | ~2,500 | ~25 min |
| VA | ~3,000 | ~30 min |
| MS | ~1,200 | ~12 min |
| GA | ~2,800 | ~28 min |

**For the full US (50 states):** estimated 8-12 hours total at
0.3s throttle. Reasonable to run overnight.

**Caveat:** Some CW soldiers migrated across state lines post-war.
A pensioner who served in TX but is buried in OK may appear in
both states' CGR records. We do NOT deduplicate across states
until we have a unified cross-state vet ID index.

## Future work

1. **Scrape all 50 states** — overnight job, ~10h, ~50K vets
2. **Fetch full vet details** for OK (currently only top-level
   data, no birth/death/spouse)
3. **Cross-reference** all OK pensioners against all OK CGR vets
   using `cgr_matcher.py`
4. **Build a unified CGR index** keyed by `(state, veteran_id)`
   for fast lookups
5. **Compare against FaG** — for each CGR vet, search FaG by
   name; record matches/misses; surface conflicts to view.html

## Privacy / courtesy notes

- CGR is maintained by volunteers at SCV. Be polite: throttle
  to ≥0.5s, identify yourself in the User-Agent.
- Our `User-Agent` is `FindAGraveHelper/0.1 (research; contact:
  jeremy@example.com)`. Update if you change the contact.
- CGR vets may have living descendants; the data is public but
  treat with respect. Do not republish wholesale without SCV
  permission.

## Source

- Site: https://cgr.scv.org/
- Operators: Sons of Confederate Veterans (SCV)
- Project lead: George Ballentine (deceased, honored on homepage)
- Data is contributed by SCV members across the US
- Access: free, no registration, no captcha (as of July 2026)