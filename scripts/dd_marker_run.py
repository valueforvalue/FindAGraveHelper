#!/usr/bin/env python3
"""CLI: mark a state.jsonl with DixieData presence.

After the unified 7,758 run completes, run this script to
mark each pensioner with dd_in_local, dd_memorial_id, etc.

Usage:
  python scripts/dd_marker_run.py \\
    --state data/results/run_full_*/state.jsonl \\
    --dd  path/to/dixiedata_export.csv \\
    --out data/results/run_full_*/dd_marked.jsonl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from dd_marker import mark_state_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True,
                        help="state.jsonl from a unified run")
    parser.add_argument("--dd", type=Path, required=True,
                        help="DixieData CSV export")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output JSONL with DD marks")
    args = parser.parse_args()
    if not args.state.exists():
        print(f"State file not found: {args.state}", file=sys.stderr)
        return 1
    if not args.dd.exists():
        print(f"DD CSV not found: {args.dd}", file=sys.stderr)
        return 1

    n_marked, n_in_dd = mark_state_file(args.state, args.dd, args.out)
    pct = (n_in_dd / n_marked * 100) if n_marked else 0
    print(f"Marked {n_marked} records ({n_in_dd} already in DD = {pct:.1f}%)")
    print(f"Output: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
