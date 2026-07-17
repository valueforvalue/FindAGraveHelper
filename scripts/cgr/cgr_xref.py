"""CGR cross-reference orchestrator.

For each pensioner in our unified list, search the Confederate
Graves Registry (cgr.scv.org) and capture any matches with
full veteran + cemetery details.

PHILOSOPHY (user guidance, 2026-07-16):
  - DD local data is human-verified — do NOT assume errors
  - When CGR disagrees with local on unit or birth year,
    record the conflict, do not silently resolve
  - Return ALL CGR matches with match_strength annotations;
    let the human decide

This module orchestrates the per-pensioner logic. The full
batch runner is in cgr_xref_run.py.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


from scripts.cgr.cgr_matcher import match_pensioner_to_cgr


@dataclass
class XrefConfig:
    """Configuration for a CGR cross-reference run."""
    include_cemetery: bool = True
    throttle_seconds: float = 1.0  # be polite


def xref_one_pensioner(
    cgr_client, pensioner: dict, config: Optional[XrefConfig] = None
) -> dict:
    """Cross-reference one pensioner against CGR.

    Returns a JSON-serializable state record:
      - pensioner_id, pensioner_name (for tracking)
      - status: 'cgr_found' | 'no_match' | 'error'
      - cgr_records: list of matched CGR records, each with:
          - cgr_id, cgr_name, cgr_unit, cgr_born (from search results)
          - vet_details: full vet details dict (or None)
          - cemetery_details: full cemetery dict (or None)
          - match_strength: 'strong' | 'medium' | 'weak' | 'none'
          - conflicts: dict of conflicting fields
          - local_unit, local_birth_year, local_middle (for reference)
      - error: error message if status == 'error'

    If anything raises (network, parser, etc.), the record is
    still returned with status='error' and a useful error
    message. This lets the run continue.
    """
    if config is None:
        config = XrefConfig()

    pid = pensioner.get("id", -1)
    p_first = pensioner.get("first_name", "")
    p_last = pensioner.get("last_name", "")
    p_middle = pensioner.get("middle_name", "")
    p_regiment = pensioner.get("regiment", "")
    p_birth_year = pensioner.get("birth_year", "")
    name_raw = pensioner.get("name_raw", "")
    full_name = " ".join([p_first, p_middle, p_last]).strip() or name_raw

    record = {
        "pensioner_id": pid,
        "pensioner_name": full_name,
        "pensioner_first": p_first,
        "pensioner_middle": p_middle,
        "pensioner_last": p_last,
        "pensioner_regiment": p_regiment,
        "pensioner_birth_year": p_birth_year,
        "status": "no_match",
        "cgr_records": [],
        "error": None,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        cgr_results = cgr_client.search_by_name(fname=p_first, lname=p_last)
    except Exception as e:
        record["status"] = "error"
        record["error"] = f"search_by_name failed: {str(e)[:500]}"
        return record

    if not cgr_results:
        record["status"] = "no_match"
        return record

    # Annotate each CGR record with match_strength + conflicts
    matched = match_pensioner_to_cgr(pensioner, cgr_results)
    record["status"] = "cgr_found"

    # Fetch vet details (and optionally cemetery) for each CGR match
    for m in matched:
        cgr_id = m.get("cgr_id")
        if cgr_id is None:
            continue

        # Vet details
        try:
            vet = cgr_client.get_vet_details(cgr_id)
            m["vet_details"] = vet
        except Exception as e:
            m["vet_details"] = None
            m["vet_error"] = str(e)[:200]

        # Cemetery details (if enabled)
        if config.include_cemetery:
            try:
                cem = cgr_client.get_cemetery_details(cgr_id)
                m["cemetery_details"] = cem
            except Exception as e:
                m["cemetery_details"] = None
                m["cemetery_error"] = str(e)[:200]
        else:
            m["cemetery_details"] = None

        record["cgr_records"].append(m)

    return record