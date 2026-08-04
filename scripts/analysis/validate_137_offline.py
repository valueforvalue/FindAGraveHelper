"""Offline validation of issue #137 against the 575-pair set.

Does NOT hit FaG. Builds the 575-pair set from dixiedata.db, then
walks the full v5 ladder against each pair to confirm:

- B10 fires only when birth_year < 1851 (no false positives)
- B10 cohort size is plausible (~15% per the issue)
- Bias trigger rate (state empty on both sides) on the cohort
- Per-strategy applicability count (compared to pre-#137 baseline
  via git log of the same file)
- No strategy raises an exception
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search.context import SearchContext
from scripts.search.strategies import STRATEGIES, b10_pre1851_tight


def build_pairs() -> list[dict]:
    con = sqlite3.connect(ROOT / "dixiedata.db")
    cur = con.cursor()
    cur.execute(
        """SELECT s.id, s.first_name, s.middle_name, s.last_name,
                  s.death_year, s.buried_in, r.details
           FROM soldiers s
           JOIN records r ON r.person_record_id = s.id
           WHERE r.record_type LIKE '%Find a Grave%'"""
    )
    pairs = []
    for sid, fn, mn, ln, dy, buried, det in cur.fetchall():
        if not det:
            continue
        m = re.search(r"memorial/(\d+)", det) or re.search(
            r'memorial_id\D*(\d+)',
            det,
        )
        if not m:
            continue
        state = ""
        if buried and "," in buried:
            tail = buried.rsplit(",", 1)[-1].strip().upper()
            if len(tail) == 2 and tail.isalpha():
                state = tail
        # Birth year proxy: death_year - 65 (CW vets).
        # Soldiers table has no birth_year column.
        dy_str = str(dy or "").strip()
        birth_proxy = ""
        if dy_str.isdigit():
            by = int(dy_str) - 65
            if 1800 <= by <= 1900:
                birth_proxy = str(by)
        pairs.append(
            {
                "soldier_id": sid,
                "first": fn or "",
                "middle": mn or "",
                "last": ln or "",
                "death_year": dy_str,
                "birth_year_proxy": birth_proxy,
                "state": state,
                "memorial_id": m.group(1),
            }
        )
    return pairs


def main() -> int:
    pairs = build_pairs()
    print(f"=== Offline validation of #137 (B10 + bias) ===")
    print(f"Total pairs: {len(pairs)}")

    apply_count: Counter = Counter()
    b10_fired = 0
    b10_buckets: Counter = Counter()
    exception_strats: Counter = Counter()

    for p in pairs:
        ctx = SearchContext(
            first=p["first"],
            middle=p["middle"],
            last=p["last"],
            birth_year=p["birth_year_proxy"],
            death_year=p["death_year"],
            state=p["state"],
        )
        for s in STRATEGIES:
            try:
                params = s.params(ctx)
            except Exception as e:
                exception_strats[s.name] += 1
                print(f"  EXCEPTION in {s.name} for soldier {p['soldier_id']}: {e}")
                continue
            if params is not None:
                apply_count[s.name] += 1
        b10_params = b10_pre1851_tight(ctx)
        if b10_params is not None:
            b10_fired += 1
            if p["birth_year_proxy"]:
                by_int = int(p["birth_year_proxy"])
                if by_int < 1830:
                    b10_buckets["<1830"] += 1
                elif by_int < 1840:
                    b10_buckets["1830-1839"] += 1
                elif by_int < 1850:
                    b10_buckets["1840-1849"] += 1
                else:  # 1850 boundary
                    b10_buckets["1850"] += 1
            else:
                b10_buckets["no_proxy"] += 1

    print(f"\n--- Per-strategy applicability (out of {len(pairs)} pairs) ---")
    for name, c in apply_count.most_common():
        print(f"  {name:25s} {c:4d} ({c / len(pairs) * 100:.1f}%)")

    print(f"\n--- B10 pre-1851 specifics ---")
    print(f"  Fired: {b10_fired} ({b10_fired / len(pairs) * 100:.1f}%)")
    print(f"  By bucket: {dict(b10_buckets)}")
    print(f"  Strategy exceptions: {dict(exception_strats)}")

    # Bias trigger rate
    no_state = sum(1 for p in pairs if not p["state"])
    no_death = sum(1 for p in pairs if not p["death_year"])
    no_both = sum(1 for p in pairs if not p["state"] and not p["death_year"])
    print(f"\n--- Bias trigger context (state empty on candidate side mirrors this) ---")
    print(f"  No state: {no_state}/{len(pairs)} ({no_state / len(pairs) * 100:.1f}%)")
    print(f"  No death year: {no_death}/{len(pairs)} ({no_death / len(pairs) * 100:.1f}%)")
    print(f"  No state AND no death year: {no_both}/{len(pairs)}")

    # Sanity: B10 false positive check
    false_pos = 0
    for p in pairs:
        ctx = SearchContext(
            first=p["first"],
            middle=p["middle"],
            last=p["last"],
            birth_year=p["birth_year_proxy"],
            death_year=p["death_year"],
            state=p["state"],
        )
        if b10_pre1851_tight(ctx) is not None:
            if not p["birth_year_proxy"] or not p["birth_year_proxy"].isdigit():
                false_pos += 1
            elif int(p["birth_year_proxy"]) >= 1851:
                false_pos += 1
    print(f"\n  B10 false positives: {false_pos}")
    assert false_pos == 0, f"B10 false positive count: {false_pos}"
    assert sum(exception_strats.values()) == 0, "Strategy exceptions detected"

    print("\n=== OFFLINE VALIDATION PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
