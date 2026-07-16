"""Unified runner (CGR cross-ref + FaG search).

For each pensioner, this module orchestrates:

  1. Look up the pensioner in a CGR blocking index (built from
     ok_cemeteries.jsonl or similar vet roster).
  2. Annotate CGR matches with match_strength.
  3. Decide: if CGR strong match exists, SKIP FaG (saves time).
  4. Otherwise run FaG and record candidates.

The output is one JSONL record per pensioner with:
  - pensioner_*: pensioner details
  - cgr_records, cgr_status
  - fag_records, fag_status, cgr_skipped_fag
  - both_match: { method, reason }
  - timestamp

The blocking index is built once and shared across all pensioners,
so lookups are O(1) per pensioner (instant) vs ~1.5s per
network call.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict, Field
from pathlib import Path
from typing import Optional

from scripts.blocking import (
    build_blocking_index,
    lookup_block,
)
from scripts.cgr_matcher import match_pensioner_to_cgr


# ============================================================
# CGR blocking index construction
# ============================================================
def build_cgr_blocking_index(cemeteries: list[dict]) -> tuple[dict, dict]:
    """Build a phonetic blocking index from CGR cemetery records.

    Input: list of cemetery records (ok_cemeteries.jsonl style)
    Returns:
      - block_index: dict[block_key -> set[vet_id]]
      - vets_by_id:  dict[vet_id -> full veteran dict]
                    (including cemetery_id, cemetery_name, county)

    We return both because the block_index is just IDs;
    the full records are needed downstream for context.
    """
    veterans = []
    for cem in cemeteries:
        for v in cem.get("veterans", []):
            vets_with_cem = {
                **v,
                "cemetery_id": cem.get("cemetery_id"),
                "cemetery_name": cem.get("cemetery_name"),
                "county": cem.get("county"),
            }
            veterans.append(vets_with_cem)
    block_index = build_blocking_index(veterans)
    vets_by_id = {v.get("id"): v for v in veterans if v.get("id") is not None}
    return block_index, vets_by_id


def lookup_cgr_for_pensioner(
    index: tuple[dict, dict], first_name: str, last_name: str, limit: int = 20
) -> list[dict]:
    """Look up vets in the blocking index for a pensioner.

    Returns the union of full veteran dicts across blocks.
    Caps at `limit` results.
    """
    block_index, vets_by_id = index
    ids = lookup_block(block_index, first_name=first_name, last_name=last_name)
    matches = []
    seen = set()
    for vid in ids:
        if vid in seen:
            continue
        seen.add(vid)
        if vid in vets_by_id:
            matches.append(vets_by_id[vid])
        if len(matches) >= limit:
            break
    return matches


# ============================================================
# Skip decision — POLICY (LOCKED 2026-07-16)
# ============================================================
# This function is INTENTIONALLY NOT CALLED by the unified pipeline.
# See scripts/unified_pipeline.py module docstring "DECISION POLICY
# (LOCKED 2026-07-16)": we always run FaG for every pensioner so
# we don't miss findings. The CGR data is used for annotation/display
# only; it does NOT gate whether to search FaG.
#
# This helper is kept here as a documentation anchor and for any
# future post-run dedup work that wants to filter CGR-strong rows
# in view.html. If you find a call site that uses it to skip FaG,
# STOP — that's policy drift.


def should_skip_fag(cgr_matches: list[dict]) -> bool:
    """(POLICY-LOCKED) Would-be skip-if-CGR-strong predicate.

    Returns True if any CGR match is 'strong'. This function is NOT
    wired into the FaG search path by policy decision
    (2026-07-16). Kept here so callers needing to surface CGR-
    strong rows for view.html / dedup work can do so without
    re-implementing the threshold logic.
    """
    return any(m.get("match_strength") == "strong" for m in cgr_matches)


# ============================================================
# Unified result
# ============================================================
@dataclass
class UnifiedConfig:
    """Configuration for a unified run.

    Note: the ``skip_fag_on_strong_cgr`` field is NOT honored by the
    pipeline (POLICY-LOCKED 2026-07-16 — we always run FaG). It is
    kept here so callers can detect policy drift if someone tries
    to gate FaG on CGR; the pipeline never reads it. See
    scripts/unified_pipeline.py module docstring.
    """
    skip_fag_on_strong_cgr: bool = field(
        default=True,
        metadata={
            "policy": "POLICY-LOCKED 2026-07-16",
            "note": "ignored by the pipeline; kept for back-compat. "
                    "See scripts/unified_pipeline.py module docstring "
                    "'DECISION POLICY (LOCKED 2026-07-16)'.",
        },
    )
    throttle_seconds: float = 1.5
    max_cgr_candidates: int = 20
    include_fag_candidates: bool = True


@dataclass
class UnifiedRunResult:
    """One pensioner's combined CGR + FaG result."""
    pensioner: dict
    cgr_records: list[dict] = field(default_factory=list)
    fag_records: list[dict] = field(default_factory=list)
    fag_status: str = "pending"  # pending | skipped_cgr_strong | auto_accept | ambiguous | too_many | no_results | error
    cgr_status: str = "pending"  # pending | cgr_found | no_match | error
    timestamp: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        out = {
            "pensioner_id": self.pensioner.get("id", -1),
            "pensioner_app_number": self.pensioner.get("application_number", ""),
            "pensioner_name": " ".join([
                self.pensioner.get("first_name", ""),
                self.pensioner.get("middle_name", ""),
                self.pensioner.get("last_name", ""),
            ]).strip().replace("  ", " "),
            "pensioner_first": self.pensioner.get("first_name", ""),
            "pensioner_middle": self.pensioner.get("middle_name", ""),
            "pensioner_last": self.pensioner.get("last_name", ""),
            "pensioner_birth_year": self.pensioner.get("birth_year", ""),
            "pensioner_death_year": self.pensioner.get("death_year", ""),
            "regiment": self.pensioner.get("regiment", ""),
            "company": self.pensioner.get("company", ""),
            "pensioncard_backlink": self.pensioner.get("pensioncard_backlink", ""),
            "backlink": self.pensioner.get("backlink", ""),
            "cgr_records": self.cgr_records,
            "cgr_status": self.cgr_status,
            "fag_records": self.fag_records,
            "fag_status": self.fag_status,
            "cgr_skipped_fag": (self.fag_status == "skipped_cgr_strong"),
            "timestamp": self.timestamp,
            "error": self.error,
        }
        return out


def annotate_cgr_matches(pensioner: dict, matches: list[dict]) -> list[dict]:
    """Run match_pensioner_to_cgr on the lookup matches."""
    return match_pensioner_to_cgr(pensioner, matches)


def write_state_line(state_path: Path, result: UnifiedRunResult) -> None:
    """Append a unified result to the JSONL state file."""
    import json
    state_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(result.to_dict(), ensure_ascii=False)
    with state_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


# ============================================================
# Index loaders
# ============================================================
def load_cgr_index_from_jsonl(path: Path) -> tuple[dict, dict]:
    """Load ok_cemeteries.jsonl into a blocking index."""
    cemeteries = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cemeteries.append(json.loads(line))
    return build_cgr_blocking_index(cemeteries)