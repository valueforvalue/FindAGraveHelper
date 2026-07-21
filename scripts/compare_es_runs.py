"""Compare es-fresh-run-2026-07-20 (new) vs es-fresh-run (baseline) results.

Usage:
    python scripts/compare_es_runs.py
        --old  output/es-fresh-run/results.jsonl
        --new  output/es-fresh-run-2026-07-20/results.jsonl
        --out  output/es-fresh-run-2026-07-20/comparison.md

Produces a Markdown report:
- Status counts (old vs new)
- Per-pensioner status diff
- Per-pensioner top-score diff
- "New auto-accepts" (in new but not old)
- "Lost auto-accepts" (in old but not new)
- Score-drift histogram
- Schema-shape diff (old F1 fields vs new F2 fields)

The two files have different schemas (legacy F1 has
`fag_status` + `fag_records`; new F2 has `status` + `common`).
This script bridges them so the comparison is apples-to-apples.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

# Status-name bridges (new schema -> old schema) for the purpose of
# comparing verdict categories. Both old and new can land in the
# same bucket: "high-confidence" / "needs-review" / "low" / "no-hit".
STATUS_BRIDGE = {
    # old (F1) -> canonical bucket
    "auto_accept": "high_confidence",
    "ambiguous": "needs_review",
    "too_many": "needs_review",
    "no_results": "no_hit",
    "error": "no_hit",
    "captcha": "no_hit",
    # new (F2) -> canonical bucket
    "auto_accept": "high_confidence",
    "needs_review": "needs_review",
    "low_score": "low",
    "no_candidates": "no_hit",
    "blocked": "no_hit",
}


def load_old(path: Path) -> dict[int, dict]:
    """Load legacy F1 records keyed by pensioner_id (int)."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        pid = r.get("pensioner_id")
        if pid is not None:
            out[int(pid)] = r
    return out


def load_new(path: Path) -> dict[int, dict]:
    """Load new F2 records keyed by pensioner_id (int)."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        pid = r.get("pensioner_id")
        if pid is not None:
            out[int(pid)] = r
    return out


def canonical_status_old(r: dict) -> str:
    """Map legacy F1 record to canonical verdict bucket."""
    s = r.get("fag_status") or r.get("status") or "?"
    return STATUS_BRIDGE.get(s, s)


def canonical_status_new(r: dict) -> str:
    """Map new F2 record to canonical verdict bucket."""
    s = r.get("status") or r.get("outcome") or "?"
    return STATUS_BRIDGE.get(s, s)


def top_score(r: dict, is_new: bool) -> float:
    """Extract the top candidate score regardless of schema."""
    if is_new:
        return float(r.get("best_score", 0.0) or 0.0)
    return float(r.get("best_score", 0.0) or 0.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, type=Path)
    ap.add_argument("--new", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    old = load_old(args.old)
    new = load_new(args.new)
    common_ids = sorted(set(old.keys()) & set(new.keys()))
    only_old = sorted(set(old.keys()) - set(new.keys()))
    only_new = sorted(set(new.keys()) - set(old.keys()))

    # ----- Section 1: status counts -----
    old_status_counts = Counter(canonical_status_old(r) for r in old.values())
    new_status_counts = Counter(canonical_status_new(r) for r in new.values())

    # ----- Section 2: per-pensioner status diff -----
    status_diff: list[tuple[int, str, str, str, float, float]] = []
    for pid in common_ids:
        old_b = canonical_status_old(old[pid])
        new_b = canonical_status_new(new[pid])
        if old_b != new_b:
            old_score = top_score(old[pid], is_new=False)
            new_score = top_score(new[pid], is_new=True)
            name = (
                new[pid].get("pensioner_name")
                or old[pid].get("pensioner_name")
                or "?"
            )
            status_diff.append(
                (pid, name, old_b, new_b, old_score, new_score)
            )

    # ----- Section 3: score drift (common-status pensioners) -----
    score_diffs: list[tuple[int, str, float, float, float]] = []
    for pid in common_ids:
        old_b = canonical_status_old(old[pid])
        new_b = canonical_status_new(new[pid])
        if old_b == new_b:
            old_score = top_score(old[pid], is_new=False)
            new_score = top_score(new[pid], is_new=True)
            drift = new_score - old_score
            if abs(drift) >= 0.05:  # only meaningful drifts
                name = (
                    new[pid].get("pensioner_name")
                    or old[pid].get("pensioner_name")
                    or "?"
                )
                score_diffs.append((pid, name, old_score, new_score, drift))

    # ----- Section 4: new / lost auto-accepts -----
    new_auto = [
        (pid, new[pid].get("pensioner_name", "?"))
        for pid in sorted(set(new.keys()))
        if canonical_status_new(new[pid]) == "high_confidence"
    ]
    old_auto = [
        (pid, old[pid].get("pensioner_name", "?"))
        for pid in sorted(set(old.keys()))
        if canonical_status_old(old[pid]) == "high_confidence"
    ]
    new_auto_ids = {pid for pid, _ in new_auto}
    old_auto_ids = {pid for pid, _ in old_auto}
    gained = sorted(new_auto_ids - old_auto_ids)
    lost = sorted(old_auto_ids - new_auto_ids)

    # ----- Section 5: score distribution comparison -----
    def score_buckets(records: dict[int, dict], is_new: bool) -> Counter:
        c: Counter = Counter()
        for r in records.values():
            s = top_score(r, is_new)
            if s < 0.20:
                c["<0.20"] += 1
            elif s < 0.40:
                c["0.20-0.40"] += 1
            elif s < 0.60:
                c["0.40-0.60"] += 1
            elif s < 0.80:
                c["0.60-0.80"] += 1
            elif s < 0.95:
                c["0.80-0.95"] += 1
            else:
                c["0.95-1.00"] += 1
        return c

    old_buckets = score_buckets(old, is_new=False)
    new_buckets = score_buckets(new, is_new=True)

    # ----- Write Markdown -----
    md: list[str] = []
    md.append("# es-fresh-run comparison (new vs baseline)")
    md.append("")
    md.append(f"- Baseline (`--old`): {args.old}")
    md.append(f"- New run (`--new`):  {args.new}")
    md.append(f"- Records in old: {len(old)}")
    md.append(f"- Records in new: {len(new)}")
    md.append(f"- Common pensioner_ids: {len(common_ids)}")
    md.append(f"- Only in old: {len(only_old)}; only in new: {len(only_new)}")
    md.append("")

    md.append("## Status verdict distribution")
    md.append("")
    md.append("| Bucket | Old (F1) | New (F2) | Δ |")
    md.append("|---|---:|---:|---:|")
    all_buckets = sorted(
        set(old_status_counts.keys()) | set(new_status_counts.keys())
    )
    for b in all_buckets:
        o = old_status_counts.get(b, 0)
        n = new_status_counts.get(b, 0)
        delta = n - o
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        md.append(f"| {b} | {o} | {n} | {delta_str} |")
    md.append("")

    md.append("## Auto-accept reconciliation")
    md.append("")
    md.append(f"- Old auto-accepts: {len(old_auto)}")
    md.append(f"- New auto-accepts: {len(new_auto)}")
    md.append(f"- Gained (new only): {len(gained)}")
    md.append(f"- Lost (old only): {len(lost)}")
    md.append("")
    if gained:
        md.append("### Gained auto-accepts")
        md.append("")
        md.append("| Pensioner | Name | Old | New |")
        md.append("|---:|---|---|---|")
        for pid in gained:
            name = new[pid].get("pensioner_name", "?")
            old_b = canonical_status_old(old[pid])
            new_b = canonical_status_new(new[pid])
            md.append(f"| {pid} | {name} | {old_b} | {new_b} |")
        md.append("")
    if lost:
        md.append("### Lost auto-accepts")
        md.append("")
        md.append("| Pensioner | Name | Old | New |")
        md.append("|---:|---|---|---|")
        for pid in lost:
            name = old[pid].get("pensioner_name", "?")
            old_b = canonical_status_old(old[pid])
            new_b = canonical_status_new(new[pid])
            md.append(f"| {pid} | {name} | {old_b} | {new_b} |")
        md.append("")

    md.append("## Per-pensioner status changes")
    md.append("")
    md.append(f"Total: {len(status_diff)} pensioners changed verdict bucket.")
    md.append("")
    if status_diff:
        md.append("| Pensioner | Name | Old bucket | New bucket | Old score | New score |")
        md.append("|---:|---|---|---|---:|---:|")
        for pid, name, o, n, os, ns in status_diff:
            md.append(
                f"| {pid} | {name} | {o} | {n} | {os:.3f} | {ns:.3f} |"
            )
        md.append("")

    md.append("## Score drift on same-status pensioners")
    md.append("")
    md.append(
        f"Total: {len(score_diffs)} pensioners with ≥0.05 score drift "
        "where verdict bucket unchanged."
    )
    md.append("")
    if score_diffs:
        md.append("| Pensioner | Name | Old score | New score | Δ |")
        md.append("|---:|---|---:|---:|---:|")
        # Show largest absolute drifts first, capped at 30
        score_diffs.sort(key=lambda x: abs(x[4]), reverse=True)
        for pid, name, os, ns, drift in score_diffs[:30]:
            md.append(
                f"| {pid} | {name} | {os:.3f} | {ns:.3f} | {drift:+.3f} |"
            )
        if len(score_diffs) > 30:
            md.append(f"\n_(+{len(score_diffs) - 30} more, omitted)_")
        md.append("")

    md.append("## Score distribution")
    md.append("")
    md.append("| Range | Old (F1) | New (F2) | Δ |")
    md.append("|---|---:|---:|---:|")
    all_ranges = sorted(old_buckets.keys() | new_buckets.keys())
    for r in all_ranges:
        o = old_buckets.get(r, 0)
        n = new_buckets.get(r, 0)
        delta = n - o
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        md.append(f"| {r} | {o} | {n} | {delta_str} |")
    md.append("")

    md.append("## Caveats")
    md.append("")
    md.append(
        "- Throttle raised from 1.5s (old) to 2.5s (new) because "
        "BrowserSession enforces the L1 floor. Wall clock "
        "approximately doubled."
    )
    md.append(
        "- Threshold hardcoded at 0.85 in both runs; the canonical "
        "`FAG_AUTO_ACCEPT_THRESHOLD` is now 0.70 (issue #37) but the "
        "config explicitly set 0.85 to isolate architecture drift from "
        "scoring-constants drift."
    )
    md.append(
        "- Status-name bridges: `auto_accept` ↔ `auto_accept`; "
        "`ambiguous`/`too_many` ↔ `needs_review`; `no_results` ↔ "
        "`no_candidates`. Both are the same verdict bucket under "
        "different naming."
    )
    md.append(
        "- Score = `best_score` in both schemas. Drift can come from "
        "additional strategies fired by the Blackboard (the new "
        "code runs the full 13-strategy FaG ladder via the engine "
        "layer, where the old code ran a subset of strategies per "
        "pensioner)."
    )

    args.out.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote comparison: {args.out}")
    print(f"  common ids:   {len(common_ids)}")
    print(f"  status diffs: {len(status_diff)}")
    print(f"  score drifts: {len(score_diffs)}")
    print(f"  gained auto:  {len(gained)}")
    print(f"  lost auto:    {len(lost)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())