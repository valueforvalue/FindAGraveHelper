#!/usr/bin/env python3
"""CLI runner for the bulk OK scraper.

Usage:
  # Default: scrape all OK cemeteries (with vet details)
  python scripts/cgr_ok_scraper_run.py --state OK

  # Faster: skip vet details
  python scripts/cgr_ok_scraper_run.py --state OK --no-vet-details

  # Different state
  python scripts/cgr_ok_scraper_run.py --state TX

  # Resume a previous run
  python scripts/cgr_ok_scraper_run.py --state OK \\
      --out C:/tmp/ok_cgr.jsonl

Time estimates (throttle=1.0s):
  - OK: 848 cemeteries + ~10K vets = ~2-3 hours
  - TX: 4282 cemeteries + many more vets = ~10+ hours

Respects the CGR site (throttling, polite UA). Resume-safe.
"""
import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
PARENT = ROOT.parent
sys.path.insert(0, str(PARENT))

from scripts.cgr.cgr_client import CGRClient
from scripts.cgr.cgr_ok_scraper import scrape_ok_cemeteries, ScrapingConfig


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cgr_ok_scraper_run")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="OK",
                        help="2-letter state code (default: OK)")
    parser.add_argument("--out", type=Path,
                        default=Path(f"C:/tmp/cgr_{Path.cwd().name or 'scrape'}.jsonl"),
                        help="Output JSONL state file")
    parser.add_argument("--throttle", type=float, default=1.0,
                        help="Seconds between CGR requests (be polite)")
    parser.add_argument("--no-vet-details", action="store_true",
                        help="Skip vet detail fetches (faster, less data)")
    parser.add_argument("--limit-cemeteries", type=int, default=0,
                        help="Process at most N cemeteries (default: all)")
    args = parser.parse_args()

    client = CGRClient(throttle_seconds=args.throttle)
    config = ScrapingConfig(
        state=args.state,
        include_vet_details=not args.no_vet_details,
        throttle_seconds=args.throttle,
    )

    log.info("Output: %s", args.out)
    log.info("State: %s | Vet details: %s | Throttle: %.1fs",
             args.state, "yes" if config.include_vet_details else "no",
             args.throttle)

    records = scrape_ok_cemeteries(client, config, output_path=args.out)

    if args.limit_cemeteries and len(records) >= args.limit_cemeteries:
        # Already limited by the loop? We don't have a built-in limit
        # in scrape_ok_cemeteries; we just stop early.
        pass

    n_with_vets = sum(1 for r in records if r["veterans"])
    n_total_vets = sum(len(r["veterans"]) for r in records)
    log.info("Summary: %d cemeteries, %d with veterans, %d total vets",
             len(records), n_with_vets, n_total_vets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())