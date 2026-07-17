"""CLI runner for CGR vet details enrichment.

Usage:
  python scripts/cgr_enrich_run.py [--limit N] [--throttle 0.5]

Reads:
  docs/research/cgr/ok_cemeteries.jsonl  (input)

Writes:
  docs/research/cgr/ok_vets_enriched.jsonl  (output, one per vet)
  docs/research/cgr/ok_enrich.log         (progress log)

Resume-safe: existing IDs in the output file are skipped
unless their vet_fetch_error field is set (so failed fetches
get retried).

Throttle is critical: 2,593 vets × ~0.3s = ~13 min total.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr.cgr_enrich import (
    EnrichmentStats,
    build_enriched_record,
    expand_to_per_vet,
    load_cemeteries_jsonl,
    parse_already_fetched,
    write_enriched_vet,
)
from scripts.cgr.cgr_client import CGRClient


INPUT = ROOT / "docs" / "research" / "cgr" / "ok_cemeteries.jsonl"
OUTPUT = ROOT / "docs" / "research" / "cgr" / "ok_vets_enriched.jsonl"
LOG = ROOT / "docs" / "research" / "cgr" / "ok_enrich.log"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(INPUT),
                        help="Input ok_cemeteries.jsonl")
    parser.add_argument("--output", default=str(OUTPUT),
                        help="Output ok_vets_enriched.jsonl")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N vets (for testing)")
    parser.add_argument("--throttle", type=float, default=0.3,
                        help="Seconds between requests (default 0.3)")
    parser.add_argument("--resume", action="store_true", default=True,
                        help="Skip already-fetched IDs")
    args = parser.parse_args()

    log = logging.getLogger("enrich")
    log.setLevel(logging.INFO)
    handler = logging.FileHandler(args.output.replace(".jsonl", ".log"))
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)
    log.addHandler(logging.StreamHandler())

    input_path = Path(args.input)
    output_path = Path(args.output)
    log.info("Input: %s", input_path)
    log.info("Output: %s", output_path)

    # Load source cems
    cems = load_cemeteries_jsonl(input_path)
    log.info("Loaded %d cemeteries", len(cems))

    vets = expand_to_per_vet(cems)
    log.info("Expanded to %d vets", len(vets))

    # Resume support
    already = parse_already_fetched(output_path) if args.resume else set()
    log.info("Resume: skipping %d already-fetched", len(already))

    stats = EnrichmentStats(total=len(vets), fetched=len(already))
    client = CGRClient(throttle_seconds=args.throttle)
    t_start = time.time()

    try:
        for i, vet in enumerate(vets):
            vid = vet.get("id")
            if vid is None:
                continue

            # Skip if already fetched
            if vid in already:
                continue

            if args.limit and (i - len(already)) >= args.limit:
                log.info("Limit reached (n=%d); stopping", i - len(already))
                break

            # Fetch vet details
            try:
                vet_details = client.get_vet_details(vid)
                error = None
            except Exception as e:
                vet_details = None
                error = str(e)[:200]

            # Build enriched record
            if error and vet_details is None:
                vet["vet_fetch_error"] = error
                enriched = vet
            else:
                enriched = build_enriched_record(vet, vet_details)

            # Track stats
            stats.fetched += 1
            if enriched.get("died_state"):
                stats.died_state_ok += 1
            if enriched.get("died_state") == "OK":
                stats.vet_died_in_ok += 1

            write_enriched_vet(output_path, enriched)

            if i % 100 == 0:
                elapsed = time.time() - t_start
                rate = (stats.fetched - len(already)) / max(elapsed, 0.1)
                eta = (stats.total - stats.fetched) / max(rate, 0.1) / 60
                log.info(
                    "Progress: %d/%d (%.1f%%); %.1f req/s; ETA %.1f min",
                    stats.fetched, stats.total, stats.progress_pct,
                    rate, eta,
                )
    except KeyboardInterrupt:
        log.warning("Interrupted by user. State saved.")
    finally:
        elapsed = time.time() - t_start
        log.info("Final: %s", json.dumps(stats.to_dict()))
        log.info("Elapsed: %.1f s (%.1f min)", elapsed, elapsed / 60)


if __name__ == "__main__":
    main()