"""Per-pensioner unified pipeline.

For each pensioner:
  1. Look up in CGR blocking index (fast, local)
  2. Annotate CGR matches with match_strength
  3. Run FaG search (browser; injected)
  4. Detect BOTH MATCH
  5. Return PipelineResult

DECISION POLICY (LOCKED 2026-07-16):

  We ALWAYS run FaG for every pensioner in
  docs/research/digitalprairie/ok_pensioners.json. The CGR blocking
  index exists only to annotate matches for human display and
  post-run CGR-side dedup work; it MUST NOT gate whether we search
  FaG.

  Rationale: the project goal is to discover how many of the ~7,758
  OK Confederate pensioners are findable in Find a Grave. Short-
  circuiting on a "strong" CGR match would cost us findings — every
  skipped FaG search is a missed opportunity to find a memorial
  that CGR didn't surface. Also, the CGR blocking index is noisy
  today (different-last-name matches sharing first-name phonetic
  codes), so a "strong" threshold alone is not reliable.

  EXTENSION (LOCKED 2026-07-16, follow-on discussion):

  The policy is interpreted as 'every pensioner gets searched as
  deeply as we have strategies'. The main run uses a 12-strategy
  ladder. Rows whose first pass resulted in a low-confidence match
  (e.g. best_score < 0.85, or fag_status in {ambiguous, too_many,
  no_results}) are eligible for a FOLLOW-UP phase that runs
  additional FaG strategies until either:

    (a) a top candidate scores > 0.85 (conclusive "found"), OR
    (b) all follow-up strategies are exhausted (conclusive
        "no FaG memorial page exists for this pensioner").

  Follow-up strategies include (but are not limited to): spouse
  cross-search (if the CGR row has spouse data), birth-state
  narrowing, nickname/initial-swap, regiment-bio with death-year.
  See docs/learnings/2026-07-16-run-2-learnings.md for the policy
  discussion that produced this extension.

  Future work (separate phase): once FaG state is available, the
  CGR data may be used to (1) find duplicates in CGR and
  (2) reduce human-review work in view.html. Neither of these
  replaces the per-pensioner FaG search.

  If you are tempted to add a "skip FaG if CGR strong" gate:
  STOP. Open an issue instead. Do not gate the FaG search.

The FaG browser search is injected (dependency injection)
so this module is testable without Playwright.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from scripts.unified_runner import (
    build_cgr_blocking_index,
    lookup_cgr_for_pensioner,
    annotate_cgr_matches,
    UnifiedRunResult,
)
from scripts.both_match import detect_both_match


# ============================================================
# Pipeline configuration
# ============================================================
@dataclass
class PipelineConfig:
    """Configuration for the unified pipeline."""
    throttle_seconds: float = 1.5
    max_cgr_candidates: int = 20
    max_fag_candidates: int = 20


# ============================================================
# Per-pensioner pipeline
# ============================================================
# fag_search_fn signature: (pensioner, config) -> (fag_record_dict, status_str)
FagSearchFn = Callable[[dict, PipelineConfig], tuple[Optional[dict], str]]


@dataclass
class PipelineResult:
    """One pensioner's combined pipeline result."""
    pensioner: dict
    cgr_records: list[dict] = field(default_factory=list)
    fag_records: list[dict] = field(default_factory=list)
    fag_status: str = "pending"
    cgr_status: str = "pending"
    both_match: Optional[dict] = None
    timestamp: str = ""
    error: Optional[str] = None


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
                            build is skipped — saves ~85 MB/min of
                            RSS churn over 7709 records. Build it once
                            in run_batch() and pass it down.

    Returns:
        PipelineResult with all sources populated.
    """
    import time
    result = PipelineResult(
        pensioner=pensioner,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    # Step 1+2: CGR lookup (always). Use the pre-built index when
    # supplied so we don't rebuild the 2,593-vet blocking index on
    # every record (which was the primary Python RSS leak).
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

    # Step 3: Always run FaG (per user decision)
    if fag_search_fn is not None:
        try:
            fag_result, fag_status = fag_search_fn(pensioner, config)
            # The FaG search function may return EITHER:
            #   (record_dict, status_str) — single candidate
            #   (list_of_records, status_str) — list of candidates
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
        # No FaG search function provided (test mode) — CGR only
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


def pipeline_result_to_unified(result: PipelineResult) -> UnifiedRunResult:
    """Convert PipelineResult to UnifiedRunResult (for JSONL writing)."""
    return UnifiedRunResult(
        pensioner=result.pensioner,
        cgr_records=result.cgr_records,
        fag_records=result.fag_records,
        fag_status=result.fag_status,
        cgr_status=result.cgr_status,
        timestamp=result.timestamp,
        error=result.error,
    )