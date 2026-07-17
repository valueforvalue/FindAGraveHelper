"""Fetch pension card page IDs from digitalprairie.ok.gov API.

For each pensioner with a pensioncard_id, fetches the JSON metadata
once and stores the page IDs (Side 1, Side 2, etc.) so view.html can
embed the IIIF images directly without browser-side fetches.

Output: a sidecar JSON file keyed by pensioner_id, mapping to the
list of page IDs. Cached so re-runs are instant.

Usage:
    python scripts/ingest/fetch_pensioncard_pages.py
    python scripts/ingest/fetch_pensioncard_pages.py --refresh
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

# Bootstrap sys.path so this script can be invoked as `python scripts/X.py`
_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PENSIONCARD_API = (
    "https://digitalprairie.ok.gov/digital/api/singleitem/"
    "collection/pensioncard/id/{id}"
)
DEFAULT_INPUT = Path("docs/research/digitalprairie/ok_pensioners.json")
DEFAULT_OUTPUT = Path(
    "docs/research/digitalprairie/ok_pensioners.pensioncard_pages.json"
)

# Conservative throttle to be a good citizen. The API endpoint is light
# (no rendering, no Cloudflare Turnstile) but we don't want to hammer.
THROTTLE_SECONDS = 0.25


def fetch_pensioncard_json(pensioncard_id: int) -> dict | None:
    """Fetch the digitalprairie API JSON for one pensioncard_id.

    Returns the parsed JSON or None on any error (404, network, parse).
    """
    url = PENSIONCARD_API.format(id=pensioncard_id)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (FindAGraveHelper; pensioncard-pages-fetch)"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logging.warning("Failed to fetch pensioncard %d: %s", pensioncard_id, e)
        return None


def extract_page_ids(api_json: dict | None, pcid: int) -> list[int]:
    """Pull page IDs from the digitalprairie API JSON.

    The API has two shapes:

    1. Compound objects (e.g. two-sided postcards): objectInfo.page[]
       contains pageptr values that ARE the IIIF image IDs. Use those.
       Example for pcid=11486:
         objectInfo.page[0].pageptr == 11484  (Side 1)
         objectInfo.page[1].pageptr == 11485  (Side 2)

    2. Single-page objects: objectInfo.code == -2 ("Requested item
       is not compound") and objectInfo.page is missing. In that case,
       the IIIF image IS the pcid itself.

    The IIIF URL pattern that works for both:
       https://digitalprairie.ok.gov/iiif/2/pensioncard:{id}/full/300,/0/default.jpg

    Historical bug: the old version of this function only looked at
    objectInfo.page[].pageptr and returned [] for single-page items.
    That left 73% of pensioncards (mostly single-page) without an
    image in view.html even though the IIIF URL worked.

    Args:
        api_json: parsed JSON from
            https://digitalprairie.ok.gov/digital/api/singleitem/collection/pensioncard/id/{pcid}
        pcid: the pensioncard_id for the item. Used as the page ID
            for single-page items (where objectInfo.page is missing).

    Returns:
        list[int]: 1 page ID for single-page items, 2 for compound,
            empty list if the API JSON is malformed or has neither
            pageptr entries nor an imageUri to fall back on.
    """
    if not api_json:
        return []
    obj_info = api_json.get("objectInfo", {})
    pages = obj_info.get("page") or []
    out = []
    for p in pages:
        ptr = p.get("pageptr")
        if ptr is not None:
            try:
                out.append(int(ptr))
            except (TypeError, ValueError):
                continue
    if out:
        return out
    # No compound pages. If the API returned an imageUri, fall back
    # to using pcid as the single page ID. This is the path for
    # single-page items (objectInfo.code == -2).
    if api_json.get("imageUri"):
        return [pcid]
    return []


def load_cache(cache_path: Path) -> dict[str, list[int]]:
    """Load existing cache. Returns {} if missing or corrupt."""
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache_path: Path, data: dict[str, list[int]]) -> None:
    """Persist the page-id cache. Atomic write via .tmp + replace."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(cache_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help=f"Source ok_pensioners.json (default: {DEFAULT_INPUT})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Sidecar output (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--throttle", type=float, default=THROTTLE_SECONDS,
                        help=f"Seconds between API calls (default: {THROTTLE_SECONDS})")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch even when cached")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N records (smoke test)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.input.exists():
        logging.error("Input file not found: %s", args.input)
        return 1

    pensioners = json.loads(args.input.read_text(encoding="utf-8"))
    logging.info("Loaded %d pensioners from %s", len(pensioners), args.input)

    cache: dict[str, list[int]] = {} if args.refresh else load_cache(args.output)
    if cache and not args.refresh:
        logging.info("Cache hit: %d entries in %s", len(cache), args.output)

    # Records that need fetching
    targets = [r for r in pensioners if r.get("pensioncard_id")]
    if args.limit:
        targets = targets[:args.limit]
    logging.info("Will process %d records (have pensioncard_id)", len(targets))

    fetched = 0
    skipped = 0
    failed = 0
    started = time.time()

    for i, rec in enumerate(targets):
        pid = rec["id"]
        pcid = rec["pensioncard_id"]
        key = str(pid)

        if not args.refresh and key in cache:
            skipped += 1
            continue

        if args.throttle > 0:
            time.sleep(args.throttle)

        api_json = fetch_pensioncard_json(pcid)
        page_ids = extract_page_ids(api_json, pcid)
        if page_ids:
            cache[key] = page_ids
            fetched += 1
        else:
            failed += 1
            logging.warning("No page IDs for pensioner_id=%d pensioncard_id=%d",
                            pid, pcid)

        # Periodic checkpoint so a long run can be resumed
        if (i + 1) % 100 == 0:
            save_cache(args.output, cache)
            elapsed = time.time() - started
            rate = (fetched + failed) / elapsed if elapsed > 0 else 0
            eta_sec = (len(targets) - i - 1) / rate if rate > 0 else 0
            logging.info(
                "Progress: %d/%d  fetched=%d skipped=%d failed=%d "
                "rate=%.2f rec/s eta=%.0fs",
                i + 1, len(targets), fetched, skipped, failed,
                rate, eta_sec,
            )

    save_cache(args.output, cache)
    elapsed = time.time() - started
    logging.info(
        "Done in %.1fs. fetched=%d skipped=%d failed=%d  cache=%d entries -> %s",
        elapsed, fetched, skipped, failed, len(cache), args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())