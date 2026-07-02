# FindAGraveHelper

A Tampermonkey/Greasemonkey userscript that scrapes memorial data from
[Find a Grave](https://www.findagrave.com) memorial pages and exports the
results as a single JSON file for offline archival or downstream processing.

## Features

- Extracts core memorial data: name, birth/death dates and locations,
  burial cemetery/location, biography, and family relationships (parents,
  spouse, children).
- Stores scraped records in a per-script ledger (via `GM_getValue` /
  `GM_setValue`) so you can build a batch across many memorial pages
  before exporting.
- Updates existing records in place by `memorial_id`, so re-scraping the
  same memorial does not create duplicates.
- Floating in-page control panel with two buttons:
  - **Scrape Current Page** — capture the memorial you're currently viewing.
  - **Export Data (N)** — download the full ledger as
    `memorials_archive.json`.
- Optionally clears the ledger after a successful export so you can start a
  new batch.

## Requirements

- A userscript manager:
  - [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Edge, Firefox, Safari)
  - [Greasemonkey](https://www.greasespot.net/) (Firefox)
  - [Violentmonkey](https://violentmonkey.github.io/) (any modern browser)

## Installation

1. Install a userscript manager from the links above.
2. Open `FindaGraveScraper.user.js` in a text editor (or download the raw
   file from this repo) and copy its contents.
3. In your userscript manager, choose **Create new script** and paste.
4. Save. Confirm the script is enabled and matches against
   `https://www.findagrave.com/memorial/*`.

## Usage

1. Visit any Find a Grave memorial page (URL of the form
   `https://www.findagrave.com/memorial/<id>/...`).
2. A small dark panel appears in the bottom-right corner labelled
   **▼ Scraper**. Click the toggle to expand it.
3. Click **Scrape Current Page** to capture the current memorial into the
   ledger.
4. Browse to other memorial pages and repeat. Re-visiting a memorial
   updates the existing record instead of duplicating.
5. When ready, click **Export Data (N)**. Your browser will download
   `memorials_archive.json`. A confirmation prompt offers to clear the
   in-script ledger so you can start a fresh batch.

## Output schema

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

Fields may be empty strings (`""`) or `null` when the corresponding data
was not present on the page.

## Processing the export with Python

Once you have `memorials_archive.json`, the example script below produces
both a human-readable CSV summary and per-record Markdown files suitable
for use in a static-site generator or note-taking workflow.

Save this as `process_ledger.py` next to `memorials_archive.json`:

```python
#!/usr/bin/env python3
"""Process a FindAGraveHelper export.

Reads `memorials_archive.json` (produced by FindaGraveScraper.user.js)
and writes:
  - `memorials.csv`        flat summary, one row per memorial
  - `memorials/`           directory of per-record Markdown files

Usage:
    python process_ledger.py memorials_archive.json
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable


def load_ledger(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array, got {type(data).__name__}")
    return data


def write_csv(records: Iterable[dict[str, Any]], out: Path) -> None:
    fieldnames = [
        "memorial_id",
        "name",
        "birth_date",
        "birth_location",
        "death_date",
        "death_age",
        "death_location",
        "burial_cemetery",
        "burial_location",
        "scraped_at",
        "url",
    ]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            writer.writerow(row)


def _md_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "—"
    return str(value)


def write_markdown(records: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for rec in records:
        memorial_id = rec.get("memorial_id") or "unknown"
        slug = f"{memorial_id}-{(rec.get('name') or 'unknown').lower().replace(' ', '-')}"
        slug = "".join(c for c in slug if c.isalnum() or c in ("-", "_"))

        lines = [
            f"# {rec.get('name') or 'Unknown'}",
            "",
            f"- **Memorial ID:** {memorial_id}",
            f"- **URL:** <{rec.get('url')}>",
            "",
            "## Dates",
            "",
            f"- **Born:** {_md_value(rec.get('birth_date'))} — {_md_value(rec.get('birth_location'))}",
            f"- **Died:** {_md_value(rec.get('death_date'))} (age {_md_value(rec.get('death_age'))}) — {_md_value(rec.get('death_location'))}",
            "",
            "## Burial",
            "",
            f"- **Cemetery:** {_md_value(rec.get('burial_cemetery'))}",
            f"- **Location:** {_md_value(rec.get('burial_location'))}",
            "",
            "## Family",
            "",
            f"- **Parents:** {_md_value(rec.get('family_parents'))}",
            f"- **Spouse:** {_md_value(rec.get('family_spouse'))}",
            f"- **Children:** {_md_value(rec.get('family_children'))}",
            "",
            "## Biography",
            "",
            _md_value(rec.get('biography')),
            "",
            f"_Scraped at {rec.get('scraped_at')}_",
            "",
        ]
        (out_dir / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <memorials_archive.json>", file=sys.stderr)
        return 1

    src = Path(sys.argv[1]).resolve()
    if not src.is_file():
        print(f"File not found: {src}", file=sys.stderr)
        return 1

    records = load_ledger(src)
    print(f"Loaded {len(records)} record(s) from {src.name}")

    write_csv(records, src.with_name("memorials.csv"))
    write_markdown(records, src.with_name("memorials"))
    print(f"Wrote {src.with_name('memorials.csv').name}")
    print(f"Wrote {src.with_name('memorials').name}/  ({len(records)} Markdown file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Example run

```text
$ python process_ledger.py memorials_archive.json
Loaded 142 record(s) from memorials_archive.json
Wrote memorials.csv
Wrote memorials/  (142 Markdown file(s))
```

## Ethical use

- This tool is intended for personal genealogical research and archival
  of memorials you have a legitimate reason to preserve.
- Be courteous to Find a Grave's servers — avoid scraping faster than a
  human browsing pace.
- Respect the wishes of memorial owners: if a memorial has been
  removed or marked private, do not redistribute its content.

## License

[MIT](./LICENSE)
