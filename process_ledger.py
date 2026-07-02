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
