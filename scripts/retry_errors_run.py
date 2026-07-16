#!/usr/bin/env python3
"""CLI: retry pensioners that ended with status='error' in state.jsonl.

Usage:
  # After main run completes:
  python scripts/retry_errors_run.py \\
    --state data/results/run_full_*/state.jsonl \\
    --pensioners docs/research/digitalprairie/ok_pensioners.json \\
    --cgr docs/research/cgr/ok_vets_enriched.jsonl \\
    --throttle 1.5

The retry:
  1. Reads state.jsonl, finds records with fag_status='error'
  2. Re-runs each through the unified pipeline
  3. Updates successful retries' status in-place
  4. Marks each retried record with `retried_at` timestamp
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from retry_errors import retry_main, collect_error_pensioner_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True,
                        help="Path to state.jsonl from the main run")
    parser.add_argument("--pensioners", type=Path, required=True,
                        help="Path to ok_pensioners.json (input)")
    parser.add_argument("--cgr", type=Path, required=True,
                        help="Path to ok_vets_enriched.jsonl")
    parser.add_argument("--throttle", type=float, default=1.5,
                        help="Seconds between FaG requests (default 1.5)")
    parser.add_argument("--no-fag", action="store_true",
                        help="CGR-only retry (no FaG)")
    parser.add_argument("--no-rss-watchdog", action="store_true",
                        help="Disable the RSS watchdog (default: enabled)")
    parser.add_argument("--rss-warn-mb", type=int, default=2048,
                        help="RSS warn threshold in MB (default 2048)")
    parser.add_argument("--rss-force-reset-mb", type=int, default=4096,
                        help="Force browser-reset threshold in MB (default 4096)")
    parser.add_argument("--rss-exit-mb", type=int, default=6144,
                        help="Hard-exit threshold in MB (default 6144)")
    parser.add_argument("--max-consecutive-errors", type=int, default=10,
                        help="Stop after this many in-a-row FaG errors (default 10)")
    args = parser.parse_args()

    log = logging.getLogger("retry")
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)

    err_ids = collect_error_pensioner_ids(args.state)
    log.info("Found %d errored pensioner_ids in %s",
             len(err_ids), args.state)
    if not err_ids:
        log.info("Nothing to retry.")
        return 0

    # Optional RSS watchdog (same defaults as the main runner)
    watchdog = None
    if not args.no_rss_watchdog:
        from scripts.rss_watchdog import RSSWatchdog
        watchdog = RSSWatchdog(
            poll_seconds=30.0,
            warn_mb=args.rss_warn_mb,
            force_reset_mb=args.rss_force_reset_mb,
            exit_mb=args.rss_exit_mb,
        )
        watchdog.start()

    log.info("Retrying %d records with throttle=%0.2fs...", len(err_ids), args.throttle)
    result = retry_main(
        state_path=args.state,
        pensioners_path=args.pensioners,
        cgr_path=args.cgr,
        throttle_seconds=args.throttle,
        no_fag=args.no_fag,
        watchdog=watchdog,
        max_consecutive_errors=args.max_consecutive_errors,
    )
    log.info("Retry result: %s", result.to_dict())
    log.info("Recovered: %d | Still error: %d | Total retried: %d",
             result.recovered, result.still_error, result.retried)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
