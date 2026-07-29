#!/usr/bin/env python3
"""EasyOCR second-pass re-OCR for records that Tesseract missed.

Issue #139 L3 follow-up (2026-07-29). After L0/L1/L2 the audit
still has ~1800 NO_KEYWORD_BUT_DATE findings. Most are soldier
cards where Tesseract failed to OCR the 'Deceased' stamp on the
top-right of the card (the red-ink mask killed the stamp text, or
the stamp was hand-written / faded).

EasyOCR has noticeably better handwriting handling and is more
robust to faded ink than Tesseract. This script runs EasyOCR on
the no-date records from the cached `red_ocr_results.json`,
appends the result to each record's `easy_text` / `easy_text_len`
fields, and re-runs `find_death_date` on the new text to see if
it extracts a death date where Tesseract failed.

Output:
- Updates `data/cards/red_ocr_results.json` IN PLACE (adds
  `easy_text` + `easy_text_len` fields; preserves everything else)
- Recomputes `death_date` if the EasyOCR text + cached Tesseract
  text together yield a parseable date.
- Resume-safe: skips records that already have an `easy_text` field.

Performance:
- CPU-only (no CUDA on this machine). EasyOCR is slow on CPU:
  ~3-8 seconds per image depending on resolution.
- 2087 widow no-date records × ~5s = ~3 hours.
- 2909 soldier no-date records × ~5s = ~4 hours.
- Total full pass: ~7 hours CPU.

Usage:
    python scripts/ingest/easyocr_pass.py --limit 10  # smoke test
    python scripts/ingest/easyocr_pass.py --only-widows  # default
    python scripts/ingest/easyocr_pass.py --include-soldiers  # both
    python scripts/ingest/easyocr_pass.py --refresh  # re-OCR all
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Import the parser functions from the pilot. This is the whole
# point: re-use the existing find_death_date on the new EasyOCR
# text so we can compare apples to apples.
from scripts.ingest.red_ink_ocr_pilot import (  # noqa: E402
    find_death_date,
    DEATH_KEYWORDS,
)


def _is_widow_record(enriched_row: dict) -> bool:
    """Match the widow-detection logic in
    enrich_pensioners_with_death_dates.py:is_widow_card."""
    return bool((enriched_row.get("spouse_name_raw") or "").strip())

DEFAULT_INPUT = Path("data/cards/red_ocr_results.json")
DEFAULT_OUTPUT = Path("data/cards/red_ocr_results.json")
DEFAULT_IMG_DIR = Path("data/cards/img")

THROTTLE_SECONDS = 0.25  # gentle pause; not strictly needed for image OCR


def easyocr_one(reader, img_path: Path) -> str:
    """Run EasyOCR on one image, return concatenated text.

    EasyOCR returns a list of (bbox, text, conf) tuples. We just
    concatenate the text fields with newlines.
    """
    results = reader.readtext(str(img_path), detail=1, paragraph=False)
    lines = []
    for _bbox, text, conf in results:
        if conf >= 0.3:  # ignore very low-confidence noise
            lines.append(text)
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                    help="cached OCR results JSON")
    ap.add_argument("--output", type=Path, default=None,
                    help="output path (default: in-place overwrite of "
                         "--input). For slice runs, ALWAYS pass an "
                         "explicit --output pointing at a sidecar file "
                         "or the canonical red_ocr_results.json will be "
                         "clobbered with the slice contents.")
    ap.add_argument("--in-place", action="store_true",
                    help="allow overwriting --input (canonical file). "
                         "Required when --output is omitted and --input "
                         "is the canonical red_ocr_results.json. "
                         "Intended for production runs only.")
    ap.add_argument("--img-dir", type=Path, default=DEFAULT_IMG_DIR,
                    help="directory containing the card jpegs")
    ap.add_argument("--limit", type=int, default=0,
                    help="process at most N records (smoke test)")
    ap.add_argument("--only-widows", action="store_true", default=True,
                    help="process widow records only (default)")
    ap.add_argument("--include-soldiers", action="store_true",
                    help="include soldier records too (full pass)")
    ap.add_argument("--priority-only", action="store_true",
                    help="only records with empty red_text (highest "
                         "value — the red-ink mask killed the stamp and "
                         "EasyOCR's full-image OCR is the only way to "
                         "recover it). Default off.")
    ap.add_argument("--refresh", action="store_true",
                    help="re-OCR even if easy_text is already present")
    ap.add_argument("--throttle", type=float, default=THROTTLE_SECONDS,
                    help="seconds between images (default 0.25)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("easyocr")

    # Lazy import — only load torch + easyocr if we actually run.
    log.info("loading easyocr reader (first run downloads the model)...")
    import easyocr  # noqa: E402
    t0 = time.time()
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    log.info("easyocr loaded in %.1fs", time.time() - t0)

    log.info("loading %s...", args.input)
    results = json.loads(args.input.read_text(encoding="utf-8"))
    log.info("loaded %d image records", len(results))

    # Output resolution + safety guard.
    # Default behavior: in-place overwrite of --input (the legacy
    # contract). When --input is the canonical file and the loaded
    # record count looks like a slice (< canonical size), refuse to
    # proceed unless --in-place was given. This prevents the
    # 2026-07-29 incident where running the script with --input
    # pointed at a 50-record slice file silently clobbered the
    # 9436-record canonical red_ocr_results.json.
    if args.output is None:
        output_path = args.input
    else:
        output_path = args.output

    if (output_path == DEFAULT_INPUT
            and len(results) < 1000
            and not args.in_place):
        log.error(
            "REFUSING to run: --input resolves to the canonical "
            "%s but only %d records were loaded (looks like a "
            "slice). Pass --output <sidecar.json> or --in-place "
            "to proceed.",
            DEFAULT_INPUT, len(results),
        )
        return 2

    args.output = output_path
    log.info("output -> %s", args.output)

    # Load the enriched sidecar to determine which records are
    # widow cards (we need the spouse_name_raw to run the
    # widow-aware parser).
    enriched_path = _ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners.with_death_dates.json"
    log.info("loading %s for widow detection...", enriched_path.name)
    enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
    enriched_by_pcid = {r.get("pensioncard_id"): r
                        for r in enriched if r.get("pensioncard_id") is not None}

    # Pre-filter: which records to process
    targets: list[dict] = []
    for r in results:
        # Skip if already has easy_text and not refreshing
        if r.get("easy_text") and not args.refresh:
            continue
        # Skip if Tesseract already found a death date (no point
        # in re-OCRing — Tesseract's parse will beat EasyOCR's
        # confidence-adjusted parse on already-extracted text)
        if r.get("death_date") is not None and not args.refresh:
            continue
        # Widow filter
        pcid = r.get("pensioncard_id")
        e = enriched_by_pcid.get(pcid, {})
        is_widow = _is_widow_record(e)
        if args.only_widows and not args.include_soldiers and not is_widow:
            continue
        # Priority filter (highest value: red-text pass returned
        # nothing, so the date is invisible to the red-mask OCR)
        if args.priority_only:
            red_len = len((r.get("red_text") or "").strip())
            if red_len > 0:
                continue
        # Image exists?
        img = args.img_dir / r.get("image", "")
        if not img.exists():
            log.warning("image missing: %s (skipping pcid=%s)",
                        img, pcid)
            continue
        targets.append(r)

    if args.limit:
        targets = targets[: args.limit]
    log.info("will process %d records (refresh=%s, only_widows=%s, include_soldiers=%s)",
             len(targets), args.refresh, args.only_widows, args.include_soldiers)

    started = time.time()
    counts = {
        "ok": 0,
        "fail": 0,
        "new_dates": 0,
        "new_date_widow_soldier_match": 0,
    }
    last_save = started
    last_log = started

    for i, rec in enumerate(targets, 1):
        img_path = args.img_dir / rec["image"]
        pcid = rec.get("pensioncard_id")
        pen = rec.get("pensioner") or {}
        soldier_name = pen.get("last_name") or ""
        e = enriched_by_pcid.get(pcid, {})
        if not soldier_name:
            raw = (pen.get("name_raw") or "").split(",", 1)[0].strip()
            soldier_name = raw

        try:
            text = easyocr_one(reader, img_path)
        except Exception as ex:
            log.warning("easyocr failed for %s: %s", img_path.name, ex)
            counts["fail"] += 1
            time.sleep(args.throttle)
            continue

        rec["easy_text"] = text
        rec["easy_text_len"] = len(text)
        counts["ok"] += 1

        # Try the parser on the EasyOCR text alone.
        easy_parsed, _ = find_death_date(text, soldier_name)
        # And on EasyOCR + cached Tesseract text combined.
        combined = (rec.get("red_text") or "") + " " + \
                   (rec.get("full_text") or "") + " " + text
        combined_parsed, _ = find_death_date(combined, soldier_name)

        new_parsed = combined_parsed or easy_parsed
        if new_parsed and rec.get("death_date") is None:
            # Upgrade the record with a death date
            old = rec.get("death_date")
            rec["death_date"] = {
                "kind": new_parsed["kind"],
                "year": new_parsed["year"],
                "month": new_parsed["month"],
                "day": new_parsed["day"],
                "iso": new_parsed["iso"],
                "match": new_parsed.get("match"),
                "span": new_parsed.get("span"),
                "near_death_keyword": bool(
                    DEATH_KEYWORDS.search(combined)
                ),
                "mentions_soldier_name": bool(
                    soldier_name and soldier_name.lower()
                    in combined[max(0, new_parsed["span"][0] - 30):
                               min(len(combined), new_parsed["span"][1] + 30)].lower()
                ),
            }
            rec["source_pass"] = "easyocr"
            counts["new_dates"] += 1
            if rec["death_date"]["mentions_soldier_name"]:
                counts["new_date_widow_soldier_match"] += 1
        elif new_parsed and rec.get("death_date") and \
             new_parsed["year"] != rec["death_date"].get("year"):
            # Tesseract's parse disagrees with EasyOCR's — log
            # the disagreement for audit. Don't overwrite.
            rec.setdefault("easy_disagreements", []).append({
                "tesseract_year": rec["death_date"].get("year"),
                "easyocr_year": new_parsed["year"],
            })

        time.sleep(args.throttle)

        # Save every 25 records (crash safety)
        now = time.time()
        if now - last_save > 60 or i == len(targets):
            args.output.write_text(
                json.dumps(results, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            last_save = now

        # Heartbeat every 5 min
        if now - last_log > 300:
            elapsed = now - started
            rate = counts["ok"] / max(elapsed, 1)
            eta_s = (len(targets) - i) / max(rate, 0.001)
            log.info(
                "heartbeat: i=%d/%d ok=%d fail=%d new_dates=%d "
                "rate=%.2f/s eta=%.0fs",
                i, len(targets), counts["ok"], counts["fail"],
                counts["new_dates"], rate, eta_s,
            )
            last_log = now
        elif i % 50 == 0:
            elapsed = now - started
            rate = counts["ok"] / max(elapsed, 1)
            log.info("i=%d/%d ok=%d new_dates=%d rate=%.2f/s",
                     i, len(targets), counts["ok"],
                     counts["new_dates"], rate)

    elapsed = time.time() - started
    log.info("done in %.1fs — ok=%d fail=%d new_dates=%d widow_soldier_match=%d",
             elapsed, counts["ok"], counts["fail"], counts["new_dates"],
             counts["new_date_widow_soldier_match"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())