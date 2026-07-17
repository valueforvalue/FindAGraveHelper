"""Backfill pensions-application backlinks into an existing state.jsonl.

The state.jsonl written by run_unified.py / unified_runner.py currently
carries `pensioncard_backlink` (the pension card URL) but drops the
matching `backlink` (the pension application URL). This script enriches
existing state files so view.html and report.md can render both source
links per pensioner without waiting for a full pipeline rerun.

Usage:
  python scripts/backfill_backlinks.py \\
      --state data/results/run_full_2026_07_16/state.jsonl \\
      --unified docs/research/digitalprairie/ok_pensioners.json \\
      --output data/results/run_full_2026_07_16/state_enriched.jsonl

If --output is omitted, writes in place (atomic via .tmp + rename).

Backwards-safe:
  - Records already carrying a non-empty `backlink` are kept as-is.
  - Records with no match in ok_pensioners.json get `backlink: ""`.
  - Atomic write: .tmp + rename, so a crash mid-write leaves the
    original state.jsonl intact.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.state.repository import JsonlStateRepository


def load_unified_index(unified_path: Path) -> dict[int, str]:
    """Build {pensioner_id: backlink} from ok_pensioners.json.

    ok_pensioners.json is a JSON array (one record per pensioner, possibly
    multiple per pensioner_id). Pick the first record per id; the
    `backlink` field is the same across records for a given pensioner.
    """
    data = json.loads(unified_path.read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for rec in data:
        pid = rec.get("id")
        if pid is None:
            continue
        if pid in out:
            continue  # first wins
        backlink = rec.get("backlink", "")
        out[pid] = backlink or ""
    return out


def backfill(
    state_path: Path,
    unified_index: dict[int, str],
    output_path: Path | None = None,
) -> tuple[int, int, int]:
    """Add `backlink` to every state record. Returns (filled, skipped, missing).

    - filled: records that gained a non-empty backlink.
    - skipped: records that already had backlink (kept as-is).
    - missing: records whose pensioner_id is not in unified_index.
    """
    src_repo = JsonlStateRepository(state_path)
    filled = skipped = missing = 0
    new_records = []
    for rec in src_repo.iter_all():
        pid = rec.get("pensioner_id")
        existing = rec.get("backlink", "")
        if existing:
            skipped += 1
        elif pid in unified_index and unified_index[pid]:
            rec["backlink"] = unified_index[pid]
            filled += 1
        else:
            rec["backlink"] = ""
            missing += 1
        new_records.append(rec)

    output_path = output_path or state_path
    JsonlStateRepository(output_path).replace_all(new_records)
    return filled, skipped, missing

    # Atomic replace
    tmp_path.replace(output_path)
    return filled, skipped, missing


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", required=True, type=Path,
                   help="Path to existing state.jsonl")
    p.add_argument("--unified", required=True, type=Path,
                   help="Path to ok_pensioners.json (digitalprairie output)")
    p.add_argument("--output", type=Path, default=None,
                   help="Output path (default: overwrite --state)")
    args = p.parse_args()

    if not args.state.exists():
        print(f"ERROR: state file not found: {args.state}", file=sys.stderr)
        return 1
    if not args.unified.exists():
        print(f"ERROR: unified file not found: {args.unified}", file=sys.stderr)
        return 1

    print(f"Loading unified index from {args.unified}...")
    unified_index = load_unified_index(args.unified)
    print(f"  {len(unified_index)} pensioner IDs in ok_pensioners.json")

    print(f"Backfilling {args.state} -> {args.output or args.state}...")
    filled, skipped, missing = backfill(args.state, unified_index, args.output)

    total = filled + skipped + missing
    print(f"  total records:  {total}")
    print(f"  filled:         {filled}")
    print(f"  already present:{skipped}")
    print(f"  no match in unified: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())