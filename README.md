# FindAGraveHelper

A pair of Tampermonkey/Greasemonkey userscripts for working with
[Find a Grave](https://www.findagrave.com) memorials, plus a
research workspace documenting Civil War genealogy patterns that
inform future development.

## What's in this repo

### Userscripts

| Script | Purpose |
|---|---|
| [`FindaGraveScraper.user.js`](./FindaGraveScraper.user.js) | **Scraper.** Loads Find a Grave memorial pages and exports the data as JSON. For already-found memorials. |
| [`FindaGraveIterativeHelper.user.js`](./FindaGraveIterativeHelper.user.js) | **Search helper.** Iteratively searches Find a Grave for a person who isn't yet in FaG. v4.0, will be replaced by v5.0. |

Both scripts work with Tampermonkey / Greasemonkey / Violentmonkey.

### Research workspace

[`docs/research/`](./docs/research/) contains the full v5.0 design
research — FaG URL parameters, Civil War genealogy tactics, phonetic
matching algorithms, naming conventions, local DB analysis, and a
broadened training set of 43,834 CW soldiers pulled from
`freecivilwarrecords.org`.

[`docs/v5-design/`](./docs/v5-design/) contains the proposed v5.0
strategy ladder and design playbook.

### Tools

| Tool | Purpose |
|---|---|
| [`process_ledger.py`](./process_ledger.py) | Converts a JSON export from `FindaGraveScraper` into CSV and per-record Markdown. |
| [`scripts/`](./scripts/) | Analysis scripts for the research workspace (rebuild broadened set, validate strategies, etc.) |

## Installing the scraper

1. Install a userscript manager from the links below.
2. Open `FindaGraveScraper.user.js` in a text editor and copy its
   contents.
3. In your userscript manager, choose **Create new script** and paste.
4. Save. Confirm the script is enabled and matches against
   `https://www.findagrave.com/memorial/*`.

### Requirements

- [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Edge, Firefox, Safari)
- [Greasemonkey](https://www.greasespot.net/) (Firefox)
- [Violentmonkey](https://violentmonkey.github.io/) (any modern browser)

## Using the scraper

1. Visit any Find a Grave memorial page (URL of the form
   `https://www.findagrave.com/memorial/<id>/...`).
2. A small dark panel appears in the bottom-right corner labelled
   **▼ Scraper**. Click the toggle to expand it.
3. Click **Scrape Current Page** to capture the current memorial into
   the ledger.
4. Browse to other memorial pages and repeat. Re-visiting a memorial
   updates the existing record instead of duplicating.
5. When ready, click **Export Data (N)**. Your browser will download
   `memorials_archive.json`. A confirmation prompt offers to clear
   the in-script ledger so you can start a fresh batch.

See `process_ledger.py` for processing the export.

## The search helper (v4.0)

The existing `FindaGraveIterativeHelper.user.js` is a working
5-strategy search ladder. See [docs/v5-design/strategy-ladder.md](./docs/v5-design/strategy-ladder.md)
for the proposed v5.0 design that will replace it.

## Output schema (from the scraper)

Each record in `memorials_archive.json` looks like this:

```json
{
  "memorial_id": "12345678",
  "name": "Jane Doe",
  "url": "https://www.findagrave.com/memorial/12345678/jane-doe",
  "birth_date": "12 Jan 1820",
  "birth_location": "Springfield, Illinois, USA",
  "death_date": "3 Mar 1894",
  "death_age": 74,
  "death_location": "Chicago, Illinois, USA",
  "burial_cemetery": "Rosehill Cemetery",
  "burial_location": "Chicago, Cook County, Illinois, USA",
  "biography": "Daughter of ...; wife of ...",
  "family_parents": ["John Doe", "Mary Roe"],
  "family_spouse": "James Smith",
  "family_children": ["Alice Smith", "Bob Smith"],
  "scraped_at": "2026-07-01T14:32:10.000Z"
}
```

Fields may be empty strings (`""`) or `null` when the corresponding
data was not present on the page.

## Processing the export with Python

Once you have `memorials_archive.json`, the example script below
produces both a human-readable CSV summary and per-record Markdown
files suitable for use in a static-site generator or note-taking
workflow.

```bash
python process_ledger.py memorials_archive.json
```

Output:
- `memorials.csv` — flat summary, one row per memorial
- `memorials/` — directory of per-record Markdown files

## Ethical use

- These tools are intended for personal genealogical research and
  archival of memorials you have a legitimate reason to preserve.
- Be courteous to Find a Grave's servers — avoid scraping faster
  than a human browsing pace (1-2 req/sec).
- Respect the wishes of memorial owners: if a memorial has been
  removed or marked private, do not redistribute its content.
- The search helper is intended to find memorials that exist for
  real people. Do not use it to create spurious memorials or
  flood FaG with low-quality submissions.

## License

[MIT](./LICENSE)