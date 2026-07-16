"""CGR vet details enrichment.

Takes ok_cemeteries.jsonl (or any CGR scrape in our format),
flattens it to one record per vet, then fetches vetDetails.php
for each and merges the death data (died_state, death_date,
rank, etc).

The output (ok_vets_enriched.jsonl) is the input to the unified
runner's blocking index. With death data, we can finally make
strong/medium/weak match decisions based on real corroboration.

Resume-safe: if the output file already exists, we skip IDs
that have a `died_state` field set.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class EnrichmentStats:
    """Track enrichment progress for diagnostics."""
    total: int = 0
    fetched: int = 0
    errors: int = 0
    died_state_ok: int = 0  # died in OK (out of total)
    vet_died_in_ok: int = 0  # alias for died_state_ok

    @property
    def progress_pct(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.fetched / self.total) * 100

    def to_dict(self) -> dict:
        d = asdict(self)
        d["progress_pct"] = round(self.progress_pct, 1)
        return d


def expand_to_per_vet(cemeteries: list[dict]) -> list[dict]:
    """Flatten a list of cemeteries to one record per vet.

    Each output record includes:
      - id, name, unit, born (from input)
      - cemetery_id, cemetery_name, county, state (from input)
      - died, died_state, death_city, etc (added by enrichment)
    """
    out = []
    for cem in cemeteries:
        vets = cem.get("veterans", [])
        for v in vets:
            if not v.get("id"):  # skip if no id (malformed)
                continue
            out.append({
                **v,
                "cemetery_id": cem.get("cemetery_id"),
                "cemetery_name": cem.get("cemetery_name"),
                "county": cem.get("county"),
                "state": cem.get("state", "OK"),
            })
    return out


def build_enriched_record(base: dict, vet_details: Optional[dict]) -> dict:
    """Merge vet_details into the base vet record.

    Vet_details fields override base fields (e.g. unit name
    detail). If vet_details is empty/None, error fields are
    set and the base is preserved.
    """
    out = dict(base)
    if vet_details is None:
        out["vet_fetch_error"] = "fetch_failed"
        return out
    if not vet_details:
        # Empty dict means parser got nothing (page existed but no fields)
        out["vet_fetch_error"] = "empty_details"
        return out
    # Map vet_details fields into the enriched record
    for k, v in vet_details.items():
        if k.startswith("_"):  # skip internal markers
            continue
        out[k] = v
    out["vet_fetched_at"] = "now"  # could be a real timestamp
    return out


def parse_already_fetched(path: Path) -> set[int]:
    """Parse the output file to find vet IDs already fetched.

    Returns a set of vet IDs whose records already exist (with
    or without died_state — we re-fetch failed/empty ones).
    """
    if not path.exists():
        return set()
    ids = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("id") is not None:
                ids.add(rec["id"])
    return ids


def load_cemeteries_jsonl(path: Path) -> list[dict]:
    """Load ok_cemeteries.jsonl format (one record per cemetery)."""
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_enriched_vet(path: Path, record: dict) -> None:
    """Append one enriched vet record to the output file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
