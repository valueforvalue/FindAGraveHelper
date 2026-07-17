"""J13: enrich pensioner records with birth/death years from dixiedata.

The local OK Confederate pensioner records
(docs/research/digitalprairie/ok_pensioners.json) have ZERO birth
or death years — only pension-application metadata. That's the
reason impossible-date candidates leak into the FaG search
results: 79% of candidates in the test batch had death_years
outside the ACW window.

The user has a parallel SQLite database of Confederate veterans
(C:/development/dixiedata/dixiedata.db, or the .ddbak backup
zip) with `death_year` and `birth_date` for ~660 OK vets,
including Robert W. Adair (TDM65-00526, 1835-1927) — the exact
match that the test batch already saw in FaG candidates.

This module joins the two sources:

  - Match key: (last_name, first_initial) — strict enough to
    avoid wrong matches for common names, loose enough that
    "R. W. Adair" -> "Robert William Adair" succeeds (R is the
    initial).

  - Output: each pensioner dict gets ._dixie_match = {...}
    with birth_year + death_year when found. The downstream
    pipeline (search_one_pensioner in scripts/fag/search.py)
    already reads local._death_year from the local dict, so
    setting these fields on the pensioner object itself is
    enough to make the score_candidate death-year component
    start contributing.

CLI:
  python -m scripts.enrich.dixiedata_dates \\
      --input docs/research/digitalprairie/ok_pensioners.json \\
      --dixiedata C:/development/dixiedata/dixiedata.db \\
      [--dixiedata-zip-backup C:/development/dixiedata/dixiedata-backup-LATEST.ddbak] \\
      --output docs/research/digitalprairie/ok_pensioners.with_dates.json \\
      [--report docs/research/dixiedata/enrich_report.json]

When the dixiedata DB or backup is missing, the script returns
the input list unchanged (with no dates added) and exits 0.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import zipfile
from pathlib import Path


log = logging.getLogger("enrich.dixiedata_dates")


def _load_dixiedata_from_db(db_path: Path) -> dict:
    """Return a {(last_name, first_initial): {"birth_year": ..., "death_year": ...}}
    index from the dixiedata SQLite database.

    Only soldiers with first_name + last_name + at least one of
    (death_year in ACW window, non-empty birth_date in ACW window)
    are included. Rows with impossible dates (e.g. dy < by, or
    dates outside [1800, 1950]) are skipped — dixiedata has known
    data-quality issues (e.g. one row has by=1933, dy=1926).
    """
    if not db_path.exists():
        return {}
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    idx: dict = {}
    cur.execute(
        "SELECT first_name, last_name, death_year, birth_date "
        "FROM soldiers "
        "WHERE first_name IS NOT NULL AND last_name IS NOT NULL "
        "AND (death_year > 0 OR (birth_date IS NOT NULL AND birth_date != ''))"
    )
    for r in cur.fetchall():
        first = (r["first_name"] or "").strip().upper()
        last = (r["last_name"] or "").strip().upper()
        if not first or not last:
            continue
        initial = first[0]
        # Birth dates in dixiedata are "MM/DD/YYYY" or "00/00/YYYY".
        # Pull the year; the MM=00 case is a known year-only record.
        by_raw = (r["birth_date"] or "").strip()
        by = ""
        if by_raw and by_raw != "00/00/0000":
            # Take the last 4 chars as the year (MM/DD/YYYY format)
            if len(by_raw) >= 4 and by_raw[-4:].isdigit():
                by = by_raw[-4:]
        dy = r["death_year"] if r["death_year"] and r["death_year"] > 0 else ""
        # Validate: skip impossible dates
        try:
            by_i = int(by) if by else None
            dy_i = int(dy) if dy else None
        except ValueError:
            continue
        if by_i is not None and (by_i < 1800 or by_i > 1950):
            by_i = None
            by = ""
        if dy_i is not None and (dy_i < 1800 or dy_i > 1950):
            dy_i = None
            dy = ""
        if by_i and dy_i and by_i >= dy_i:
            # born after death; skip both as unreliable
            continue
        rec = {}
        if by:
            rec["birth_year"] = str(by)
        if dy:
            rec["death_year"] = str(dy)
        if not rec:
            continue
        # Don't overwrite a better match
        key = (last, initial)
        existing = idx.get(key)
        if existing is None or (
            sum(1 for v in rec.values() if v) > sum(1 for v in existing.values() if v)
        ):
            idx[key] = rec
    con.close()
    return idx


def _load_dixiedata_from_zip(zip_path: Path | str) -> dict:
    """Extract data/dixiedata.db from a .ddbak zip backup, then
    load the soldiers index. Returns {} if extraction fails or
    the embedded file is empty.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        return {}
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            log.info("dixiedata zip has %d members; first 5: %s", len(names), names[:5])
            db_member = next((n for n in names if n.endswith("data/dixiedata.db")), None)
            if not db_member:
                log.warning("dixiedata zip has no data/dixiedata.db entry")
                return {}
            extract_root = Path("/tmp/dixiedata_extract") / zip_path.stem
            if extract_root.exists():
                import shutil
                shutil.rmtree(extract_root)
            zipfile.ZipFile(zip_path).extract(db_member, extract_root)
            db_path = extract_root / db_member
            log.info("extracted dixiedata DB to %s (size %d)", db_path, db_path.stat().st_size)
            return _load_dixiedata_from_db(db_path)
    except Exception as e:
        log.warning("dixiedata .ddbak extraction failed: %s", e)
        return {}


def load_dixiedata_index(
    db_path: Path | None = None,
    zip_path: Path | None = None,
    sidecar: Path | None = None,
) -> dict:
    """Load the (last, first_initial) -> {birth_year, death_year}
    index from dixiedata. Tries sources in this order:
      1. sidecar JSON file (committed; fast, no DB needed)
      2. live DB (sqlite file)
      3. .ddbak zip backup (fallback when DB path is missing)

    Returns {} if nothing is available.
    """
    if sidecar:
        sidecar = Path(sidecar)
        if not sidecar.exists():
            log.info("sidecar %s not found; trying other sources", sidecar)
        else:
            try:
                raw = json.loads(sidecar.read_text(encoding="utf-8"))
                # Keys are 'LAST|initial' strings; convert to tuples
                idx = {tuple(k.split("|", 1)): v for k, v in raw.items()}
                if idx:
                    log.info(
                        "loaded %d rows from sidecar %s", len(idx), sidecar
                    )
                    return idx
            except (json.JSONDecodeError, OSError) as e:
                log.warning("sidecar load failed: %s; trying other sources", e)
    idx = _load_dixiedata_from_db(db_path) if db_path else {}
    if idx:
        return idx
    if zip_path:
        idx = _load_dixiedata_from_zip(zip_path)
    return idx


def _normalize_for_match(s: str) -> str:
    """Uppercase + strip for name matching. Strips trailing periods
    ('R.' -> 'R') so 'R. W. Adair' -> first_initial 'R' matches
    'Robert William Adair' -> 'R'.
    """
    return s.strip().rstrip(".").upper()


def enrich_pensioner_dates(
    pensioners: list[dict],
    dixi_index: dict | None = None,
    *,
    dixi_db: Path | None = None,
    dixi_zip: Path | None = None,
    dixi_sidecar: Path | None = None,
) -> list[dict]:
    """Add birth_year / death_year to each pensioner where the
    dixiedata join succeeds.

    Args:
        pensioners: list of pensioner dicts (mutated in place
            AND returned).
        dixi_index: optional pre-loaded index. If None, the
            load_dixiedata_index helper is called with dixi_db /
            dixi_zip / dixi_sidecar.
        dixi_db, dixi_zip, dixi_sidecar: alternative sources
            when dixi_index is None. Sidecar wins if present.

    Returns:
        Same list with .birth_year / .death_year populated where
        the join succeeded. Pensioners with no match are
        unchanged. A summary is logged at INFO.
    """
    if dixi_index is None:
        dixi_index = load_dixiedata_index(dixi_db, dixi_zip, dixi_sidecar)
    if not dixi_index:
        log.info(
            "dixiedata index is empty (no DB or zip found); "
            "returning pensioners unchanged."
        )
        return pensioners
    matched = 0
    for p in pensioners:
        last = _normalize_for_match(p.get("last_name", ""))
        first = _normalize_for_match(p.get("first_name", ""))
        if not last or not first:
            continue
        rec = dixi_index.get((last, first[0]))
        if rec is None:
            continue
        if not p.get("birth_year") and "birth_year" in rec:
            p["birth_year"] = rec["birth_year"]
        if not p.get("death_year") and "death_year" in rec:
            p["death_year"] = rec["death_year"]
        if p.get("birth_year") or p.get("death_year"):
            matched += 1
    log.info("dixiedata enrichment matched %d/%d pensioners", matched, len(pensioners))
    return pensioners


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, required=True,
                   help="ok_pensioners.json (or another uniform JSON list)")
    p.add_argument("--output", type=Path, required=True,
                   help="Path to write the enriched JSON (same schema, with dates added).")
    p.add_argument("--dixiedata", type=Path, default=None,
                   help="Path to the live dixiedata SQLite (dixiedata.db).")
    p.add_argument("--dixiedata-zip-backup", type=Path, default=None,
                   help="Path to a .ddbak zip backup (used as fallback when --dixiedata is missing).")
    p.add_argument("--dixiedata-sidecar", type=Path, default=None,
                   help="Path to a pre-built sidecar JSON file (ok_pensioners.dixiedata_match.json). "
                        "Fast; no DB or .ddbak needed. The committed sidecar is the default "
                        "(see docs/research/digitalprairie/ok_pensioners.dixiedata_match.json).")
    p.add_argument("--report", type=Path, default=None,
                   help="Optional: write a summary report (counts, missing matches) to this path.")
    args = p.parse_args(argv)

    pensioners = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(pensioners, list):
        print("error: input must be a JSON list of pensioner dicts", file=sys.stderr)
        return 1
    matched_before = sum(1 for p in pensioners if p.get("birth_year") or p.get("death_year"))
    enriched = enrich_pensioner_dates(
        pensioners,
        dixi_db=args.dixiedata,
        dixi_zip=args.dixiedata_zip_backup,
        dixi_sidecar=args.dixiedata_sidecar,
    )
    matched_after = sum(1 for p in enriched if p.get("birth_year") or p.get("death_year"))

    args.output.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"enrich complete: {matched_before} already had dates, {matched_after} after enrichment "
        f"(+{matched_after - matched_before} new). Wrote {args.output}"
    )

    if args.report:
        rpt = {
            "total": len(enriched),
            "with_birth_year": sum(1 for p in enriched if p.get("birth_year")),
            "with_death_year": sum(1 for p in enriched if p.get("death_year")),
            "with_either": matched_after,
            "new_matches": matched_after - matched_before,
        }
        args.report.write_text(json.dumps(rpt, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
