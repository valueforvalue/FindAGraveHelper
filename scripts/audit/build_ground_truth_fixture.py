"""Build the ground-truth fixture from dixiedata.db.

The e2e ground-truth test (tests/test_e2e_ground_truth.py) needs
a CSV at a stable path that contains (pensioner_id, memorial_id)
pairs. The operator's hand-curated version lives at
C:\\tmp\\ground_truth.csv (privacy: the operator's personal
matches are not in the repo).

This script generates an equivalent public fixture from
dixiedata.db (which IS in the repo, per the operator's call).
Pairs are joined by pension_id (dixiedata.soldiers.pension_id
== ok_pensioners.pension_number). FAG records are pulled from
dixiedata.records where record_type='Find a Grave' and details
contains a /memorial/<id>/ URL.

Output: tests/fixtures/ground_truth.csv
  - columns: pensioner_id, pension_number, pensioner_name,
    soldier_first, soldier_last, memorial_id, memorial_url, rank
  - rank is set to 1 for every pair (the operator's matches
    are all top-rank by construction).
  - 240 pairs as of 2026-07-31. Refresh by re-running this
    script against a fresh dixiedata.db.

Idempotent: re-running overwrites the same schema.

Usage:
    python scripts/audit/build_ground_truth_fixture.py \\
        --output tests/fixtures/ground_truth.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_DB = _ROOT / "dixiedata.db"
DEFAULT_PENSIONERS = _ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners.json"
DEFAULT_OUTPUT = _ROOT / "tests" / "fixtures" / "ground_truth.csv"

_MEMORIAL_RE = re.compile(r"/memorial/(\d+)/")


def build(db: Path, pensioners_path: Path) -> list[dict]:
    """Return list of ground-truth dicts. Joins dixiedata.records
    to ok_pensioners.json on pension_id."""
    pensioners = json.loads(pensioners_path.read_text(encoding="utf-8"))
    pension_by_id = {
        (p.get("pension_number") or "").strip(): p
        for p in pensioners
        if (p.get("pension_number") or "").strip()
    }

    c = sqlite3.connect(str(db))
    cur = c.execute(
        "SELECT s.pension_id, s.first_name, s.last_name, r.details "
        "FROM records r JOIN soldiers s ON s.id = r.person_record_id "
        "WHERE r.record_type = 'Find a Grave' "
        "  AND r.details LIKE '%findagrave.com/memorial/%' "
        "  AND s.pension_id IS NOT NULL "
        "  AND s.pension_id != 'N/A' AND s.pension_id != ''"
    )

    out: list[dict] = []
    for pid, fn, ln, url in cur.fetchall():
        p = pension_by_id.get(pid)
        if p is None:
            continue
        m = _MEMORIAL_RE.search(url)
        if not m:
            continue
        
        out.append({
            "id": p.get("id"),
            "application_number": pid,
            "pensioner_name": p.get("name_raw", ""),
            "first_name": p.get("first_name", ""),
            "last_name": p.get("last_name", ""),
            "regiment": p.get("regiment", ""),
            "pensioncard_id": p.get("pensioncard_id", ""),
            
            
            "_gt_soldier_first": fn,
            "_gt_soldier_last": ln,
            "_gt_memorial_id": m.group(1),
            "_gt_memorial_url": url,
            "_gt_rank": 1,
        })
    c.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--pensioners", type=Path, default=DEFAULT_PENSIONERS)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args(argv)

    rows = build(args.db, args.pensioners)
    if not rows:
        sys.stderr.write(
            f"no rows from {args.db}; check the join keys.\n"
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".partial")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(args.output)
    print(f"wrote {len(rows)} ground-truth pairs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
