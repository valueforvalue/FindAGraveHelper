"""Download the original Confederate pension APPLICATION images.

Each row in ``docs/research/digitalprairie/ok_pensioners.json`` carries
two distinct Digital Prairie items:

  * ``id`` / ``iiif_url``               — the **application** (the
    long-form pension request form, sometimes multi-page). Single page
    in practice (verified 2026-07-29: ``objectInfo.page`` is empty for
    pensions:*, every id points to a single IIIF tile).

  * ``pensioncard_id`` / ``pensioncard_iiif_url`` — the 3x5 pension
    index card summarizing the pension. Downloaded separately by
    :mod:`scripts.ingest.download_pensioncard_images`.

This script fetches every pensioner's application tile and writes it
to ``data/cards/applications/<pensioner_id>.jpg``. Applications
without a corresponding pension card (151 orphans routed to the
"_" letter bucket in the viewer) are included too — they still have
``id`` + ``iiif_url`` in the source data.

Throttle is 0.25s. Digital Prairie is a static CDN with no observed
rate limits (the 2.5s FaG throttle does not apply here), but we keep
a courtesy gap. Unlike FaG, no Playwright + stealth needed — plain
``urllib.request`` is correct (matches ``download_pensioncard_images.py``).

Resume-safe: skips records whose destination file already exists and
is non-empty. Pass ``--refresh`` to force re-download.

404s (some pensioners have no application record, e.g. id=4 verified
2026-07-29) are logged and counted as "missing-source" rather than
treated as failures — they don't block the rest of the run.

Usage:
    python scripts/ingest/download_application_images.py
    python scripts/ingest/download_application_images.py --refresh
    python scripts/ingest/download_application_images.py --limit 100
    python scripts/ingest/download_application_images.py --throttle 0.5
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_INPUT = Path("docs/research/digitalprairie/ok_pensioners.json")
DEFAULT_OUT_DIR = Path("data/cards/applications")
DEFAULT_SUMMARY = Path("data/cards/download_summary_applications.json")

THROTTLE_SECONDS = 0.25
UA = "Mozilla/5.0 (FindAGraveHelper; applications-download)"
REQUEST_TIMEOUT = 30


def http_get(url: str, timeout: int = REQUEST_TIMEOUT) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logging.info("GET 404 url=%s", url)
            return None
        logging.warning("GET failed url=%s err=%s", url, e)
        return None
    except Exception as e:
        logging.warning("GET failed url=%s err=%s", url, e)
        return None


def iiif_url(pensioner_id: int) -> str:
    """Direct IIIF URL for one pensioner application tile.

    The ``iiif_url`` field in ok_pensioners.json already points at the
    default-quality tile; we re-derive the same URL here so the
    downloader doesn't need the source JSON in memory per record.
    """
    return (f"https://digitalprairie.ok.gov/iiif/2/pensions:{pensioner_id}"
            f"/full/full/0/default.jpg")


def fetch_one(pensioner_id: int, dest: Path,
              refresh: bool) -> tuple[str, int]:
    """Download one application tile.

    Returns ``(status, bytes_written)`` where status is one of:
      - "skip-already-exists"  (file present + non-empty + not refresh)
      - "ok"                   (newly downloaded)
      - "http-404"             (no application record on digitalprairie)
      - "fetch-failed"         (network/parse error)
      - "empty-response"       (200 OK but zero bytes — treat as bad)
    """
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return "skip-already-exists", dest.stat().st_size
    data = http_get(iiif_url(pensioner_id))
    if data is None:
        return "http-404", 0
    if len(data) == 0:
        return "empty-response", 0
    dest.write_bytes(data)
    return "ok", len(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                    help="source pensioners JSON")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR,
                    help="output directory for application jpgs")
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY,
                    help="download-summary sidecar JSON path")
    ap.add_argument("--throttle", type=float, default=THROTTLE_SECONDS,
                    help="seconds between fetches (default 0.25)")
    ap.add_argument("--refresh", action="store_true",
                    help="re-download even if dest file exists")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N records (for dry-runs)")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[: args.limit]
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("applications")

    summary = {
        "ok": 0,
        "skip": 0,
        "missing_source": 0,   # 404 from digitalprairie
        "fetch_failed": 0,      # network/timeout/parse error
        "empty_response": 0,
        "records": [],
    }
    started = time.time()
    last_heartbeat = started
    last_flush = started

    for i, row in enumerate(rows, 1):
        pensioner_id = row.get("id")
        pensioncard_id = row.get("pensioncard_id")
        if not pensioner_id:
            summary["records"].append({
                "pensioner_id": None,
                "status": "missing-id",
            })
            continue
        dest = args.out / f"{pensioner_id}.jpg"
        status, nbytes = fetch_one(pensioner_id, dest, args.refresh)
        if status == "ok":
            summary["ok"] += 1
        elif status == "skip-already-exists":
            summary["skip"] += 1
        elif status == "http-404":
            summary["missing_source"] += 1
        elif status == "empty-response":
            summary["empty_response"] += 1
        else:
            summary["fetch_failed"] += 1
        summary["records"].append({
            "pensioner_id": pensioner_id,
            "pensioncard_id": pensioncard_id,
            "path": str(dest.relative_to(args.out.parent)),
            "status": status,
            "bytes": nbytes,
        })
        log.info("[%d/%d] id=%s pcid=%s %s bytes=%s",
                 i, len(rows), pensioner_id, pensioncard_id, status, nbytes)

        # Throttle every iteration (including 404s, to avoid hammering)
        time.sleep(args.throttle)

        # Heartbeat every 5 min (same cadence as
        # download_pensioncard_images.py — see L3-adjacent commentary)
        now = time.time()
        if now - last_heartbeat > 300:
            elapsed_min = (now - started) / 60
            log.info(
                "heartbeat: i=%d/%d ok=%d skip=%d miss=%d fail=%d "
                "empty=%d elapsed=%.1fmin",
                i, len(rows),
                summary["ok"], summary["skip"],
                summary["missing_source"], summary["fetch_failed"],
                summary["empty_response"], elapsed_min,
            )
            last_heartbeat = now

        # Per-record flush of summary (cheap; lets external monitors
        # tail progress). Same pattern as the pensioncard downloader.
        if i % 100 == 0 or i == len(rows):
            summary["elapsed_seconds"] = round(now - started, 2)
            args.summary.write_text(
                json.dumps(summary, indent=2),
                encoding="utf-8",
            )
            last_flush = now

    elapsed = time.time() - started
    summary["elapsed_seconds"] = round(elapsed, 2)
    args.summary.write_text(json.dumps(summary, indent=2),
                            encoding="utf-8")
    log.info(
        "done: ok=%d skip=%d miss=%d fail=%d empty=%d elapsed=%.1fs -> %s",
        summary["ok"], summary["skip"], summary["missing_source"],
        summary["fetch_failed"], summary["empty_response"],
        elapsed, args.summary,
    )
    # Non-zero exit only on actual fetch failures (404s are
    # expected and not a run failure).
    return 0 if summary["fetch_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())