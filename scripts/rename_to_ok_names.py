"""One-shot rename: unified.json -> ok_pensioners.json + add provenance _meta.

T015 of the refactor. Idempotent. Run from repo root:

  python scripts/rename_to_ok_names.py [--dry-run]

Reads the source files, writes the new files with a sibling _meta.json,
then removes the originals.

Why a sibling _meta.json instead of embedding in the data file?
- unified.json is a JSON array (consumers iterate it). Embedding _meta
  as a special first record would break every consumer that expects
  every record to have a pensioner_id.
- ok_cemeteries.jsonl is JSONL (one JSON per line). Same issue: a
  special first line would break parsers.

A sibling *.meta.json is the cleanest provenance-bearing pattern.

Backwards-safe: prints the path map before doing anything so a human
can verify; --dry-run stops before any rename.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Source -> (new data path, new meta path, source_url, source_collection)
RENAMES = [
    {
        "data_src": ROOT / "docs" / "research" / "digitalprairie" / "unified.json",
        "data_dst": ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners.json",
        "meta_dst": ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners.meta.json",
        "source_url": "https://digitalprairie.ok.gov/digital/collection/pensions",
        "source_collection": "pensions + pensioncard (merged on application_number)",
        "record_count_field": None,  # JSON array, count by len()
    },
    {
        "data_src": ROOT / "docs" / "research" / "digitalprairie" / "unified_sample_50.json",
        "data_dst": ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners_sample_50.json",
        "meta_dst": ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners_sample_50.meta.json",
        "source_url": "https://digitalprairie.ok.gov/digital/collection/pensions",
        "source_collection": "pensions + pensioncard (merged on application_number; 50-record sample)",
        "record_count_field": None,
    },
    {
        "data_src": ROOT / "docs" / "research" / "cgr" / "ok_cemeteries.jsonl",
        "data_dst": ROOT / "docs" / "research" / "cgr" / "ok_cemeteries.jsonl",  # already named
        "meta_dst": ROOT / "docs" / "research" / "cgr" / "ok_cemeteries.meta.json",
        "source_url": "https://www.confederategraves.com/search.php",
        "source_collection": "Oklahoma Confederate Graves Registry scrape (CGR)",
        "record_count_field": "cemetery_count",
    },
]


def count_json_array(path: Path) -> int:
    return len(json.loads(path.read_text(encoding="utf-8")))


def count_jsonl(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def build_meta(item: dict, record_count: int) -> dict:
    return {
        "_meta": {
            "source_url": item["source_url"],
            "source_collection": item["source_collection"],
            "pulled_at": datetime.now(timezone.utc).isoformat(),
            "record_count": record_count,
            "schema_version": 1,
        }
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Print the planned renames + meta, do not write")
    args = p.parse_args()

    print(f"Renames planned (root={ROOT}):\n")
    plan = []
    for item in RENAMES:
        if not item["data_src"].exists():
            print(f"  SKIP: {item['data_src']} (not present)")
            continue

        # Count records
        if str(item["data_src"]).endswith(".json"):
            count = count_json_array(item["data_src"])
        else:
            count = count_jsonl(item["data_src"])

        meta = build_meta(item, count)
        plan.append((item, meta))
        print(f"  data: {item['data_src'].name} -> {item['data_dst'].name}")
        print(f"  meta: {item['meta_dst'].name}")
        print(f"    source_url:    {item['source_url']}")
        print(f"    source_coll:   {item['source_collection']}")
        print(f"    record_count:  {count}")
        print()

    if args.dry_run:
        print("DRY RUN: no files written.")
        return 0

    # Execute
    for item, meta in plan:
        # Write meta first (provenance survives even if rename fails)
        item["meta_dst"].write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        # Rename data (only if destination differs)
        if item["data_src"] != item["data_dst"]:
            item["data_dst"].write_bytes(item["data_src"].read_bytes())
            item["data_src"].unlink()
            print(f"  renamed: {item['data_src'].name} -> {item['data_dst'].name}")
        else:
            print(f"  kept:    {item['data_src'].name} (already named ok_*)")
        print(f"  wrote:   {item['meta_dst'].name}")

    print(f"\nDone. {len(plan)} file(s) renamed + {len(plan)} meta file(s) written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())