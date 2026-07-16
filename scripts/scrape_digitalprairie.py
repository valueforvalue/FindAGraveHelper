#!/usr/bin/env python3
"""Scrape the Oklahoma Digital Prairie Confederate Pension Records collection.

Source: https://digitalprairie.ok.gov/digital/collection/pensions
        (alias: 'pensions')

Each pension file is a single-item record served by the CONTENTdm v13
single-item JSON API:

  GET https://digitalprairie.ok.gov/digital/api/singleitem/collection/pensions/id/<id>

The API returns structured metadata fields directly — no OCR or PDF
text extraction required. We iterate ID range 1..N (where N is the
max ID with a record) and collect:

  - All structured metadata fields (Name, App#, Pension#, Company,
    Regiment, Subject, Description, etc.)
  - IIIF image URL for visual verification
  - Public-facing backlink to the record page on digitalprairie.ok.gov

Output:
  - <out_dir>/pensions.csv       parsed fields, one row per record
  - <out_dir>/pensions.json      full record with backlink + IIIF URL
  - <out_dir>/scrape.log        progress + errors

Resume-safe: skips IDs already in the output JSON.

Usage:
  python scrape_digitalprairie.py --out-dir C:/tmp/dp_pensions
  python scrape_digitalprairie.py --out-dir docs/research/digitalprairie \\
         --max-id 8000 --concurrency 10
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# API base
API_BASE_PENSIONS = "https://digitalprairie.ok.gov/digital/api/singleitem/collection/pensions/id"
API_BASE_PENSIONCARD = "https://digitalprairie.ok.gov/digital/api/singleitem/collection/pensioncard/id"
# Public-facing URL for the record page
PUBLIC_URL_PENSIONS = "https://digitalprairie.ok.gov/digital/singleitem/collection/pensions/id/{id}"
PUBLIC_URL_PENSIONCARD = "https://digitalprairie.ok.gov/digital/singleitem/collection/pensioncard/id/{id}"
# IIIF image URL
IIIF_URL_PENSIONS = "https://digitalprairie.ok.gov/iiif/2/pensions:{id}/full/full/0/default.jpg"
IIIF_URL_PENSIONCARD = "https://digitalprairie.ok.gov/iiif/2/pensioncard:{id}/full/full/0/default.jpg"

# CSV columns (in order)
CSV_FIELDS = [
    "id",
    "name_raw",
    "first_name",
    "middle_name",
    "last_name",
    "spouse_name",
    "application_number",
    "pension_number",
    "company",
    "regiment",
    "subject",
    "coverage",
    "creator",
    "publisher",
    "date",
    "backlink",
    "iiif_url",
    "api_url",
]

# Log setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("scrape")


def fetch_item(item_id: int, collection: str = "pensions",
               timeout: float = 15.0) -> dict[str, Any] | None:
    """Fetch one item by ID from a given collection. Returns None if 404."""
    if collection == "pensions":
        api_base = API_BASE_PENSIONS
    else:
        api_base = API_BASE_PENSIONCARD
    url = f"{api_base}/{item_id}"
    req = Request(url, headers={"User-Agent": "FindAGraveHelper-research/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read())
            if "message" in data and data.get("stack"):
                return None
            if not data.get("fields"):
                return None
            return data
    except HTTPError as e:
        if e.code == 404:
            return None
        raise
    except (URLError, TimeoutError) as e:
        log.warning("Network error for collection=%s id=%s: %s", collection, item_id, e)
        return None
    except json.JSONDecodeError as e:
        log.warning("JSON decode error for id=%s: %s", item_id, e)
        return None


def parse_fields(data: dict[str, Any]) -> dict[str, str]:
    """Convert the API's `fields` array into a flat dict keyed by `key`."""
    return {f["key"]: (f.get("value") or "").strip() for f in data.get("fields", [])}


def parse_name(name: str) -> tuple[str, str, str]:
    """Parse 'Last, First Middle' into (first, middle, last).

    Examples:
      'Morrow, Emily'           -> ('Emily', '',     'Morrow')
      'Barefield, Cary R.'      -> ('Cary',   'R.',   'Barefield')
      'Anderson, William T. J.' -> ('William','T. J.','Anderson')
      'Walker, Capt. Henry'     -> ('Capt. Henry','','Walker')   # conservative

    Returns ('', '', '') if name is empty.
    """
    name = (name or "").strip()
    if not name:
        return ("", "", "")
    if "," in name:
        last, rest = name.split(",", 1)
        last = last.strip()
        rest = rest.strip()
        parts = rest.split()
        if len(parts) == 0:
            return ("", "", last)
        first = parts[0]
        middle = " ".join(parts[1:])
        return (first, middle, last)
    parts = name.split()
    if len(parts) == 1:
        return ("", "", parts[0])
    return (parts[0], " ".join(parts[1:]), "")


def parse_spouse_name(spouse: str) -> tuple[str, str, str]:
    """Same as parse_name but for the `spouse` field."""
    return parse_name(spouse)


def build_record(item_id: int, data: dict[str, Any],
                 collection: str = "pensions") -> dict[str, Any]:
    """Build the JSON record for one item."""
    fields = parse_fields(data)
    name = fields.get("title", "")
    spouse = fields.get("spouse", "")
    first, middle, last = parse_name(name)
    sp_first, sp_mid, sp_last = parse_spouse_name(spouse)

    if collection == "pensions":
        backlink = PUBLIC_URL_PENSIONS.format(id=item_id)
        iiif = IIIF_URL_PENSIONS.format(id=item_id)
        api_url = f"{API_BASE_PENSIONS}/{item_id}"
    else:
        backlink = PUBLIC_URL_PENSIONCARD.format(id=item_id)
        iiif = IIIF_URL_PENSIONCARD.format(id=item_id)
        api_url = f"{API_BASE_PENSIONCARD}/{item_id}"

    record = {
        "id": item_id,
        "collection": collection,
        "name_raw": name,
        "first_name": first,
        "middle_name": middle,
        "last_name": last,
        "spouse_name_raw": spouse,
        "spouse_first_name": sp_first,
        "spouse_middle_name": sp_mid,
        "spouse_last_name": sp_last,
        "application_number": fields.get("applic", ""),
        "pension_number": fields.get("pensio", ""),
        "company": fields.get("compan", ""),
        "regiment": fields.get("regime", ""),
        "subject": fields.get("subjec", ""),
        "coverage": fields.get("covera", ""),
        "creator": fields.get("author", "") or fields.get("creato", ""),
        "publisher": fields.get("publia", ""),
        "date": fields.get("date", ""),
        "rights": fields.get("rights", "") or fields.get("righta", ""),
        "language": fields.get("langua", ""),
        "description": fields.get("descri", ""),
        "backlink": backlink,
        "iiif_url": iiif,
        "image_uri": data.get("imageUri", ""),
        "iiif_info_uri": data.get("iiifInfoUri", ""),
        "thumbnail_uri": data.get("thumbnailUri", ""),
        "download_uri": data.get("downloadUri", ""),
        "api_url": api_url,
        "all_fields": fields,
    }
    return record


def to_csv_row(record: dict[str, Any]) -> dict[str, str]:
    """Convert a record to a CSV row using CSV_FIELDS ordering."""
    return {f: record.get(f, "") for f in CSV_FIELDS}


def find_max_id(start: int, end: int, step: int = 500,
               collection: str = "pensions") -> int:
    """Binary-search-ish for the max item ID with a record."""
    log.info("Probing %s collection for max ID between %d and %d (step %d)...",
             collection, start, end, step)
    last_hit = start
    probe = start
    while probe <= end:
        if fetch_item(probe, collection) is not None:
            last_hit = probe
            log.info("  Probe id=%d: HIT", probe)
        else:
            log.info("  Probe id=%d: empty", probe)
            break
        probe += step
    log.info("Refining %s between %d and %d...", collection, last_hit, last_hit + step)
    lo, hi = last_hit, last_hit + step
    while hi - lo > 5:
        mid = (lo + hi) // 2
        if fetch_item(mid, collection) is not None:
            lo = mid
        else:
            hi = mid
    log.info("%s max ID is approximately %d", collection, lo)
    return lo


def load_existing_for_collection(out_dir: Path, collection: str) -> set[int]:
    """Load existing IDs for a specific collection."""
    path = out_dir / f"{collection}.json"
    if not path.exists():
        return set()
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return {r["id"] for r in data if "id" in r}
    except (json.JSONDecodeError, OSError):
        return set()


def save_records(out_dir: Path, records: list[dict[str, Any]], collection: str) -> None:
    """Write JSON + CSV atomically."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{collection}.json"
    csv_path = out_dir / f"{collection}.csv"

    records = sorted(records, key=lambda r: r["id"])

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(to_csv_row(rec))


def scrape_range(
    out_dir: Path,
    min_id: int = 1,
    max_id: int | None = None,
    concurrency: int = 10,
    auto_probe: bool = True,
    save_every: int = 100,
    collection: str = "pensions",
) -> list[dict[str, Any]]:
    """Scrape IDs in [min_id, max_id] from a collection. Returns list of records."""
    out_dir.mkdir(parents=True, exist_ok=True)

    if max_id is None and auto_probe:
        max_id = find_max_id(min_id, 10000, collection=collection)

    if max_id is None:
        log.error("Could not determine max_id for %s; pass --max-id", collection)
        return []

    log.info("Scraping %s IDs %d..%d with concurrency %d",
             collection, min_id, max_id, concurrency)

    existing = load_existing_for_collection(out_dir, collection)
    if existing:
        log.info("Resume: %d %s records already on disk, will skip",
                 len(existing), collection)

    records: dict[int, dict[str, Any]] = {}
    json_path = out_dir / f"{collection}.json"
    if json_path.exists():
        try:
            records = {r["id"]: r for r in json.load(json_path.open(encoding="utf-8"))}
        except Exception as e:
            log.warning("Could not load existing %s: %s", json_path, e)

    ids_to_fetch = [i for i in range(min_id, max_id + 1) if i not in existing]
    log.info("Will fetch %d new %s records", len(ids_to_fetch), collection)

    if not ids_to_fetch:
        return list(records.values())

    fetched = 0
    errors = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(fetch_item, i, collection): i for i in ids_to_fetch}
        for fut in as_completed(futures):
            item_id = futures[fut]
            try:
                data = fut.result()
                if data is not None:
                    records[item_id] = build_record(item_id, data, collection)
            except Exception as e:
                log.warning("%s id=%s failed: %s", collection, item_id, e)
                errors += 1
            fetched += 1
            if fetched % save_every == 0:
                save_records(out_dir, list(records.values()), collection)
                elapsed = time.time() - t0
                rate = fetched / elapsed if elapsed > 0 else 0
                log.info("Progress: %d/%d %s fetched (%d errors, %.1f/sec)",
                         fetched, len(ids_to_fetch), collection, errors, rate)

    save_records(out_dir, list(records.values()), collection)
    elapsed = time.time() - t0
    log.info("Done. %d %s records in %s (%d errors, %.1f sec)",
             len(records), collection, out_dir, errors, elapsed)
    return list(records.values())


def merge_collections(out_dir: Path) -> None:
    """Merge pensions + pensioncard on application_number, output unified.json.

    The `pensions` collection has the application file. The `pensioncard`
    collection has the regiment/company metadata. Same person has the same
    application number in both.
    """
    log.info("Merging pensions + pensioncard collections...")
    pensions_path = out_dir / "pensions.json"
    cards_path = out_dir / "pensioncard.json"
    if not pensions_path.exists() or not cards_path.exists():
        log.error("Need both pensions.json and pensioncard.json to merge")
        return

    pensions = json.load(pensions_path.open(encoding="utf-8"))
    cards = json.load(cards_path.open(encoding="utf-8"))

    # Index cards by application number (and pension number, fallback to name)
    by_app: dict[str, dict[str, Any]] = {}
    by_pen: dict[str, dict[str, Any]] = {}
    by_name: dict[tuple, dict[str, Any]] = {}
    for c in cards:
        app = c.get("application_number", "").strip()
        pen = c.get("pension_number", "").strip()
        name = (c.get("last_name", ""), c.get("first_name", ""))
        if app:
            by_app[app] = c
        if pen:
            by_pen[pen] = c
        if name[0] and name[1]:
            by_name[name] = c

    merged = []
    matched_card = 0
    unmatched = 0
    for p in pensions:
        app = p.get("application_number", "").strip()
        pen = p.get("pension_number", "").strip()
        card = by_app.get(app) or by_pen.get(pen)
        if card is None:
            name_key = (p.get("last_name", ""), p.get("first_name", ""))
            card = by_name.get(name_key)
        if card:
            matched_card += 1
        else:
            unmatched += 1
        # Merge: take file from pensions, regiment/company/spouse from card
        merged_record = dict(p)
        if card:
            for k in ("company", "regiment", "spouse_name_raw",
                      "spouse_first_name", "spouse_middle_name", "spouse_last_name",
                      "publisher", "language"):
                v = card.get(k)
                if v and not merged_record.get(k):
                    merged_record[k] = v
            merged_record["pensioncard_id"] = card["id"]
            merged_record["pensioncard_backlink"] = card["backlink"]
            merged_record["pensioncard_iiif_url"] = card["iiif_url"]
            merged_record["pensioncard_all_fields"] = card["all_fields"]
        merged.append(merged_record)

    log.info("Merged %d pensions records: %d matched a card, %d unmatched",
             len(merged), matched_card, unmatched)

    # Write merged output
    out_json = out_dir / "unified.json"
    out_csv = out_dir / "unified.csv"
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    csv_fields = CSV_FIELDS + ["pensioncard_id", "pensioncard_backlink"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for rec in merged:
            writer.writerow({k: rec.get(k, "") for k in csv_fields})

    log.info("Wrote %s and %s", out_json, out_csv)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", type=Path, required=True,
                   help="Directory to write per-collection JSON+CSV and unified output")
    p.add_argument("--min-id", type=int, default=1,
                   help="Lowest ID to fetch (default: 1)")
    p.add_argument("--max-id", type=int, default=None,
                   help="Highest ID to fetch (default: auto-probe)")
    p.add_argument("--concurrency", type=int, default=10,
                   help="Concurrent requests (default: 10)")
    p.add_argument("--no-probe", action="store_true",
                   help="Skip auto-probe of max ID (require --max-id)")
    p.add_argument("--save-every", type=int, default=100,
                   help="Save progress every N records (default: 100)")
    p.add_argument("--collection", choices=["pensions", "pensioncard", "both"],
                   default="both",
                   help="Which collection(s) to scrape (default: both)")
    p.add_argument("--no-merge", action="store_true",
                   help="Skip the pensions + pensioncard merge step")
    args = p.parse_args()

    collections = ["pensions", "pensioncard"] if args.collection == "both" else [args.collection]
    for c in collections:
        scrape_range(
            out_dir=args.out_dir,
            min_id=args.min_id,
            max_id=args.max_id,
            concurrency=args.concurrency,
            auto_probe=not args.no_probe,
            save_every=args.save_every,
            collection=c,
        )

    if not args.no_merge and len(collections) == 2:
        merge_collections(args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())