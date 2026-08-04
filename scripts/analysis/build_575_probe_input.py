"""Build the JSON input for the full 575-record probe.

Output: data/probe_input_575.json — list of soldier dicts with
first, middle, last, death_year, bucket, memorial_id. The
probe_strategy_yield.py script reads this and runs the full
11-strategy ladder against real FaG.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DB = ROOT / "dixiedata.db"
OUT = ROOT / "data" / "probe_input_575.json"


def main() -> int:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(
        """SELECT s.id, s.first_name, s.middle_name, s.last_name,
                  s.death_year, s.buried_in, r.details
           FROM soldiers s
           JOIN records r ON r.person_record_id = s.id
           WHERE r.record_type LIKE '%Find a Grave%'"""
    )
    soldiers = []
    seen_ids = set()
    for sid, fn, mn, ln, dy, buried, det in cur.fetchall():
        if not det:
            continue
        m = re.search(r"memorial/(\d+)", det) or re.search(
            r"memorial_id\D*(\d+)",
            det,
        )
        if not m:
            continue
        # Dedupe on (soldier_id, memorial_id) so the one soldier with
        # 2 memorials appears twice (the 575-pair set is 574 soldiers
        # + 1 extra)
        key = (sid, m.group(1))
        if key in seen_ids:
            continue
        seen_ids.add(key)
        state = ""
        if buried and "," in buried:
            tail = buried.rsplit(",", 1)[-1].strip().upper()
            if len(tail) == 2 and tail.isalpha():
                state = tail
        dy_str = str(dy or "").strip()
        # Cohort bucket: pre-1851 (B10 candidate) vs other
        by_proxy = ""
        if dy_str.isdigit():
            by = int(dy_str) - 65
            if 1800 <= by <= 1900:
                by_proxy = str(by)
        bucket = "pre1851" if by_proxy and int(by_proxy) < 1851 else "other"
        soldiers.append(
            {
                "first": fn or "",
                "middle": mn or "",
                "last": ln or "",
                "death_year": dy_str,
                "memorial_id": m.group(1),
                "bucket": bucket,
                "state": state,
                "soldier_id": sid,
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(soldiers, f, indent=2)
    n_pre = sum(1 for s in soldiers if s["bucket"] == "pre1851")
    print(f"Wrote {len(soldiers)} soldiers to {OUT}")
    print(f"  pre-1851 cohort: {n_pre}")
    print(f"  other: {len(soldiers) - n_pre}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
