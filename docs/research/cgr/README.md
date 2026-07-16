# CGR (Confederate Graves Registry) — Research Data

This directory holds the OK CGR scrape + enrichment data, used as
the source-of-truth for matching Confederate veterans against the
Oklahoma pensioner list (`ok_pensioners.json`).

## Files

- **`ok_cemeteries.jsonl`** (committed, ~3.7MB)
  769 OK cemeteries with their 2,593 unique veterans. This is
  from the bulk scrape (2026-07-16).

- **`ok_vets_enriched.jsonl`** (committed, ~1.7MB)
  Same 2,593 veterans enriched with full vet_details (died_state,
  died_date, rank, company, etc). One record per vet (flat).
  Used as input to the unified pipeline's blocking index.

- **`ok_vet_ids.txt`**, **`ok_scrape.log`** (committed)
  Provenance + which vets we got.

- **`ok_enrich.log`** (committed)
  Log from the enrichment run (2026-07-16).

## Provenance

### `ok_cemeteries.jsonl`

| Field | Value |
|---|---|
| Scraped | 2026-07-16 |
| State | OK |
| Source | https://cgr.scv.org/ |
| Cemeteries | 769 |
| Unique vets | 2,593 |
| Command | `python scripts/cgr_ok_scraper_run.py --state OK --throttle 0.3 --no-vet-details` |
| Duration | ~7 min |

### `ok_vets_enriched.jsonl`

| Field | Value |
|---|---|
| Fetched | 2026-07-16 |
| Source | https://cgr.scv.org/vetDetails.php?id=X |
| Vets | 2,593 (all vets from ok_cemeteries.jsonl) |
| Died states | 2,560 with died_state set; 2,523 (97.3%) died in OK |
| Errors | 0 |
| Command | `python scripts/cgr_enrich_run.py --throttle 0.3` |
| Duration | ~24 min |

### Died-state distribution (enriched)

| State | Vets |
|---|---|
| OK | 2,523 (97.3%) |
| (unknown) | 33 (1.3%) |
| TX | 15 |
| AR | 7 |
| GA | 4 |
| KS, LA, TN, OH, PA | 2-2 each |
| AL, MO | 1 each |

The overwhelmingly OK burial rate confirms that the OK CGR
list IS an OK veteran registry, not just an OK cemetery list.

## How to regenerate

```bash
# Step 1: bulk scrape the OK cemeteries (one vet_details fetch per vet)
python scripts/cgr_ok_scraper_run.py --state OK --throttle 0.3 --no-vet-details
# Output: ok_cemeteries.jsonl (resumable; skip if file exists)

# Step 2: enrich with full vet_details for each vet
python scripts/cgr_enrich_run.py --throttle 0.3
# Output: ok_vets_enriched.jsonl (resumable)

# Steps are resumable: existing IDs in output files are skipped.
```

## Schema

### `ok_cemeteries.jsonl`

```json
{
  "state": "OK",
  "cemetery_id": 13211,
  "cemetery_name": "Baptist Mission Cemetery",
  "county": "Adair",
  "raw_label": "Adair Co.: Baptist Mission Cemetery",
  "veterans": [
    {"id": 96425, "name": "Lafayette Carroll (Fate) Campbell",
     "unit": "NC", "born": "Jan 21 1845"}
  ],
  "timestamp": "2026-07-16T01:13:01"
}
```

### `ok_vets_enriched.jsonl`

Same as above but flattened (one row per vet) and enriched with
vet_details fields:

- `died` (full date string, e.g. "1932-02-28")
- `died_state` (e.g. "OK", "AR", etc.)
- `birth_state` (e.g. "NC")
- `rank` (e.g. "Pvt")
- `unit` (full unit string, e.g. "1 OK Infantry")
- `spouse`, `mother_maiden`, `notes`, `source`
