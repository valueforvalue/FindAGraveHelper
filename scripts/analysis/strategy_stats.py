"""Cross-run strategy effectiveness analytics (issue #79).

Reads run_audit.jsonl from all output/*/ directories (or a
specified root) and computes per-strategy metrics:

  - fires: how often each strategy ran
  - skipped: how often it was skipped
  - errors: how often it errored
  - total_candidates: sum of candidates from all fires
  - avg_candidates: mean candidates per fire
  - success_rate: fraction of runs where the strategy contributed
    to an auto_accept outcome (inferred from the pensioner's
    final status in the same audit file).

Output: a JSON report written to --out (default stdout).

Usage:
    python -m scripts.analysis.strategy_stats
    python -m scripts.analysis.strategy_stats --root output/
    python -m scripts.analysis.strategy_stats --out analytics/strategy_stats.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def collect_audit_files(root: Path) -> list[Path]:
    """Find all run_audit.jsonl files under *root*."""
    if not root.exists():
        return []
    return sorted(root.glob("*/run_audit.jsonl"))


def parse_audit(path: Path) -> dict[str, Any]:
    """Parse one run_audit.jsonl into aggregated per-strategy stats
    and per-pensioner outcomes."""
    strategy_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"fires": 0, "skipped": 0, "errors": 0, "total_candidates": 0}
    )
    # Per-pensioner outcome tracking: pensioner_id -> final status
    pensioner_statuses: dict[str, str] = {}
    # Maps pensioner_id -> set of strategies that contributed
    pensioner_strategies: dict[str, set[str]] = defaultdict(set)

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("event", "")
                pid = str(event.get("pensioner_id", ""))

                if event_type == "strategy_ran":
                    strat = event.get("strategy", "unknown")
                    candidates = int(event.get("candidates", 0))
                    strategy_stats[strat]["fires"] += 1
                    strategy_stats[strat]["total_candidates"] += candidates
                    if pid:
                        pensioner_strategies[pid].add(strat)

                elif event_type == "strategy_skipped":
                    strat = event.get("strategy", "unknown")
                    strategy_stats[strat]["skipped"] += 1

                elif event_type == "strategy_error":
                    strat = event.get("strategy", "unknown")
                    strategy_stats[strat]["errors"] += 1

                elif event_type == "pensioner_end":
                    pensioner_statuses[pid] = event.get("status", "unknown")
    except OSError:
        pass

    # Compute per-strategy success: fraction of fires where the
    # pensioner ended up auto_accept. Conservative estimate: a
    # strategy "succeeded" if at least one pensioner that it fired
    # on ended with auto_accept status.
    for strat, stats in strategy_stats.items():
        fires = stats["fires"]
        if fires == 0:
            stats["avg_candidates"] = 0.0
            stats["success_rate"] = 0.0
            continue
        stats["avg_candidates"] = round(stats["total_candidates"] / fires, 2)

        # Count how many unique pensioners this strategy ran for
        # and how many of those ended auto_accept.
        pids_touched: set[str] = set()
        pids_accepted: set[str] = set()
        for pid, strats in pensioner_strategies.items():
            if strat in strats:
                pids_touched.add(pid)
                if pensioner_statuses.get(pid) == "auto_accept":
                    pids_accepted.add(pid)
        n_touched = len(pids_touched)
        stats["pensioners_touched"] = n_touched
        stats["pensioners_accepted"] = len(pids_accepted)
        stats["success_rate"] = (
            round(len(pids_accepted) / n_touched, 4) if n_touched else 0.0
        )

    return dict(strategy_stats)


def aggregate_across_runs(
    root: Path,
) -> dict[str, Any]:
    """Collect + aggregate strategy stats across all runs."""
    files = collect_audit_files(root)
    all_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"fires": 0, "skipped": 0, "errors": 0, "total_candidates": 0}
    )

    run_summaries: list[dict] = []
    for path in files:
        run_name = path.parent.name
        stats = parse_audit(path)
        if not stats:
            continue
        total_fires = sum(s["fires"] for s in stats.values())
        total_skipped = sum(s["skipped"] for s in stats.values())
        total_errors = sum(s["errors"] for s in stats.values())
        run_summaries.append({
            "run": run_name,
            "strategies": len(stats),
            "total_fires": total_fires,
            "total_skipped": total_skipped,
            "total_errors": total_errors,
        })
        for strat, s in stats.items():
            all_stats[strat]["fires"] += s["fires"]
            all_stats[strat]["skipped"] += s.get("skipped", 0)
            all_stats[strat]["errors"] += s.get("errors", 0)
            all_stats[strat]["total_candidates"] += s["total_candidates"]
            # Pensioner-level stats are per-run; we average them.
            success = s.get("success_rate", 0.0)
            if "success_rates" not in all_stats[strat]:
                all_stats[strat]["success_rates"] = []
            all_stats[strat]["success_rates"].append(success)

    # Finalize: compute averages
    for strat, s in all_stats.items():
        fires = s["fires"]
        s["avg_candidates"] = round(s["total_candidates"] / fires, 2) if fires else 0.0
        rates = s.pop("success_rates", [])
        s["avg_success_rate"] = round(sum(rates) / len(rates), 4) if rates else 0.0
        s["runs_with_data"] = len(rates)

    return {
        "runs_analyzed": len(run_summaries),
        "runs": run_summaries,
        "strategies": all_stats,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Cross-run strategy effectiveness analytics."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("output"),
        help="Root directory containing run subdirectories (default: output/).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON file (default: stdout).",
    )
    args = parser.parse_args(argv)

    report = aggregate_across_runs(args.root)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
