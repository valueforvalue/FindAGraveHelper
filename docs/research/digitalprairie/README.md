# Oklahoma Digital Prairie — Confederate Pension Index

## Source

[Oklahoma Digital Prairie](https://digitalprairie.ok.gov/digital/collection/pensions/search)
hosts the **Confederate Pension Records** and **Confederate Pension
Index Cards** collections. These are records from the Oklahoma Board
of Pension Commissioners, established by the 1915 Confederate Soldiers'
Pension Act.

The cards and files document Confederate veterans (and their widows)
who applied for Oklahoma pensions in the 1910s–1950s. They include:

- **Index cards** (`pensioncard` collection): 3×5 cards with name,
  application #, pension #, company, regiment, publisher, subject.
- **Application files** (`pensions` collection): the full application
  PDFs, with name, application #, pension #, archive (Record Group
  5), dates, descriptive metadata.

Oklahoma residency was required, so these records are the
**canonical OK-associated Confederate veteran list**.

## What we pulled

| Collection | Records | ID range |
|---|---|---|
| `pensions` (application files) | **7,709** | 1–8975 |
| `pensioncard` (index cards) | **11,987** | 1–12978 |
| **unified** (merged) | **7,558** | unique application# / pension# |

The `pensioncard` collection has more records than `pensions` because
not every card has a corresponding full application file in the
digitized set. The unified set is the canonical 7,558 OK-associated
Confederate pensioners we know about.

## Files in this directory

| File | What |
|---|---|
| `pensions.json` | 7,709 application file metadata records |
| `pensions.csv` | same, flat CSV |
| `pensioncard.json` | 11,987 index card metadata records |
| `pensioncard.csv` | same, flat CSV |
| `ok_pensioners.json` | **7,558 merged records — the canonical list** |
| `ok_pensioners.csv` | same, flat CSV |
| `scrape.log` | scrape run log |

Each record in `ok_pensioners.json` has:

- **Parsed name fields**: `first_name`, `middle_name`, `last_name`
- **Spouse name** (parsed): `spouse_first_name`, `spouse_middle_name`, `spouse_last_name`
- **Application and pension numbers**: `application_number`, `pension_number`
- **Unit data** (from card): `company`, `regiment`
- **Subject / coverage / creator / publisher** (descriptive)
- **Source provenance**: every API field preserved in `all_fields`
- **Backlinks**:
  - `backlink` — public pensions page
  - `pensioncard_backlink` — public card page
  - `iiif_url`, `pensioncard_iiif_url` — IIIF image URLs for visual check
  - `image_uri`, `thumbnail_uri`, `download_uri` — additional resource links
- **API URL** for re-fetching

## How the data was pulled

See `scripts/scrape_digitalprairie.py`. It:

1. Iterates ID range 1..N for each collection
2. Hits the CONTENTdm v13 single-item API at
   `https://digitalprairie.ok.gov/digital/api/singleitem/collection/{alias}/id/{id}`
3. Parses structured metadata (no OCR/PDF-text needed — fields are
   pre-extracted in the API response)
4. Saves per-collection JSON + CSV
5. Merges `pensions` + `pensioncard` on `application_number` (or
   fallback to `pension_number` or `(last, first)`) into `ok_pensioners.json`
6. Resume-safe: re-running skips already-fetched IDs

Scrape rate: ~50 records/sec with concurrency 15. Full run is
~5 minutes.

## Reproducing the scrape

```bash
python scripts/scrape_digitalprairie.py \
    --out-dir docs/research/digitalprairie \
    --min-id 1 --max-id 13000 --no-probe \
    --concurrency 15 --save-every 500
```

The script auto-probes for the max ID if `--max-id` is omitted. Add
`--no-probe` to skip that step (faster restart).

## Next step: search Find a Grave for each soldier

The unified JSON is the input to a batch FaG search. The
`FindaGraveIterativeHelper.user.js` script can be run in a loop
(matching each pensioner against FaG), or a Python harness can be
written that:

1. Iterates `ok_pensioners.json`
2. Builds a search URL for each soldier using the v5.0 strategy ladder
3. Submits the URL, parses the results page
4. If a high-confidence match (score ≥ 0.85) is found, records the
   FaG URL in a new column
5. Outputs `unified_with_fag.csv` showing which soldiers are already
   in FaG and which still need to be found

The dixiedata DB has 575 soldiers already in FaG. The unified set has
7,558. The next step is to find which ~7,000 soldiers are NOT yet in
FaG and prioritize searching for them.

## License / usage

These records are public domain (per the
`http://rightsstatements.org/vocab/NoC-US/1.0/` rights statement
embedded in each record). They come from the Oklahoma State Archives
via the Oklahoma Department of Libraries.

## Sample record

```json
{
  "id": 3,
  "collection": "pensions",
  "name_raw": "Adair, R. W.",
  "first_name": "R.",
  "middle_name": "W.",
  "last_name": "Adair",
  "application_number": "A4",
  "pension_number": "P1",
  "company": "A & C",
  "regiment": "2nd Mississippi & 3rd Mississippi Infantry & Cavalry",
  "subject": "Military pensions--Oklahoma; United States--History--Civil War, 1861-1865",
  "backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/3",
  "pensioncard_backlink": "https://digitalprairie.ok.gov/digital/singleitem/collection/pensioncard/id/3",
  "iiif_url": "https://digitalprairie.ok.gov/iiif/2/pensions:3/full/full/0/default.jpg",
  "pensioncard_iiif_url": "https://digitalprairie.ok.gov/iiif/2/pensioncard:3/full/full/0/default.jpg",
  ...
}
```

This soldier:
- Applied for OK Confederate pension in 1910s–1950s (Coverage)
- Served in Co. A & C, 2nd Mississippi Infantry and 3rd Mississippi
  Cavalry
- Application # A4, Pension # P1
- Backlinks to the original pension file and card at digitalprairie.ok.gov
- IIIF image URLs for visual verification of the source records

## IIIF image embedding — current working pattern (2026-07-17)

The view.html review UI embeds the actual pension card scan
inline using the IIIF Image API. The pattern was discovered
the hard way after `scripts/ingest/fetch_pensioncard_pages.py`
silently failed for 73% of records and the rendered view.html
showed no images.

### Working IIIF URL (verified 2026-07-17)

```
https://digitalprairie.ok.gov/iiif/2/pensioncard:{page_id}/full/300,/0/default.jpg
```

Where `page_id` is one of:

  - For **compound** pension cards (two-sided postcards, mostly):
    a `pageptr` value from the API's `objectInfo.page[]`. These
    are DIFFERENT from `pensioncard_id`. Example for pcid=11486:
    - Side 1 page_id = 11484
    - Side 2 page_id = 11485
  - For **single-page** pension cards (most records): the
    `pensioncard_id` itself. The API returns
    `objectInfo.code == -2` ("Requested item is not compound")
    and the `objectInfo.page[]` is absent.

The full URL works for BOTH cases — the difference is just
which page id you use.

### API endpoint

The only endpoint that returns JSON metadata is:

```
https://digitalprairie.ok.gov/digital/api/singleitem/collection/pensioncard/id/{pcid}
```

It returns:

```json
{
  "filename": "11487.cpd",
  "imageUri": "https://digitalprairie.ok.gov/iiif/2/pensioncard:11486/full/full/0/default.jpg",
  "iiifInfoUri": "/iiif/2/pensioncard:11486/info.json",
  "objectInfo": {
    "code": "0",
    "message": "Compound object",
    "page": [
      {"pagetitle": "Side 1", "pagefile": "11485.jp2", "pageptr": "11484"},
      {"pagetitle": "Side 2", "pagefile": "11486.jp2", "pageptr": "11485"}
    ],
    "type": "Postcard"
  }
}
```

For single-page items, `objectInfo.code == -2` and `objectInfo.page[]`
is missing entirely (NOT empty — missing). Check `imageUri` for
the fallback path.

### URL patterns that DON'T work (verified 2026-07-17)

  - `/iiif/2/pensioncard:{pcid}/full/full/0/default.jpg` with the
    PARENT `pcid` (when it has compound children) → 501 "Unsupported
    source format" (server can't render JP2 at full size for compound
    parents).
  - `/iiif/2/pensioncard:{pcid}/info.json` → 501 for compound pcids
  - `/api/image/{pcid}` → 403
  - `?size=300,` (size in query string instead of IIIF path segment) → 501

### Bug history

**Bug A (compound-vs-single):** `scripts/ingest/fetch_pensioncard_pages.py::extract_page_ids()`
only looked at `objectInfo.page[].pageptr` and returned `[]` when
that was missing. For single-page items (73% of records), this
returned an empty list, so `view.html` had no images to embed.
The fix: when `objectInfo.page[]` is empty but `imageUri` exists,
use the `pcid` as a single-page id. Implemented 2026-07-17.

**Bug B (URL prefix):** The React SPA's `imageUri` field comes
pre-prefixed with `/digital` in the JS bundle, but the API JSON
returns it as a full URL `https://digitalprairie.ok.gov/iiif/...`.
Don't double-prefix.

**Bug C (pensioncard_pages was unused in view.html):** Even when
`pensioncard_pages: [9182, 9183]` was populated, the IIIF URL
construction used a different formula. Old URL pattern tried
`/pensioncard/{page_id}` (no `:` colon) which 404'd.

### How the cache is populated

```
python scripts/ingest/fetch_pensioncard_pages.py \
    --input docs/research/digitalprairie/ok_pensioners.json \
    --output docs/research/digitalprairie/ok_pensioners.pensioncard_pages.json
```

This populates a sidecar JSON `{str(pensioner_id): [page_id, ...]}`
that's loaded by `scripts/pipeline/run_unified.py` and injected
into each results.jsonl record's `pensioncard_pages` field.
view.html reads `record.pensioncard_pages` and builds IIIF URLs
via `buildIiifThumbnailUrl(page_id)`.

At 0.25s throttle, ingesting the full 7,709 records takes ~32 min.
The sidecar is cached; re-runs are instant.

### Where the bug was rediscovered (twice)

The fix shipped in commit `1534ca2` (Fix #13, 2026-07-16) but the
ingest script's `extract_page_ids()` only handled the compound
case, leaving single-page items with no images. Discovered again
during the es-fresh-run view.html review (2026-07-17) when 0/177
cards showed images.