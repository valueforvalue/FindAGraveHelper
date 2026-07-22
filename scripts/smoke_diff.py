"""Smoke test: run scheduler path against sample input.

Usage (no FaG — fast sanity check):
    python scripts/smoke_diff.py --input ok_pensioners.json --cgr ok_vets_enriched.jsonl --limit 10

Usage (real FaG — takes hours, opens visible browser):
    python scripts/smoke_diff.py --input ok_pensioners.json --cgr ok_vets_enriched.jsonl \\
        --limit 50 --real-fag --filter-last-name F
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _load_input(path: Path, limit: int | None, last_name_prefix: str | None = None) -> list[dict]:
    """Load pensioner data, optionally filtering by last name prefix."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        result = data
    else:
        result = [data]

    if last_name_prefix:
        prefix = last_name_prefix.lower()
        result = [
            p for p in result
            if str(p.get("last_name", "")).lower().startswith(prefix)
        ]

    if limit:
        result = result[:limit]
    return result


def _load_cgr(path: Path) -> list[dict]:
    """Load CGR data (JSONL or JSON)."""
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return [
            json.loads(line)
            for line in raw.strip().split("\n")
            if line.strip()
        ]


def _read_results(path: Path) -> list[dict]:
    """Read results JSONL, return rows sorted by pensioner_id."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            rows.append(json.loads(line))
    rows.sort(key=lambda r: r.get("pensioner_id", 0))
    return rows


# ============================================================
# Scheduler path
# ============================================================


def _run_scheduler(
    input_path: Path, cgr_path: Path, out_dir: Path,
    limit: int | None, last_name_prefix: str | None,
    real_fag: bool,
) -> list[dict]:
    """Run scheduler path and return sorted output rows."""
    from scripts.pipeline.run_unified import run_batch_scheduler, UnifiedRunnerConfig
    from scripts.blackboard.store import SqliteBlackboardStore
    from scripts.blackboard.schema import RunManifest

    pensioners = _load_input(input_path, limit, last_name_prefix)
    cems = _load_cgr(cgr_path)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = out_dir / "blackboard.db"
    store = SqliteBlackboardStore(db_path)
    store.open()

    throttle = 2.5 if real_fag else 0.0

    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        results_filename="results.jsonl",
        enable_fag=real_fag,
        blackboard_db_path=db_path,
        run_manifest=RunManifest(
            manifest_id="smoke-scheduler",
            run_id="smoke-scheduler",
        ),
        throttle_seconds=throttle,
    )
    cfg._blackboard_store = store  # type: ignore[attr-defined]

    try:
        run_batch_scheduler(pensioners, cems, cfg)
    finally:
        store.close()

    return _read_results(out_dir / "results.jsonl")


# ============================================================
# Legacy path
# ============================================================


# ============================================================
# Smoke runner (scheduler only — legacy removed #86)
# ============================================================


def run_smoke(
    input_path: Path, cgr_path: Path, out_dir: Path,
    limit: int | None, last_name_prefix: str | None,
    real_fag: bool,
) -> dict:
    """Run scheduler path and return summary."""
    scheduler_rows = _run_scheduler(
        input_path, cgr_path, out_dir, limit, last_name_prefix, real_fag,
    )
    return {
        "rows": len(scheduler_rows),
        "ids": [r["pensioner_id"] for r in scheduler_rows[:5]],
        "statuses": {},
    }
    s_ids = {r["pensioner_id"] for r in scheduler_rows}
    l_ids = {r["pensioner_id"] for r in legacy_rows}

    summary: dict = {
        "scheduler_count": len(scheduler_rows),
        "legacy_count": len(legacy_rows),
        "ids_match": s_ids == l_ids,
        "status_diffs": [],
        "score_diffs": [],
        "missing_from_scheduler": sorted(l_ids - s_ids),
        "missing_from_legacy": sorted(s_ids - l_ids),
    }

    l_by_id = {r["pensioner_id"]: r for r in legacy_rows}
    for sr in scheduler_rows:
        pid = sr["pensioner_id"]
        lr = l_by_id.get(pid)
        if lr is None:
            continue

        s_status = sr.get("status", "")
        l_status = lr.get("status", "")
        if s_status != l_status:
            summary["status_diffs"].append({
                "pensioner_id": pid,
                "pensioner_name": sr.get("pensioner_name", ""),
                "scheduler_status": s_status,
                "legacy_status": l_status,
            })

        s_score = sr.get("best_score", 0.0) or 0.0
        l_score = lr.get("best_score", 0.0) or 0.0
        if abs(s_score - l_score) > 0.01:
            summary["score_diffs"].append({
                "pensioner_id": pid,
                "pensioner_name": sr.get("pensioner_name", ""),
                "scheduler_score": round(s_score, 4),
                "legacy_score": round(l_score, 4),
            })

    summary["status_diff_count"] = len(summary["status_diffs"])
    summary["score_diff_count"] = len(summary["score_diffs"])
    return summary


# ============================================================
# Main
# ============================================================


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--cgr", type=Path, required=True)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--filter-last-name", type=str, default=None,
                   help="Only pensioners whose last name starts with this letter")
    p.add_argument("--real-fag", action="store_true",
                   help="Run real FaG searches (opens browser, takes hours)")
    p.add_argument("--out", type=Path, default=Path("output/smoke_diff"))
    args = p.parse_args()

    limit = args.limit if args.limit else None

    print(f"=== Smoke diff ===")
    print(f"Input:      {args.input}")
    print(f"CGR:        {args.cgr}")
    print(f"Limit:      {args.limit}")
    print(f"Last name:  {args.filter_last_name or 'all'}")
    print(f"Real FaG:   {args.real_fag}")
    if args.real_fag:
        print("WARNING: Real FaG mode opens a visible browser. 2.5s throttle.")
        print("         This will take ~2 min/pensioner (50 = ~100 min).")

    # Count matching pensioners
    pensioners = _load_input(args.input, limit, args.filter_last_name)
    print(f"Matching:   {len(pensioners)} pensioners")

    # Run scheduler path
    sched_out = args.out / "scheduler"
    print("\n[1/2] Running scheduler path...")
    try:
        scheduler_rows = _run_scheduler(
            args.input, args.cgr, sched_out, limit, args.filter_last_name, args.real_fag
        )
        print(f"      {len(scheduler_rows)} rows -> {sched_out / 'results.jsonl'}")
    except Exception as e:
        print(f"      FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Smoke: run scheduler path and report.
    print("\n=== Smoke complete ===")
    summary = run_smoke(
        args.input, args.cgr, args.out, limit, args.filter_last_name, args.real_fag,
    )
    print(json.dumps(summary, indent=2, default=str))

    (args.out / "smoke_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    print(f"\nOK: {summary['rows']} rows processed by scheduler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
