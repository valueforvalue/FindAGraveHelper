#!/usr/bin/env python3
"""Re-run death-date extraction from cached OCR text only (no re-OCR).

Context: 2026-07-29 issue #139 surfaced 3423 audit findings
(NO_KEYWORD_BUT_DATE, FULL_DATE_BUT_YEAR_ONLY, WIDOW_BUT_NO_DATE,
SUSPECT_MONTH_DAY, etc.). Root causes are mostly parser-side, not
OCR-engine-side:

  - Date regex required whitespace before 4-digit year, missing
    "June 5,1902" cases.
  - Filter window of ±30 chars was too narrow for "came to Oklahoma
    Territory 1912" (~40 chars).
  - MAX_YEAR=1940 rejected legit widow deaths in 1941-1955.
  - No parser for 2-digit-year stamps ("Deceased 1-26-25").
  - No MARRIED_RE / FILED_RE filters — marriage dates and letter
    dates were being picked as deaths.

This script reads the cached `data/cards/red_ocr_results.json`
(9436 image records with `red_text` + `full_text` already done by
the original `red_ink_ocr_pilot.py` run) and re-extracts death
dates using the updated parser logic in
`red_ink_ocr_pilot.py:find_death_date`.

Output:
  - `data/cards/red_ocr_results.json` UPDATED IN PLACE — each
    record's `death_date` field is recomputed. The script
    preserves the existing `red_text` / `full_text` / `context_window`
    / `full_window` so we don't have to re-OCR.
  - `data/cards/red_ocr_summary.json` recomputed from the
    per-image death_date results.
  - The downstream `enrich_pensioners_with_death_dates.py` script
    is then re-run to produce a new sidecar.

Usage:
    python scripts/ingest/re_enrich_from_ocr.py
    python scripts/ingest/re_enrich_from_ocr.py --dry-run
    python scripts/ingest/re_enrich_from_ocr.py --input other_results.json
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

# Import the updated parser functions from the pilot script. This is
# the whole point: the pilot owns the regex/filter logic; this
# script is a thin re-driver over its `find_death_date` + the cached
# OCR text.
from scripts.ingest.red_ink_ocr_pilot import (  # noqa: E402
    find_death_date,
    DEATH_KEYWORDS,
    fuzzy_death_keyword,
)


def _annotate(chosen, src_text, soldier_name):
    """Compute near_death_keyword and mentions_soldier_name for
    the chosen candidate by re-scanning the text source that
    produced it.

    `find_death_date` returns a candidate dict WITHOUT these
    fields; they're added by `process_image` for the original
    red/full path. The re-enrich driver picks from three text
    sources (red, full, easy), so it must compute the
    annotations from the picked source's text.
    """
    if chosen is None:
        return False, False
    if not src_text:
        return False, False
    has_kw = fuzzy_death_keyword(src_text)
    name_lower = soldier_name.strip().lower() if soldier_name else ""
    has_name = bool(name_lower and name_lower in src_text.lower())
    return has_kw, has_name

DEFAULT_INPUT = Path("data/cards/red_ocr_results.json")
DEFAULT_OUTPUT = Path("data/cards/red_ocr_results.json")
DEFAULT_SUMMARY = Path("data/cards/red_ocr_summary.json")


def _score_candidate(parsed):
    """Pick the best death_date among red/full/easy parsed dicts.

    Score (ascending tuple, lower is better):
      - prefer full-date over year-only
      - prefer near_death_keyword over not
      - prefer mentions_soldier_name over not
    Returns a sort key tuple; the caller's `min()` picks the best.
    """
    if parsed is None:
        return (1, 1, 1, 1)
    kind_rank = 0 if parsed.get("kind") == "date" else 1
    kw_rank = 0 if parsed.get("near_death_keyword") else 1
    name_rank = 0 if parsed.get("mentions_soldier_name") else 1
    return (kind_rank, kw_rank, name_rank, 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                    help="cached OCR results JSON (re-enriches in place by default)")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                    help="output path (default: overwrite --input)")
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY,
                    help="red_ocr_summary.json output path")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute new death_date values but don't write")
    ap.add_argument("--limit", type=int, default=0,
                    help="process only the first N records (for smoke tests)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("re_enrich")

    log.info("loading %s...", args.input)
    results = json.loads(args.input.read_text(encoding="utf-8"))
    log.info("loaded %d image records", len(results))

    if args.limit:
        results = results[: args.limit]

    started = time.time()
    counts = {
        "total": len(results),
        "with_red_text": 0,
        "with_full_text": 0,
        "with_easy_text": 0,
        "red_parsed": 0,
        "full_parsed": 0,
        "easy_parsed": 0,
        "red_picked": 0,
        "full_picked": 0,
        "easy_picked": 0,
        "no_date": 0,
        "year_only": 0,
        "full_date": 0,
    }

    # For "did this record's death_date CHANGE?" accounting
    changed = 0

    for rec in results:
        red_text = rec.get("red_text", "") or ""
        full_text = rec.get("full_text", "") or ""
        easy_text = rec.get("easy_text", "") or ""
        if red_text:
            counts["with_red_text"] += 1
        if full_text:
            counts["with_full_text"] += 1
        if easy_text:
            counts["with_easy_text"] += 1

        # Re-extract from the cached red text and the cached full
        # text. We pass the soldier name from the record's
        # `pensioner` block so widow-aware scoring still works.
        soldier_name = ""
        pen = rec.get("pensioner") or {}
        last = pen.get("last_name") or ""
        if last:
            soldier_name = last
        # Fallback: derive from name_raw
        if not soldier_name:
            raw = pen.get("name_raw", "") or ""
            if "," in raw:
                soldier_name = raw.split(",", 1)[0].strip()

        old_death = rec.get("death_date")
        old_source_pass = rec.get("source_pass")
        red_parsed, red_window = find_death_date(red_text, soldier_name)
        full_parsed, full_window = find_death_date(full_text, soldier_name)
        easy_parsed, easy_window = find_death_date(easy_text, soldier_name)
        if red_parsed:
            counts["red_parsed"] += 1
        if full_parsed:
            counts["full_parsed"] += 1
        if easy_parsed:
            counts["easy_parsed"] += 1

        # Pick the best candidate across all three text sources.
        # Issue #139 follow-up: easy_text was previously ignored,
        # leaving the L3 EasyOCR pass results stale. We now score
        # by (full-date > year-only) x (near_death_keyword) x
        # (mentions_soldier_name) and tie-break by source order
        # (red > full > easy). This means easy_text can PROMOTE
        # a record that red/full couldn't parse, but won't
        # OVERRIDE a red/full death date that's already correct.
        candidates = [
            ("red", red_parsed),
            ("full", full_parsed),
            ("easy", easy_parsed),
        ]
        cands = [(src, c) for src, c in candidates if c is not None]
        if cands:
            cands.sort(key=lambda sc: _score_candidate(sc[1]))
            chosen_src, chosen = cands[0]

            
            src_text = {
                "red": red_text, "full": full_text, "easy": easy_text
            }[chosen_src]
            has_kw, has_name = _annotate(
                chosen, src_text, soldier_name
            )

            new_death = {
                "kind": chosen["kind"],
                "year": chosen["year"],
                "month": chosen["month"],
                "day": chosen["day"],
                "iso": chosen["iso"],
                "match": chosen.get("match"),
                "near_death_keyword": has_kw,
                "mentions_soldier_name": has_name,
            }
            rec["death_date"] = new_death
            # Update source_pass to reflect which text source
            # the picked candidate came from. The downstream
            # audit uses this to flag PASS_RED_BUT_LOW_TEXT etc.
            rec["source_pass"] = (
                "red" if chosen_src == "red"
                else "full-fallback" if chosen_src == "full"
                else "easyocr"
            )
            if new_death["kind"] == "date":
                counts["full_date"] += 1
            else:
                counts["year_only"] += 1
            if chosen_src == "red":
                counts["red_picked"] += 1
            elif chosen_src == "full":
                counts["full_picked"] += 1
            else:
                counts["easy_picked"] += 1
            if old_death != new_death or old_source_pass != rec["source_pass"]:
                changed += 1
        else:
            rec["death_date"] = None
            rec["source_pass"] = None
            counts["no_date"] += 1
            if old_death is not None:
                changed += 1

    elapsed = time.time() - started
    log.info("re-extracted %d records in %.1fs", len(results), elapsed)
    log.info("  with red text:     %d", counts["with_red_text"])
    log.info("  with full text:    %d", counts["with_full_text"])
    log.info("  with easy text:    %d", counts["with_easy_text"])
    log.info("  red-pass parsed:   %d", counts["red_parsed"])
    log.info("  full-text parsed:  %d", counts["full_parsed"])
    log.info("  easy-text parsed:  %d", counts["easy_parsed"])
    log.info("  red-pass picked:   %d", counts["red_picked"])
    log.info("  full-text picked:  %d", counts["full_picked"])
    log.info("  easy-pass picked:  %d", counts["easy_picked"])
    log.info("  year-only:         %d", counts["year_only"])
    log.info("  full date:         %d", counts["full_date"])
    log.info("  no date:           %d", counts["no_date"])
    log.info("  changed from old:  %d", changed)

    if args.dry_run:
        log.info("dry-run: not writing")
        return 0

    # Write the updated results. Atomic via .partial so a crash
    # mid-write doesn't corrupt the OCR cache.
    out_partial = args.output.with_suffix(args.output.suffix + ".partial")
    out_partial.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    out_partial.replace(args.output)
    log.info("wrote %s", args.output)

    # Recompute the summary
    summary = {
        "total_images": len(results),
        "with_red_text": counts["with_red_text"],
        "with_full_text": counts["with_full_text"],
        "with_easy_text": counts["with_easy_text"],
        "red_parsed": counts["red_parsed"],
        "full_parsed": counts["full_parsed"],
        "easy_parsed": counts["easy_parsed"],
        "red_picked": counts["red_picked"],
        "full_picked": counts["full_picked"],
        "easy_picked": counts["easy_picked"],
        "with_death_date": (
            counts["red_picked"] + counts["full_picked"]
            + counts["easy_picked"]
        ),
        "year_only": counts["year_only"],
        "full_date": counts["full_date"],
        "no_date": counts["no_date"],
        "elapsed_seconds": round(elapsed, 2),
    }
    args.summary.write_text(json.dumps(summary, indent=2),
                            encoding="utf-8")
    log.info("wrote %s", args.summary)

    log.info("next step: python scripts/ingest/enrich_pensioners_with_death_dates.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())