"""Smoke test: run scheduler and legacy paths against same input, diff outputs.

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
        use_scheduler=True,
        blackboard_db_path=db_path,
        run_manifest=RunManifest(
            manifest_id="smoke-scheduler",
            run_id="smoke-scheduler",
        ),
        throttle_seconds=throttle,
        fag_search_fn=None,  # scheduler uses BrowserSession, not fag_search_fn
    )
    # Need fag_search_fn truthy to trigger BrowserSession creation in run_batch_scheduler
    if real_fag:
        cfg.fag_search_fn = True  # type: ignore[assignment] — signal to create BrowserSession

    cfg._blackboard_store = store  # type: ignore[attr-defined]

    try:
        run_batch_scheduler(pensioners, cems, cfg)
    finally:
        store.close()

    return _read_results(out_dir / "results.jsonl")


# ============================================================
# Legacy path
# ============================================================


def _run_legacy(
    input_path: Path, cgr_path: Path, out_dir: Path,
    limit: int | None, last_name_prefix: str | None,
    real_fag: bool,
) -> list[dict]:
    """Run legacy god-loop path and return sorted output rows."""
    from scripts.pipeline.run_unified import run_batch, UnifiedRunnerConfig
    from scripts.fag.fag_browser import make_fag_search_fn

    pensioners = _load_input(input_path, limit, last_name_prefix)
    cems = _load_cgr(cgr_path)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    throttle = 2.5 if real_fag else 0.0

    if real_fag:
        fag_fn = make_fag_search_fn(
            throttle=throttle,
            reset_browser_every=250,
            state_filter="OK",
        )
    else:
        fag_fn = None

    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        results_filename="results.jsonl",
        throttle_seconds=throttle,
        fag_search_fn=fag_fn,
        use_scheduler=False,
    )

    run_batch(pensioners, cems, cfg)
    return _read_results(out_dir / "results.jsonl")


# ============================================================
# Diff
# ============================================================


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

    # Run legacy path
    legacy_out = args.out / "legacy"
    print("[2/2] Running legacy path...")
    try:
        legacy_rows = _run_legacy(
            args.input, args.cgr, legacy_out, limit, args.filter_last_name, args.real_fag
        )
        print(f"      {len(legacy_rows)} rows -> {legacy_out / 'results.jsonl'}")
    except Exception as e:
        print(f"      FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Diff
    print("\n=== Diff ===")
    summary = diff_outputs(scheduler_rows, legacy_rows)
    print(json.dumps(summary, indent=2, default=str))

    (args.out / "diff_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    if not summary["ids_match"]:
        print("\nFAIL: ID sets differ between paths.")
        if summary["missing_from_scheduler"]:
            print(f"  Missing from scheduler: {summary['missing_from_scheduler'][:5]}")
        if summary["missing_from_legacy"]:
            print(f"  Missing from legacy: {summary['missing_from_legacy'][:5]}")
        return 1

    if summary["status_diff_count"] > 0:
        print(f"\nStatus diffs: {summary['status_diff_count']}")
        for d in summary["status_diffs"][:10]:
            print(f"  #{d['pensioner_id']} {d['pensioner_name']}: "
                  f"{d['legacy_status']} -> {d['scheduler_status']}")

    if summary["score_diff_count"] > 0:
        print(f"\nScore diffs: {summary['score_diff_count']}")
        for d in summary["score_diffs"][:10]:
            print(f"  #{d['pensioner_id']} {d['pensioner_name']}: "
                  f"{d['legacy_score']} -> {d['scheduler_score']}")

    if summary["score_diff_count"] == 0 and summary["ids_match"]:
        print("\nPASS: Both paths produced identical results.")
        return 0
    elif summary["ids_match"]:
        print(f"\nPASS: Same IDs. {summary['status_diff_count']} status diffs, "
              f"{summary['score_diff_count']} score diffs.")
        return 0
    else:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
