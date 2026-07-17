"""J14: post-pipeline comparison of FaG results against dixiedata.

The user keeps a separate SQLite research database (C:/development/
dixiedata/dixiedata.db or its .ddbak backup) where they've
already paired ~611 Confederate vets with verified Find a Grave
memorials. We're not auto-enriching the input (that path was
removed in J14; auto-join was too error-prone), but AFTER the
pipeline runs we can:

  1. Read this run's output/test-batch-25/results.jsonl
  2. Read the dixiedata DB or .ddbak backup (READ ONLY; no
     writes)
  3. For each pensioner record, check: does the top FaG
     candidate (highest-ranked by score_candidate) match
     a memorial_id already tracked in dixiedata?
  4. If yes, write `dd_match: {matched: True, dd_soldier: ...,
     dd_memorial_id: ..., dd_record_link: ...}` to each pensioner's
     results.jsonl record.
  5. Mirror the dd_match sidecar to `output/<runname>/dd_match.json`
     for view.html to read alongside results.jsonl.

This way the reviewer sees a "DD tracked" badge on pensioners
they've already documented in dixiedata and can filter them out
for a fast triage pass. The pipeline NEVER touches the input
data or DD itself.

CLI usage:
  python -m scripts.cgr.dixiedata_match \\
      --results output/<runname>/results.jsonl \\
      --dd-zip-backup C:/development/dixiedata/dixiedata-backup-LATEST.ddbak \\
      [--dd-db /path/to/dixiedata.db]   # optional faster path if live DB exists \\
      [--dd-sidecar <path.json>]        # pre-built cache; faster \\
      [--top-n 1]                       # only check top N candidates (default 1) \\
      [--match-strength weak|strict]    # see below (default: weak)

Match-strength semantics:
  weak  (default): match if top candidate's memorial_id appears
         anywhere in this soldier's DD FaG records (any of the 3
         storage conventions).
  strict: match AND the top candidate's slug also matches the DD
         slug (so we know it's not a coincidence / different person
         who shares a memorial after merge).

The output is a single dd_match.json sidecar that view.html
embeds alongside results.jsonl.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import zipfile
from pathlib import Path


log = logging.getLogger("cgr.dixiedata_match")


# ============================================================
# Memorial-ID extraction from DD records
# ============================================================
# The dixiedata `records` table stores FaG memorial IDs in 3
# different conventions:
#   (1) app_id = "FaG ID: 9121410"
#   (2) app_id = "9121410"   (bare integer)
#   (3) details = "https://www.findagrave.com/memorial/9121410/jane-doe"
# We normalize all three to the same integer form so a memorial
# can be looked up regardless of how DD chose to record it.
_FAG_ID_FROM_APP_ID = re.compile(r"(?:FaG\s*ID:\s*)?(\d{6,9})")
_FAG_ID_FROM_URL = re.compile(r"/memorial/(\d{6,9})/")


def _extract_fag_ids(record: dict) -> set:
    """Pull every memorial-ID we can find in a single DD record.
    Returns a set of integer memorial IDs."""
    ids = set()
    app_id = (record.get("app_id") or "").strip()
    details = (record.get("details") or "").strip()
    # Both fields may carry the URL too (e.g. Ancestry+Fold3
    # records sometimes do).
    for s in (app_id, details):
        if not s:
            continue
        for m in _FAG_ID_FROM_APP_ID.finditer(s):
            ids.add(int(m.group(1)))
        for m in _FAG_ID_FROM_URL.finditer(s):
            ids.add(int(m.group(1)))
    return ids


# ============================================================
# dixiedata loaders (READ ONLY)
# ============================================================
def _load_dd_from_db(db_path: Path) -> dict:
    """Return: {soldier_key: [{memorial_id, slug, ...}]} index
    where soldier_key = (last_name_up, first_initial_up).

    Only soldiers with at least one FaG-tagged record appear in
    the index. Multiple FaG records per soldier (e.g. one as
    Find a Grave, one as fold3) all get included.
    """
    if not db_path.exists():
        return {}
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    idx: dict = {}
    cur.execute(
        "SELECT s.first_name, s.last_name, r.app_id, r.details, r.record_type "
        "FROM soldiers s "
        "JOIN records r ON r.soldier_id = s.id "
        "WHERE r.record_type LIKE '%Find a Grave%' "
        "   OR r.app_id LIKE 'FaG%' "
        "   OR r.details LIKE '%findagrave.com/memorial/%'"
    )
    for r in cur.fetchall():
        first = (r["first_name"] or "").strip().rstrip(".").upper()
        last = (r["last_name"] or "").strip().rstrip(".").upper()
        if not first or not last:
            continue
        ids = _extract_fag_ids({"app_id": r["app_id"], "details": r["details"]})
        if not ids:
            continue
        key = (last, first[0])
        idx.setdefault(key, []).append({
            "first_name": first,
            "last_name": last,
            "memorial_ids": sorted(ids),
            "source_record_type": r["record_type"],
            "dd_details_url": _extract_first_url(r["details"] or ""),
        })
    con.close()
    return idx


def _extract_first_url(s: str) -> str:
    """Return the first http(s) URL in s, or empty string."""
    m = re.search(r"https?://\S+", s)
    return m.group(0) if m else ""


def _load_dd_from_zip(zip_path: Path | str) -> dict:
    zip_path = Path(zip_path)
    if not zip_path.exists():
        return {}
    try:
        with zipfile.ZipFile(zip_path) as z:
            db_member = next(
                (n for n in z.namelist() if n.endswith("data/dixiedata.db")), None
            )
            if not db_member:
                return {}
            extract_root = Path("/tmp/dixiedata_dd_match_extract") / zip_path.stem
            if extract_root.exists():
                import shutil
                shutil.rmtree(extract_root)
            zipfile.ZipFile(zip_path).extract(db_member, extract_root)
            db_path = extract_root / db_member
            return _load_dd_from_db(db_path)
    except Exception as e:
        log.warning("dixiedata .ddbak extraction failed: %s", e)
        return {}


def load_dd_index(
    db_path: Path | str | None = None,
    zip_path: Path | str | None = None,
) -> dict:
    """Load the (last, initial) -> [FaG record dict] index from
    dixiedata. Tries the live DB first; falls back to .ddbak.
    Returns {} when neither is available.
    """
    # Guard against Path("") -> WindowsPath(".") confusing .exists()
    db_path_p = Path(db_path) if db_path else None
    zip_path_p = Path(zip_path) if zip_path else None
    if db_path_p and db_path_p.exists() and db_path_p.is_file():
        idx = _load_dd_from_db(db_path_p)
        if idx:
            return idx
    if zip_path_p and zip_path_p.exists() and zip_path_p.is_file():
        return _load_dd_from_zip(zip_path_p)
    return {}


# ============================================================
# Per-pensioner match
# ============================================================
def _pensioner_key(p: dict) -> tuple:
    """Match key for a pensioner dict: (last_name, first_initial)."""
    last = (p.get("pensioner_last") or p.get("last_name") or "").strip().rstrip(".").upper()
    first = (p.get("pensioner_first") or p.get("first_name") or "").strip().rstrip(".").upper()
    if not last or not first:
        return ()
    return (last, first[0])


def _match_pensioner_to_dd(
    pensioner: dict,
    dd_index: dict,
    top_n: int = 1,
    match_strength: str = "weak",
) -> dict | None:
    """Compare a pensioner's top FaG candidates against DD's
    tracked memorials. Returns a dd_match dict if matched, else None.

    Args:
        pensioner: results.jsonl record (must have .fag_records
            list with [memorial_id, slug] per candidate).
        dd_index:   {(last, initial): [{memorial_ids, ...}]}
        top_n:      how many of the top-ranked candidates to check.
        match_strength:
            'weak'  -> memorial_id matches any DD record for this soldier
            'strict' -> additionally, the candidate's slug must match the
                       DD slug in the URL (best-effort slug extraction from
                       the DD details URL).

    Returns: None or
        {
            'matched': True,
            'dd_soldier_first': str,
            'dd_soldier_last': str,
            'dd_memorial_id': int,
            'dd_record_type': str,
            'dd_details_url': str,
            'matched_candidate_rank': int,  # 1-based
            'matched_candidate_slug': str,
            'match_strength': str,
        }
    """
    key = _pensioner_key(pensioner)
    if not key:
        return None
    dd_records = dd_index.get(key)
    if not dd_records:
        return None
    dd_memorial_set = set()
    for rec in dd_records:
        for mid in rec["memorial_ids"]:
            dd_memorial_set.add(mid)
    if not dd_memorial_set:
        return None

    # Check the top N FaG candidates
    fag_records = pensioner.get("fag_records") or []
    for i, c in enumerate(fag_records[:top_n]):
        cand_mid_raw = c.get("memorial_id")
        try:
            cand_mid = int(cand_mid_raw) if cand_mid_raw is not None else None
        except (TypeError, ValueError):
            continue
        if cand_mid not in dd_memorial_set:
            continue
        # Found a candidate mid in DD. If strict, verify slug too.
        cand_slug = (c.get("slug") or "").strip().rstrip("/").lower()
        rec_with_mid = next(
            (r for r in dd_records if cand_mid in r["memorial_ids"]),
            dd_records[0],
        )
        if match_strength == "strict":
            dd_slug = _extract_dd_slug(rec_with_mid.get("dd_details_url") or "")
            if dd_slug and cand_slug and dd_slug != cand_slug:
                continue  # different memorial; skip
        return {
            "matched": True,
            "dd_soldier_first": rec_with_mid["first_name"],
            "dd_soldier_last": rec_with_mid["last_name"],
            "dd_memorial_id": cand_mid,
            "dd_record_type": rec_with_mid["source_record_type"],
            "dd_details_url": rec_with_mid["dd_details_url"],
            "matched_candidate_rank": i + 1,
            "matched_candidate_slug": cand_slug,
            "match_strength": match_strength,
        }
    return None


def _extract_dd_slug(url: str) -> str:
    """Extract the slug segment from a FaG URL
    (e.g. .../memorial/9121410/jane-doe -> 'jane-doe'). Returns ''
    when no slug parseable.
    """
    m = re.search(r"/memorial/\d+/([^/?#]+)", url)
    return m.group(1).lower().rstrip("/") if m else ""


# ============================================================
# Top-level: annotate results.jsonl + write sidecar
# ============================================================
def annotate_results_with_dd(
    results_path: Path,
    dd_index: dict,
    top_n: int = 1,
    match_strength: str = "weak",
) -> dict:
    """For each record in results.jsonl, compute a dd_match dict
    and write back to the same file with a new `dd_match` field.
    Returns a stats dict {matched, total, ...}.

    NOTE: Mutates the results.jsonl file in place. The runner's
    caller is responsible for making a backup if desired. We
    re-open + re-write line by line to keep memory bounded on
    large runs.
    """
    results_path = Path(results_path)
    if not results_path.exists():
        return {"matched": 0, "total": 0, "error": "results.jsonl not found"}

    tmp_path = results_path.with_suffix(results_path.suffix + ".tmp")
    matched = 0
    total = 0
    matched_ranks: list[int] = []
    matched_strength_breakdown = {"weak": 0, "strict": 0}
    matched_by_dd_record_type: dict = {}
    # For view.html: also collect (pensioner_id -> dd_match) for the
    # sidecar so the badge/filter can light up even when the user
    # re-loads an export that lost the per-record annotation.
    matched_pairs: list[dict] = []
    with results_path.open("r", encoding="utf-8") as fin, \
         tmp_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.rstrip("\n")
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                fout.write(line + "\n")
                continue
            dd = _match_pensioner_to_dd(
                rec, dd_index,
                top_n=top_n,
                match_strength=match_strength,
            )
            if dd:
                matched += 1
                matched_ranks.append(dd["matched_candidate_rank"])
                matched_strength_breakdown[match_strength] = (
                    matched_strength_breakdown.get(match_strength, 0) + 1
                )
                rtype = dd["dd_record_type"]
                matched_by_dd_record_type[rtype] = (
                    matched_by_dd_record_type.get(rtype, 0) + 1
                )
                pid = rec.get("pensioner_id")
                if pid is not None:
                    matched_pairs.append({
                        "pensioner_id": pid,
                        "dd_match": dd,
                    })
            rec["dd_match"] = dd  # always set: None or dict
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
    tmp_path.replace(results_path)
    stats = {
        "matched": matched,
        "total": total,
        "matched_at_top_rank": sum(1 for r in matched_ranks if r == 1),
        "matched_ranks_distribution": {
            str(k): matched_ranks.count(k) for k in sorted(set(matched_ranks))
        },
        "matched_strength_breakdown": matched_strength_breakdown,
        "matched_by_dd_record_type": matched_by_dd_record_type,
        "match_strength_param": match_strength,
        "top_n": top_n,
        "dd_source_path": "dixiedata_sqlite_or_zip",
        "matched_pairs": matched_pairs,
    }
    return stats


def cli_main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", type=Path, required=True,
                   help="Path to results.jsonl (input + output; mutated in place)")
    p.add_argument("--dd-db", type=Path, default=None,
                   help="Path to the live dixiedata SQLite (dixiedata.db).")
    p.add_argument("--dd-zip-backup", type=Path, default=None,
                   help="Path to a .ddbak zip backup (fallback when --dd-db is missing).")
    p.add_argument("--sidecar-out", type=Path, default=None,
                   help="Optional: write a stats sidecar JSON (e.g. dd_match.json alongside results.jsonl).")
    p.add_argument("--top-n", type=int, default=1,
                   help="How many of the top FaG candidates to check per pensioner (default 1).")
    p.add_argument("--match-strength", choices=["weak", "strict"], default="weak",
                   help="'weak': memorial_id only. 'strict': also requires slug match.")
    args = p.parse_args(argv)

    dd_index = load_dd_index(db_path=args.dd_db, zip_path=args.dd_zip_backup)
    log.info("loaded dixiedata index: %d (last, initial) entries with FaG records", len(dd_index))

    if not dd_index:
        print(
            "warning: no dixiedata DB or .ddbak found; nothing to do.",
            file=sys.stderr,
        )
        # Still emit a sidecar reporting zero matches so view.html
        # sees the same shape regardless.
        if args.sidecar_out:
            args.sidecar_out.write_text(json.dumps({
                "matched": 0, "total": 0, "dd_index_size": 0,
                "note": "no dd source provided; no matches",
            }, indent=2))
        return 0

    stats = annotate_results_with_dd(
        results_path=args.results,
        dd_index=dd_index,
        top_n=args.top_n,
        match_strength=args.match_strength,
    )
    log.info(
        "annotated %d/%d records as DD-matched (strength=%s, top_n=%d)",
        stats["matched"], stats["total"], args.match_strength, args.top_n,
    )
    if args.sidecar_out:
        args.sidecar_out.parent.mkdir(parents=True, exist_ok=True)
        stats_out = dict(stats)
        stats_out["dd_index_size"] = len(dd_index)
        args.sidecar_out.write_text(json.dumps(stats_out, indent=2))
        log.info("wrote sidecar: %s", args.sidecar_out)
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
