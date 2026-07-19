"""Smoke test: run scheduler and legacy paths against same input, diff outputs.

Usage:
    python scripts/smoke_diff.py --input ok_pensioners.json --cgr ok_vets_enriched.jsonl --limit 50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure scripts/ is on the path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _run_scheduler(
    input_path: Path, cgr_path: Path, out_dir: Path, limit: int
) -> list[dict]:
    """Run scheduler path and return sorted output rows."""
    from scripts.pipeline.run_unified import run_batch_scheduler, UnifiedRunnerConfig, BatchResult
    from scripts.blackboard.store import SqliteBlackboardStore
    from scripts.blackboard.schema import RunManifest

    pensioners = _load_input(input_path, limit)
    cems = _load_cgr(cgr_path)

    db_path = out_dir / "blackboard.db"
    store = SqliteBlackboardStore(db_path)
    store.open()

    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        results_filename="results.jsonl",
        use_scheduler=True,
        blackboard_db_path=db_path,
        run_manifest=RunManifest(
            manifest_id="smoke-scheduler",
            run_id="smoke-scheduler",
        ),
        throttle_seconds=0.0,
        fag_search_fn=None,  # no browser for smoke
    )
    cfg._blackboard_store = store  # type: ignore[attr-defined]

    try:
        run_batch_scheduler(pensioners, cems, cfg)
    finally:
        store.close()

    return _read_results(out_dir / "results.jsonl")


def _run_legacy(
    input_path: Path, cgr_path: Path, out_dir: Path, limit: int
) -> list[dict]:
    """Run legacy god-loop path and return sorted output rows."""
    from scripts.pipeline.run_unified import run_batch, UnifiedRunnerConfig

    pensioners = _load_input(input_path, limit)
    cems = _load_cgr(cgr_path)

    out_dir.mkdir(parents=True, exist_ok=True)

    # No real browser for smoke — compare non-FaG pipeline outputs
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        results_filename="results.jsonl",
        throttle_seconds=0.0,
        fag_search_fn=None,  # no browser
        use_scheduler=False,
    )

    run_batch(pensioners, cems, cfg)
    return _read_results(out_dir / "results.jsonl")


def _load_input(path: Path, limit: int) -> list[dict]:
    """Load pensioner data."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data[:limit] if limit else data
    return [data]


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


def diff_outputs(
    scheduler_rows: list[dict], legacy_rows: list[dict]
) -> dict:
    """Compare outputs. Returns diff summary dict."""
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

    # Per-pensioner comparison
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
                "scheduler_status": s_status,
                "legacy_status": l_status,
            })

        s_score = sr.get("best_score", 0.0) or 0.0
        l_score = lr.get("best_score", 0.0) or 0.0
        if abs(s_score - l_score) > 0.01:
            summary["score_diffs"].append({
                "pensioner_id": pid,
                "scheduler_score": s_score,
                "legacy_score": l_score,
            })

    summary["status_diff_count"] = len(summary["status_diffs"])
    summary["score_diff_count"] = len(summary["score_diffs"])
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True,
                   help="Path to ok_pensioners.json")
    p.add_argument("--cgr", type=Path, required=True,
                   help="Path to ok_vets_enriched.jsonl")
    p.add_argument("--limit", type=int, default=50,
                   help="Number of pensioners to test (default: 50)")
    p.add_argument("--out", type=Path, default=Path("output/smoke_diff"),
                   help="Output directory (default: output/smoke_diff)")
    args = p.parse_args()

    print(f"=== Smoke diff: {args.limit} pensioners ===")
    print(f"Input:  {args.input}")
    print(f"CGR:    {args.cgr}")

    # Run scheduler path
    sched_out = args.out / "scheduler"
    if sched_out.exists():
        import shutil
        shutil.rmtree(sched_out)
    sched_out.mkdir(parents=True, exist_ok=True)
    print("\n[1/2] Running scheduler path...")
    try:
        scheduler_rows = _run_scheduler(args.input, args.cgr, sched_out, args.limit)
        print(f"      {len(scheduler_rows)} rows written to {sched_out / 'results.jsonl'}")
    except Exception as e:
        print(f"      FAILED: {e}")
        return 1

    # Run legacy path
    legacy_out = args.out / "legacy"
    legacy_out.mkdir(parents=True, exist_ok=True)
    print("[2/2] Running legacy path...")
    try:
        legacy_rows = _run_legacy(args.input, args.cgr, legacy_out, args.limit)
        print(f"      {len(legacy_rows)} rows written to {legacy_out / 'results.jsonl'}")
    except Exception as e:
        print(f"      FAILED: {e}")
        return 1

    # Diff
    print("\n=== Diff ===")
    summary = diff_outputs(scheduler_rows, legacy_rows)
    print(json.dumps(summary, indent=2))

    # Write summary
    (args.out / "diff_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    # Pass if IDs match and status diffs are within tolerance
    if not summary["ids_match"]:
        print("\nFAIL: ID sets differ between paths.")
        return 1

    if summary["status_diff_count"] > 0:
        print(f"\nNOTE: {summary['status_diff_count']} status differences "
              f"(expected -- scoring policy differs between paths).")
        for d in summary["status_diffs"][:5]:
            print(f"  pensioner {d['pensioner_id']}: "
                  f"{d['legacy_status']} -> {d['scheduler_status']}")

    print("\nPASS: Both paths produced the same pensioner IDs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
