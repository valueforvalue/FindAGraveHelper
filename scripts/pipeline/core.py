"""Per-pensioner unified pipeline (T019 merge).

Combines the former scripts/unified_pipeline.py and
scripts/unified_runner.py into one module. PipelineResult is
the single boundary DTO; UnifiedRunResult remains as a
back-compat alias so existing callers compile.

DECISION POLICY (LOCKED 2026-07-16):

  We ALWAYS run FaG for every pensioner in
  docs/research/digitalprairie/ok_pensioners.json. The CGR blocking
  index exists only to annotate matches for human display and
  post-run CGR-side dedup work; it MUST NOT gate whether we search
  FaG.

  Rationale: the project goal is to discover how many of the ~7,758
  OK Confederate pensioners are findable in Find a Grave. Short-
  circuiting on a "strong" CGR match would cost us findings - every
  skipped FaG search is a missed opportunity to find a memorial
  that CGR didn't surface. Also, the CGR blocking index is noisy
  today (different-last-name matches sharing first-name phonetic
  codes), so a "strong" threshold alone is not reliable.

  If you are tempted to add a "skip FaG if CGR strong" gate:
  STOP. Open an issue instead. Do not gate the FaG search.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from scripts.blocking import (
    build_blocking_index,
    lookup_block,
)
from scripts.cgr_matcher import match_pensioner_to_cgr
from scripts.both_match import detect_both_match


# ============================================================
# Configuration
# ============================================================
@dataclass
class PipelineConfig:
    """Configuration for the unified pipeline."""
    throttle_seconds: float = 1.5
    max_cgr_candidates: int = 20
    max_fag_candidates: int = 20


@dataclass
class UnifiedConfig:
    """Back-compat alias. See PipelineConfig for the canonical type.

    Note: the ``skip_fag_on_strong_cgr`` field is NOT honored by the
    pipeline (POLICY-LOCKED 2026-07-16). Kept here for back-compat.
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


# ============================================================
# CGR blocking index
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


def should_skip_fag(cgr_matches: list[dict]) -> bool:
    """(POLICY-LOCKED) Would-be skip-if-CGR-strong predicate.

    Returns True if any CGR match is 'strong'. This function is NOT
    wired into the FaG search path by policy decision
    (2026-07-16). Kept here so callers needing to surface CGR-
    strong rows for view.html / dedup work can do so without
    re-implementing the threshold logic.
    """
    return any(m.get("match_strength") == "strong" for m in cgr_matches)


def annotate_cgr_matches(pensioner: dict, matches: list[dict]) -> list[dict]:
    """Run match_pensioner_to_cgr on the lookup matches."""
    return match_pensioner_to_cgr(pensioner, matches)


def load_cgr_index_from_jsonl(path: Path) -> tuple[dict, dict]:
    """Load ok_cemeteries.jsonl into a blocking index."""
    cemeteries = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cemeteries.append(json.loads(line))
    return build_cgr_blocking_index(cemeteries)


# ============================================================
# Result DTOs
# ============================================================
@dataclass
class PipelineResult:
    """One pensioner's combined pipeline result. The single boundary DTO."""
    pensioner: dict
    cgr_records: list[dict] = field(default_factory=list)
    fag_records: list[dict] = field(default_factory=list)
    fag_status: str = "pending"
    cgr_status: str = "pending"
    both_match: Optional[dict] = None
    timestamp: str = ""
    error: Optional[str] = None


@dataclass
class UnifiedRunResult:
    """Back-compat alias for PipelineResult. The two have identical fields.

    New code should use PipelineResult directly.
    """
    pensioner: dict
    cgr_records: list[dict] = field(default_factory=list)
    fag_records: list[dict] = field(default_factory=list)
    fag_status: str = "pending"
    cgr_status: str = "pending"
    timestamp: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialise to the state.jsonl wire format."""
        return {
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


def pipeline_result_to_unified(result: PipelineResult) -> UnifiedRunResult:
    """Convert PipelineResult to UnifiedRunResult (for JSONL writing).

    Back-compat helper; new code can use PipelineResult directly.
    """
    return UnifiedRunResult(
        pensioner=result.pensioner,
        cgr_records=result.cgr_records,
        fag_records=result.fag_records,
        fag_status=result.fag_status,
        cgr_status=result.cgr_status,
        timestamp=result.timestamp,
        error=result.error,
    )


# ============================================================
# Per-pensioner pipeline
# ============================================================
# fag_search_fn signature: (pensioner, config) -> (fag_record_dict, status_str)
FagSearchFn = Callable[[dict, PipelineConfig], tuple[Optional[dict], str]]


def run_pipeline_for_pensioner(
    pensioner: dict,
    cgr_index_vets: list[dict],
    config: PipelineConfig,
    fag_search_fn: Optional[FagSearchFn] = None,
    prebuilt_cgr_index: Optional[tuple] = None,
) -> PipelineResult:
    """Run the unified pipeline for one pensioner.

    Args:
        pensioner: Pensioner dict (id, first_name, last_name, etc.)
        cgr_index_vets: List of cemetery records (for blocking index)
        config: Pipeline configuration
        fag_search_fn: Callable that performs FaG search. REQUIRED
                        for normal runs. None = CGR-only test mode.
        prebuilt_cgr_index: Optional pre-built (block_index, vets_by_id)
                            tuple. If provided, the per-pensioner
                            build is skipped.

    Returns:
        PipelineResult with all sources populated.
    """
    result = PipelineResult(
        pensioner=pensioner,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    # Step 1-2: CGR blocking + annotate
    try:
        if prebuilt_cgr_index is not None:
            cgr_index = prebuilt_cgr_index
        else:
            cgr_index = build_cgr_blocking_index(cgr_index_vets)
        raw_matches = lookup_cgr_for_pensioner(
            cgr_index,
            pensioner.get("first_name", ""),
            pensioner.get("last_name", ""),
            limit=config.max_cgr_candidates,
        )
        cgr_annotated = annotate_cgr_matches(pensioner, raw_matches)
        result.cgr_records = cgr_annotated
        result.cgr_status = "cgr_found" if cgr_annotated else "no_match"
    except Exception as e:
        result.cgr_status = "error"
        result.error = f"CGR: {str(e)[:200]}"

    # Step 3: FaG search (always run; CGR must not gate)
    if fag_search_fn is not None:
        try:
            fag_result, fag_status = fag_search_fn(pensioner, config)
            if isinstance(fag_result, dict):
                result.fag_records = [fag_result] if fag_result else []
            elif isinstance(fag_result, list):
                result.fag_records = fag_result or []
            else:
                result.fag_records = []
            result.fag_status = fag_status
        except Exception as e:
            result.fag_status = "error"
            result.error = f"FaG: {str(e)[:200]}"
    else:
        result.fag_status = "not_run"

    # Step 4: BOTH MATCH detection
    if result.cgr_records and result.fag_records:
        bm = detect_both_match(
            pensioner,
            result.cgr_records,
            result.fag_records,
            fag_link=None,
        )
        if bm is not None:
            result.both_match = bm.to_dict()

    return result


# ============================================================
# State writers
# ============================================================
def write_state_line(state_path: Path, result: UnifiedRunResult) -> None:
    """Append a unified result to the JSONL state file."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(result.to_dict(), ensure_ascii=False)
    with state_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()