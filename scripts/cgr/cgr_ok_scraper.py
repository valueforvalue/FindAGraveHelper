"""Bulk OK scraper for the Confederate Graves Registry.

Walks all cemeteries in a state (default: OK), fetches all
veterans in each cemetery, and writes a JSONL state file
with one record per cemetery (and the vet list nested).

PHILOSOPHY:
  - CGR is a curated database — record what they say
  - DD local data is human-verified — do NOT assume errors
  - Resume-safe: re-run skips already-processed cemeteries
  - One bad cemetery doesn't kill the run (try/except per cemetery)
  - One bad vet doesn't kill the cemetery scrape (try/except per vet)

This is the bulk OK scrape that complements the per-pensioner
xref. Where the xref answers "is our pensioner in CGR?", this
answers "what's in CGR for OK?".

Usage:
  # Default: scrape all OK cemeteries
  python scripts/cgr_ok_scraper.py --state OK

  # Output to a specific file
  python scripts/cgr_ok_scraper.py --state OK --out C:/tmp/ok_cgr.jsonl

  # Faster: skip vet details (just list cemetery + names)
  python scripts/cgr_ok_scraper.py --state OK --no-vet-details

  # Resume a previous run
  python scripts/cgr_ok_scraper.py --state OK --out C:/tmp/ok_cgr.jsonl
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cgr_ok_scraper")


@dataclass
class ScrapingConfig:
    state: str = "OK"
    include_vet_details: bool = True
    throttle_seconds: float = 1.0
    max_cemeteries: Optional[int] = None


def scrape_ok_cemeteries(
    cgr_client,
    config: Optional[ScrapingConfig] = None,
    output_path: Optional[Path] = None,
) -> list[dict]:
    """Walk all cemeteries in the configured state, fetch their veterans.

    Returns the list of records (one per cemetery). Also writes
    to output_path as JSONL if provided.

    Each record:
      - cemetery_id, cemetery_name, county, raw_label
      - state: the state we searched
      - timestamp: ISO datetime
      - veterans: list of {id, name, unit, born, [vet_details]}
      - error: error message if cemetery failed (otherwise None)
    """
    if config is None:
        config = ScrapingConfig()

    log.info("Listing cemeteries in %s...", config.state)
    try:
        cemeteries = cgr_client.list_cemeteries_in_state(config.state)
    except Exception as e:
        log.error("Failed to list cemeteries in %s: %s", config.state, e)
        return []

    log.info("Found %d cemeteries in %s", len(cemeteries), config.state)

    # Resume-safe: load existing IDs
    processed_ids: set[int] = set()
    if output_path and output_path.exists():
        with output_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cid = rec.get("cemetery_id")
                    if cid is not None:
                        processed_ids.add(cid)
                except json.JSONDecodeError:
                    pass
        if processed_ids:
            log.info("Skipping %d already-processed cemeteries", len(processed_ids))

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for i, cem in enumerate(cemeteries, 1):
        cid = cem["id"]
        if cid in processed_ids:
            continue

        log.info(
            "[%d/%d] Cemetery %d — %s Co.: %s",
            i, len(cemeteries), cid, cem["county"], cem["name"],
        )

        record = {
            "state": config.state,
            "cemetery_id": cid,
            "cemetery_name": cem["name"],
            "county": cem["county"],
            "raw_label": cem["raw_label"],
            "veterans": [],
            "error": None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        try:
            vets = cgr_client.list_all_veterans_in_cemetery(cid)
        except Exception as e:
            log.error("  Failed to list vets for cemetery %d: %s", cid, e)
            record["error"] = f"list_all_veterans_in_cemetery failed: {str(e)[:200]}"
            records.append(record)
            _append(output_path, record)
            continue

        log.info("  -> %d veteran(s)", len(vets))

        for v in vets:
            if config.include_vet_details:
                vet_id = v.get("id")
                if vet_id is not None:
                    try:
                        details = cgr_client.get_vet_details(vet_id)
                        v["vet_details"] = details
                    except Exception as e:
                        v["vet_details"] = None
                        v["vet_error"] = str(e)[:200]
            record["veterans"].append(v)

        records.append(record)
        _append(output_path, record)

        if config.max_cemeteries is not None and len(records) >= config.max_cemeteries:
            log.info("Reached max_cemeteries=%d; stopping.", config.max_cemeteries)
            break

    log.info("Done. %d cemetery records.", len(records))
    return records


def _append(path: Optional[Path], record: dict) -> None:
    """Append one record to a JSONL file. No-op if path is None."""
    if path is None:
        return
    line = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()