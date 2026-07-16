#!/usr/bin/env python3
"""CGR cross-reference runner.

Walks the OK Confederate pensioner list (ok_pensioners.json), searches
each in the Confederate Graves Registry (cgr.scv.org), fetches
vet + cemetery details for any matches, and writes a state JSONL
file with one record per pensioner.

PHILOSOPHY:
  - DD local data is human-verified — do NOT assume errors
  - Conflicts (different unit, different birth year) are
    recorded, not silently resolved
  - All CGR matches are returned with match_strength annotations;
    the human reviews

Usage:
  # First 10 from ok_pensioners.json
  python scripts/cgr_xref_run.py --limit 10

  # Full batch
  python scripts/cgr_xref_run.py

  # From a different input (any JSON list with id/first_name/last_name/regiment)
  python scripts/cgr_xref_run.py --input path/to/file.json
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
PARENT = ROOT.parent
sys.path.insert(0, str(PARENT))

from scripts.cgr_client import CGRClient
from scripts.cgr_xref import xref_one_pensioner, XrefConfig


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cgr_xref_run")


def load_pensioners(path: Path) -> list[dict]:
    """Load pensioners from ok_pensioners.json (a JSON array)."""
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=Path("docs/research/digitalprairie/ok_pensioners.json"))
    parser.add_argument("--state", type=Path, required=True,
                        help="Output JSONL state file")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--throttle", type=float, default=1.0,
                        help="Seconds between CGR requests (be polite)")
    parser.add_argument("--no-cemetery", action="store_true",
                        help="Skip cemetery detail fetches")
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Input file not found: %s", args.input)
        return 1

    pensioners = load_pensioners(args.input)
    if args.limit:
        pensioners = pensioners[:args.limit]
    log.info("Loaded %d pensioners from %s", len(pensioners), args.input)

    # Resume-safe: skip already-processed IDs
    processed = set()
    if args.state.exists():
        with args.state.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    processed.add(rec.get("pensioner_id"))
                except json.JSONDecodeError:
                    pass
        log.info("Skipping %d already-processed pensioners", len(processed))

    config = XrefConfig(
        include_cemetery=not args.no_cemetery,
        throttle_seconds=args.throttle,
    )
    client = CGRClient(throttle_seconds=args.throttle)

    args.state.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    for p in pensioners:
        pid = p.get("id", -1)
        if pid in processed:
            continue
        count += 1
        full_name = f"{p.get('first_name', '')} {p.get('middle_name', '')} {p.get('last_name', '')}".strip()
        log.info("[%d/%d] id=%d  %s", count, len(pensioners), pid, full_name)

        record = xref_one_pensioner(client, p, config)
        with args.state.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Log the result
        n_cgr = len(record.get("cgr_records", []))
        if record["status"] == "cgr_found":
            log.info("    -> CGR: %d match(es)", n_cgr)
            for c in record["cgr_records"]:
                vet = c.get("vet_details", {})
                log.info(
                    "       %s [%s] died %s in %s",
                    c.get("cgr_name"), c.get("match_strength"),
                    vet.get("died", "?"), vet.get("died_state", "?"),
                )
        elif record["status"] == "no_match":
            log.info("    -> no CGR match")
        else:
            log.warning("    -> ERROR: %s", record.get("error"))

    log.info("Done. State file: %s", args.state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())