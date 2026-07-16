#!/usr/bin/env python3
"""Spouse cross-reference prototype.

Validates the approach by fetching FaG memorial pages for our
575 known local records and extracting:
  - spouse_name
  - children

Then checks whether the spouse name matches a widow record in
the unified OK pension list, OR whether a child's name appears
in another unified record. These matches would let us
cross-verify a pensioner from a separate record.

Output:
  - C:/tmp/fag_gt/spouse_index.json  (memorial_id → spouse + children)
  - stdout summary

This takes ~5-10 minutes for 575 records.

Usage:
  python scripts/spouse_prototype.py --limit 50
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from scripts.spouse_extract import extract_spouse, extract_children

LOCAL_CSV = "C:/Development/FindAGraveHelper/docs/research/local-data/local_soldiers_with_fag.csv"
UNIFIED_JSON = "C:/tmp/ok_pensioners.json"
OUTPUT_INDEX = "C:/tmp/fag_gt/spouse_index.json"


def fetch_memorial(page, mem_id: str, slug: str) -> dict:
    """Visit a memorial page and return extracted family data."""
    url = f"https://www.findagrave.com/memorial/{mem_id}/{slug}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        body = page.inner_text("body", timeout=10000)
        return {
            "url": url,
            "spouse": extract_spouse(body),
            "children": extract_children(body),
        }
    except Exception as e:
        return {"url": url, "error": str(e), "spouse": None, "children": []}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", default=OUTPUT_INDEX)
    parser.add_argument("--unified", default=UNIFIED_JSON)
    args = parser.parse_args()

    # Load local records (which have FaG URLs)
    local = list(csv.DictReader(open(LOCAL_CSV, encoding="utf-8")))
    url_re = re.compile(r"findagrave\.com/memorial/(\d+)/([^/\s\"'#]+)", re.I)

    targets = []
    for r in local:
        if not r.get("last_name"):
            continue
        for field in ("app_id", "details"):
            m = url_re.search(r.get(field, "") or "")
            if m:
                targets.append({
                    "s_id": r["s_id"],
                    "first_name": r["first_name"],
                    "last_name": r["last_name"],
                    "death_year": r.get("death_year", ""),
                    "memorial_id": m.group(1),
                    "slug": m.group(2),
                })
                break
    targets = targets[:args.limit]
    print(f"Visiting {len(targets)} memorial pages…")

    # Build unified lookup for cross-ref
    unified = json.load(open(args.unified, encoding="utf-8"))
    # Index by last_name (uppercase) for fast lookup
    by_last: dict[str, list[dict]] = {}
    for r in unified:
        ln = (r.get("last_name") or "").upper()
        if ln:
            by_last.setdefault(ln, []).append(r)

    # Browser
    p = sync_playwright().start()
    b = p.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    ctx = b.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Safari/537.36"
        ),
        viewport={"width": 1280, "height": 720},
        locale="en-US",
        timezone_id="America/Chicago",
    )
    page = ctx.new_page()
    Stealth().apply_stealth_sync(page)

    # Warmup
    page.goto("https://www.findagrave.com/", wait_until="domcontentloaded", timeout=20000)
    time.sleep(3)

    results = {}
    cross_refs = []
    for i, t in enumerate(targets, 1):
        mid = t["memorial_id"]
        print(f"[{i}/{len(targets)}] {t['first_name']} {t['last_name']} (memorial {mid})…")
        data = fetch_memorial(page, mid, t["slug"])
        results[mid] = data
        # Cross-reference: spouse name → unified widow record?
        if data.get("spouse"):
            spouse = data["spouse"]
            s_last = spouse["last_name"].upper()
            s_first = spouse["first_name"].upper()
            candidates = by_last.get(s_last, [])
            soldier_last = t["last_name"].upper()
            for c in candidates:
                # Check: widow has first name + last name matching FaG spouse
                c_first = (c.get("first_name") or "").upper()
                c_last = (c.get("last_name") or "").upper()
                # Widow's name on record matches FaG spouse
                if c_first and c_last and c_last == s_last:
                    # First-name match (loose: handle "Fannie" = "Fayette J.")
                    fname_match = (
                        s_first.startswith(c_first[:3])
                        or c_first.startswith(s_first[:3])
                        or s_first[:1] == c_first[:1]
                    )
                    if not fname_match:
                        continue
                    # AND widow's spouse_name_raw mentions our soldier's last name
                    spouse_raw = (c.get("spouse_name_raw") or "").upper()
                    if soldier_last not in spouse_raw and c_last not in spouse_raw:
                        continue
                    cross_refs.append({
                        "type": "spouse_match",
                        "soldier_record": t,
                        "soldier_faG_id": mid,
                        "widow_record": {
                            "id": c["id"],
                            "name": c["name_raw"],
                            "spouse_name_raw": c["spouse_name_raw"],
                            "regiment": c["regiment"],
                        },
                        "faG_spouse": spouse,
                        "match_strength": "strong" if fname_match and soldier_last in spouse_raw else "loose",
                    })
                    break
        time.sleep(1.5)  # throttle

    b.close()
    p.stop()

    # Save
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote index: {args.output}")
    print(f"Cross-refs found: {len(cross_refs)}")
    for cr in cross_refs[:5]:
        s_name = f"{cr['soldier_record']['first_name']} {cr['soldier_record']['last_name']}"
        print(f"  [SOLDIER] {s_name} (FaG {cr['soldier_faG_id']})")
        print(f"     [WIDOW] {cr['widow_record']['name']} (unified #{cr['widow_record']['id']})")
        print(f"     FaG spouse: {cr['faG_spouse']['raw_name']} ({cr['faG_spouse']['birth_year']}-{cr['faG_spouse']['death_year']})")
        print()
    return results, cross_refs


if __name__ == "__main__":
    main()