"""Enrich ok_pensioners.json with death dates from red-ink OCR.

Reads ``data/cards/red_ocr_results.json`` (per-image OCR output from
``scripts/ingest/red_ink_ocr_pilot.py``), dedupes per pensioncard_id,
and adds two fields to each pensioner record in
``docs/research/digitalprairie/ok_pensioners.json``:

- ``death_year`` (str): 4-digit year, e.g. "1935". Empty string if
  no candidate. This is the field the blackboard projector reads
  via ``pensioner_data.get("death_year")``.
- ``death_date_iso`` (str): ISO date "YYYY-MM-DD" when full date
  parsed (year-month-day), else just "YYYY", else empty. This is
  the richer per-pensioner death date for human review.

Per-card dedup policy (when a two-sided card yields two dates):
1. Prefer the candidate whose ``near_death_keyword`` flag is True
   (death keyword was found on the card).
2. Prefer ``kind=date`` over ``kind=year-only``.
3. Prefer the earliest year that still falls in range (1865-1940).

Adds only. Does not remove or modify existing fields.

Output:
- ``docs/research/digitalprairie/ok_pensioners.json`` (mutated in
  place).
- ``data/cards/enrichment_report.json`` (per-card summary of what
  was added).

Usage:
    python scripts/ingest/enrich_pensioners_with_death_dates.py
    python scripts/ingest/enrich_pensioners_with_death_dates.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from collections import defaultdict

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_INPUT_JSON = Path(
    "docs/research/digitalprairie/ok_pensioners.json"
)
DEFAULT_OCR_JSON = Path("data/cards/red_ocr_results.json")
# Default output is a SIDE-CAR file, NOT ok_pensioners.json
# itself. This is intentional — the developer wants to review the
# enrichment before merging into the source. Once validated, copy
# sidecar -> source:
#   cp ok_pensioners.with_death_dates.json ok_pensioners.json
DEFAULT_OUT_JSON = Path(
    "docs/research/digitalprairie/ok_pensioners.with_death_dates.json"
)
DEFAULT_REPORT = Path("data/cards/enrichment_report.json")

MIN_YEAR = 1860  # Issue #144: lowered from 1865 to catch Civil War deaths
# Issue #144 follow-up (2026-08-02): raised MAX_YEAR 1940 → 1965
# to match the parser's cap. Earlier 1940 cap silently dropped
# valid 1941-1965 death dates (per the parser's own
# documentation that widow cards legitimately have death dates
# in 1941-1955 — the enrich script was rejecting them).
MAX_YEAR = 1965


def pick_best_per_card(sides: list[dict]) -> dict | None:
    """Pick the best death date from one card's page-sides.

    Returns the chosen info dict (with year/month/day/iso) or None.

    Selection priority (issue #145 — widow vs soldier):
    1. ``mentions_soldier_name=True`` wins. On widow cards the
       soldier's death date is usually in the body prose ("He
       died ... in ...") which mentions his name, while the
       red stamp records the widow's own death. Picking the
       soldier-mentioning candidate is the right call for FaG
       search.
    2. ``near_death_keyword=True``.
    3. ``kind=date`` over year-only.
    4. Earlier year — the soldier typically died before the
       widow (decades gap), so when multiple candidates tie on
       the criteria above, the earlier year is more likely the
       soldier's death.
    """
    candidates = []
    for s in sides:
        d = s.get("death_date")
        if not d:
            continue
        year = d.get("year")
        if not (MIN_YEAR <= year <= MAX_YEAR):
            continue
        candidates.append(d)

    if not candidates:
        return None

    def score(c: dict) -> tuple[int, int, int, int]:
        # Sort ascending — highest tuple wins. Tuple order:
        # mentions_soldier, kw, kind, NEGATED_year (older = better).
        mentions_soldier = 1 if c.get("mentions_soldier_name") else 0
        kw = 1 if c.get("near_death_keyword") else 0
        kind = 1 if c.get("kind") == "date" else 0
        year = c.get("year") or 0
        return (mentions_soldier, kw, kind, -year)

    return max(candidates, key=score)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT_JSON)
    ap.add_argument("--ocr", type=Path, default=DEFAULT_OCR_JSON)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--dry-run", action="store_true",
                    help="compute report only; don't write pensioner JSON")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    rows = json.loads(args.input.read_text(encoding="utf-8"))
    ocr = json.loads(args.ocr.read_text(encoding="utf-8"))

    # Group OCR results by pensioncard_id.
    by_pcid: dict[int, list[dict]] = defaultdict(list)
    for r in ocr:
        pcid = r.get("pensioncard_id")
        if pcid is not None:
            by_pcid[int(pcid)].append(r)

    enriched = 0
    enriched_kw = 0
    enriched_full_date = 0
    skipped = 0
    changed = []
    for row in rows:
        pcid = row.get("pensioncard_id")
        if pcid is None:
            skipped += 1
            continue
        pcid = int(pcid)
        sides = by_pcid.get(pcid, [])
        chosen = pick_best_per_card(sides)
        if chosen is None:
            skipped += 1
            continue
        year = chosen["year"]
        row["death_year"] = str(year)
        # death_date_iso: full date if kind=date, else just year
        if chosen.get("kind") == "date" and chosen.get("month") and chosen.get("day"):
            row["death_date_iso"] = chosen["iso"]
            enriched_full_date += 1
        else:
            row["death_date_iso"] = f"{year:04d}"
        enriched += 1
        if chosen.get("near_death_keyword"):
            enriched_kw += 1
        changed.append({
            "pensioner_id": row.get("id"),
            "pensioncard_id": pcid,
            "name_raw": row.get("name_raw"),
            "is_widow_card": row.get("spouse_name_raw", "").strip() != "",
            "death_year": row["death_year"],
            "death_date_iso": row["death_date_iso"],
            "near_death_keyword": chosen.get("near_death_keyword", False),
            "mentions_soldier_name": chosen.get("mentions_soldier_name", False),
            "source_pass": sides[0].get("source_pass") if sides else None,
        })

    if not args.dry_run:
        args.out.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    args.report.write_text(
        json.dumps({
            "total_pensioners": len(rows),
            "enriched": enriched,
            "enriched_with_death_keyword": enriched_kw,
            "enriched_with_full_date": enriched_full_date,
            "skipped": skipped,
            "changed": changed,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logging.info(
        "enriched=%d (kw=%d, full_date=%d) skipped=%d total=%d -> %s",
        enriched, enriched_kw, enriched_full_date, skipped,
        len(rows), args.report,
    )
    if not args.dry_run:
        logging.info("wrote enriched pensioner JSON to %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())