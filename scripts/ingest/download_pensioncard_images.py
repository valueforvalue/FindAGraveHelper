"""Download pension card images for the red-ink OCR pilot.

For each pensioner in the sample-50 set, this script:
1. Calls the Digital Prairie singleitem API for the pensioncard_id
   to discover the actual IIIF page IDs (since compound objects
   like two-sided postcards have pages at different IDs than
   the parent pensioncard_id).
2. Downloads each page's full-resolution IIIF tile.
3. Saves files to ``data/pilot/img/<pensioncard_id>__<page_id>.jpg``.

For two-sided cards this yields two images, e.g.:
    1090__1088.jpg  (Side 1)
    1090__1089.jpg  (Side 2)
For single-page cards it yields one image, e.g.:
    98__98.jpg

This is phase 1 of the red-ink OCR pilot. Phase 2 (OCR + date parsing)
lives in :mod:`scripts.ingest.red_ink_ocr_pilot`. Per the developer,
we deliberately download all images first and then OCR in a separate
pass to keep network and compute stages cleanly separated.

Throttle is 1.25s between fetches (API + IIIF) — Digital Prairie is
static CDN-served with no observed rate limits, but we don't want
to hammer.

Usage:
    python scripts/ingest/download_pensioncard_images.py
    python scripts/ingest/download_pensioncard_images.py --input ok_pensioners_sample_50.json
    python scripts/ingest/download_pensioncard_images.py --refresh
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_INPUT = Path("docs/research/digitalprairie/ok_pensioners.json")
DEFAULT_OUT_DIR = Path("data/cards/img")
PENSIONCARD_API = (
    "https://digitalprairie.ok.gov/digital/api/singleitem/"
    "collection/pensioncard/id/{id}"
)
THROTTLE_SECONDS = 1.0
UA = "Mozilla/5.0 (FindAGraveHelper; red-ink-ocr)"


def http_get(url: str, timeout: int = 30) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        logging.warning("GET failed url=%s err=%s", url, e)
        return None


def resolve_pages(pcid: int) -> list[int]:
    """Call the singleitem API to find the actual IIIF page IDs.

    Returns:
        list[int]: the page IDs that have working IIIF tiles.
            - Single-page items: [pcid]
            - Compound items (e.g. two-sided postcards): [pageptr_1,
              pageptr_2, ...] in canonical order.

    See :mod:`scripts.ingest.fetch_pensioncard_pages` for the same
    page-resolution logic in a different shape.
    """
    body = http_get(PENSIONCARD_API.format(id=pcid))
    if not body:
        return []
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as e:
        logging.warning("API json parse failed pcid=%d err=%s", pcid, e)
        return []
    pages = (data.get("objectInfo") or {}).get("page") or []
    pageptrs = []
    for p in pages:
        ptr = p.get("pageptr")
        if ptr:
            try:
                pageptrs.append(int(ptr))
            except (TypeError, ValueError):
                pass
    if pageptrs:
        return pageptrs
    # Single-page fallback: imageUri exists means the parent pcid
    # itself is the IIIF page. Check for the marker fields.
    if data.get("imageUri") or data.get("iiifInfoUri"):
        return [pcid]
    return []


def iiif_url(page_id: int) -> str:
    return (f"https://digitalprairie.ok.gov/iiif/2/pensioncard:{page_id}"
            f"/full/full/0/default.jpg")


def fetch_tile(page_id: int, dest: Path, refresh: bool) -> tuple[bool, int]:
    if dest.exists() and not refresh:
        return True, 200
    data = http_get(iiif_url(page_id))
    if data is None:
        return False, 0
    dest.write_bytes(data)
    return True, 200


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--throttle", type=float, default=THROTTLE_SECONDS)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    summary = {
        "ok_pages": 0,
        "fail_pages": 0,
        "skip_pages": 0,
        "cards_with_no_pages": 0,
        "cards": [],
    }
    started = time.time()
    for i, row in enumerate(rows, 1):
        pcid = row.get("pensioncard_id")
        pensioner_id = row.get("id")
        if not pcid:
            summary["cards"].append({
                "pensioner_id": pensioner_id,
                "pensioncard_id": None,
                "status": "missing-pensioncard-id",
                "pages": [],
            })
            continue
        page_ids = resolve_pages(pcid)
        if not page_ids:
            summary["cards_with_no_pages"] += 1
            summary["cards"].append({
                "pensioner_id": pensioner_id,
                "pensioncard_id": pcid,
                "status": "api-no-pages",
                "pages": [],
            })
            logging.info("[%d/%d] no pages pcid=%s", i, len(rows), pcid)
            time.sleep(args.throttle)
            continue
        card_record = {
            "pensioner_id": pensioner_id,
            "pensioncard_id": pcid,
            "page_ids": page_ids,
            "pages": [],
        }
        for pid in page_ids:
            dest = args.out / f"{pcid}__{pid}.jpg"
            existed_before = dest.exists() and not args.refresh
            ok, status = fetch_tile(pid, dest, args.refresh)
            page_status = "ok" if ok else f"http-{status}"
            card_record["pages"].append({
                "page_id": pid,
                "path": str(dest.relative_to(args.out.parent)),
                "status": page_status,
                "bytes": dest.stat().st_size if dest.exists() else 0,
            })
            if ok and existed_before:
                summary["skip_pages"] += 1
            elif ok:
                summary["ok_pages"] += 1
            else:
                summary["fail_pages"] += 1
            logging.info("[%d/%d] pcid=%s page=%s %s bytes=%s",
                         i, len(rows), pcid, pid,
                         page_status,
                         dest.stat().st_size if dest.exists() else 0)
            time.sleep(args.throttle)
        summary["cards"].append(card_record)

    elapsed = time.time() - started
    summary["elapsed_seconds"] = round(elapsed, 2)
    out_meta = args.out.parent / "download_summary.json"
    out_meta.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logging.info(
        "done pages ok=%d skip=%d fail=%d cards_no_pages=%d elapsed=%.1fs -> %s",
        summary["ok_pages"], summary["skip_pages"], summary["fail_pages"],
        summary["cards_with_no_pages"], elapsed, out_meta,
    )
    return 0 if summary["fail_pages"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())