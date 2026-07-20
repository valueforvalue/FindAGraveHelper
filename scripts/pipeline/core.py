"""Per-record unified pipeline (T019 merge + 2026-07-20 refactor).

Combines the former scripts/unified_pipeline.py and
scripts/unified_runner.py into one module. PipelineResult is
the single boundary DTO; UnifiedRunResult remains as a
back-compat alias so existing callers compile.

The pipeline is engine-agnostic: a SearchRecord is the input
and a SearchEngine does the work. The default engine is
FaGEngine (for the OK Confederate pensioner use case); a
future Ancestry / FamilySearch / Newspapers.com engine
plugs in via config.engine.

DECISION POLICY (LOCKED 2026-07-16):

  We ALWAYS run the search engine for every record in the
  input. The CGR blocking index exists only to annotate
  matches for human display and post-run CGR-side dedup
  work; it MUST NOT gate whether we search.

  Rationale: the project goal is to discover how many of
  the ~7,758 OK Confederate pensioners are findable in
  Find a Grave. Short-circuiting on a "strong" CGR match
  would cost us findings - every skipped search is a
  missed opportunity to find a memorial that CGR didn't
  surface. Also, the CGR blocking index is noisy today
  (different-last-name matches sharing first-name
  phonetic codes), so a "strong" threshold alone is not
  reliable.

  If you are tempted to add a "skip search if CGR strong"
  gate: STOP. Open an issue instead. Do not gate the
  search.

FOLLOW-UP PHASE (LOCKED 2026-07-16):

  Rows whose first pass resulted in a low-confidence match
  (best_score < AUTO_ACCEPT_THRESHOLD, or status in
  {ambiguous, too_many, no_results}) are eligible for a
  follow-up phase that runs additional strategies until
  either (a) a top candidate scores >=
  AUTO_ACCEPT_THRESHOLD or (b) all follow-up strategies
  are exhausted.

  Follow-up strategies include (but are not limited to):
  spouse cross-search (if CGR row has spouse data),
  birth-state narrowing, nickname/initial-swap,
  regiment-bio with death-year. See
  scripts/pipeline/leftover_investigation.py for the
  implementation.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.matching.blocking import (
    build_blocking_index,
    lookup_block,
)
from scripts.cgr.cgr_matcher import match_pensioner_to_cgr
from scripts.matching.both_match import detect_both_match
from scripts.search.context import from_pensioner as _ctx_from_pensioner
from scripts.search.engine import default_search_one
from scripts.search.fag_engine import FaGEngine
from scripts.search.record import (
    SearchRecord,
    from_pensioner as _record_from_pensioner,
    to_pensioner_dict,
)


# ============================================================
# Configuration
# ============================================================
@dataclass
class PipelineConfig:
    """Configuration for the unified pipeline.

    engine: SearchEngine to use (default: FaGEngine() for the
    current OK pensioner use case). New code can pass
    FakeSearchEngine for tests, or a future AncestryEngine
    for a different search backend.

    page: a Playwright page (or stub for tests). Required when
    engine is set; ignored otherwise.

    fag_search_fn: legacy callback. If set AND engine is None,
    used for back-compat with existing callers. New code
    should use engine + page instead.
    """
    throttle_seconds: float = 1.5
    max_cgr_candidates: int = 20
    max_fag_candidates: int = 20
    engine: Any = None           # SearchEngine | None
    page: Any = None             # Playwright Page | stub | None
    fag_search_fn: Optional[Callable] = None  # legacy callback


@dataclass
class UnifiedConfig:
    """Back-compat alias. See PipelineConfig for the canonical type.

    Note: there is intentionally NO `skip_fag_on_strong_cgr` field.
    The decision to always run FaG is POLICY-LOCKED 2026-07-16 (see
    this module's docstring). Adding such a field back risks
    re-introducing the disabled skip path.
    """
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


# NOTE: The should_skip_fag() predicate was REMOVED entirely
# (previously was a would-be skip-if-CGR-strong check marked
# POLICY-LOCKED 2026-07-16). Per this module's DECISION POLICY,
# FaG runs unconditionally for every pensioner. If you need to
# surface CGR-strong rows for dedup or display, inline the check
# at the call site — do NOT re-introduce this helper, which
# historically invited accidental re-wiring of the skip path.


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
    """One record's combined pipeline result. The single boundary DTO.

    Fields:
      record:        the input SearchRecord (issue #34).
      pensioner:     back-compat dict form of the input (for the
                     legacy UnifiedRunResult.to_dict() path).
                     When None, derived from record; when supplied
                     explicitly, preserved verbatim (so legacy
                     callers that pass int ids keep int ids in
                     the wire format).
      cgr_records:   OK-specific CGR cross-reference matches.
                     Empty list when no CGR input is provided.
      fag_records:   matches from the engine. For FaGEngine this
                     is the FaG-candidate list. For other engines
                     this is the engine's candidate list (engine-
                     agnostic name; the wire format emits it as
                     "fag_records" for back-compat).
      fag_status:    engine status string. For FaGEngine this is
                     the FaG-specific status (auto_accept, etc.).
      cgr_status:    CGR cross-reference status.
      engine_result: the raw engine result dict (engine-agnostic).
                     For FaGEngine this contains the same data as
                     fag_records + strategies_run + classification.
      status:        engine-agnostic status. For FaGEngine this
                     mirrors fag_status; for other engines it's
                     whatever the engine returned.
      both_match:    cross-confirmation between CGR and engine.
      timestamp:     run time (ISO 8601).
      error:         error string if the engine or any stage failed.
    """
    record: SearchRecord
    pensioner: Optional[dict] = None
    cgr_records: list[dict] = field(default_factory=list)
    fag_records: list[dict] = field(default_factory=list)
    fag_status: str = "pending"
    cgr_status: str = "pending"
    engine_result: Optional[dict] = None
    status: str = "pending"
    both_match: Optional[dict] = None
    timestamp: str = ""
    error: Optional[str] = None

    def __post_init__(self):
        # If pensioner dict wasn't supplied, derive it from record.
        # When the caller passes an explicit pensioner dict, we
        # preserve it verbatim (the legacy wire format depends
        # on int ids staying as ints).
        if self.pensioner is None:
            self.pensioner = to_pensioner_dict(self.record)


@dataclass
class UnifiedRunResult:
    """Back-compat wrapper for the wire format.

    New code should use PipelineResult directly. This class
    exists to preserve the existing to_dict() output exactly.
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
            # NOTE: no `cgr_skipped_fag` key — see DECISION POLICY
            # (LOCKED 2026-07-16) in this module's docstring.
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
    """Run the unified pipeline for one pensioner (legacy entry).

    Back-compat: builds a SearchRecord internally and calls
    run_one(). New code should use run_one() directly with a
    SearchRecord and (optionally) a SearchEngine.

    The original pensioner dict is preserved on the result
    so the wire-format conversion produces byte-identical
    output to the pre-refactor pipeline.

    Args:
        pensioner: Pensioner dict (id, first_name, last_name, etc.)
        cgr_index_vets: List of cemetery records (for blocking index)
        config: Pipeline configuration
        fag_search_fn: Legacy callable that performs FaG search.
                        Ignored if config.engine is set. Used for
                        back-compat with existing callers.
        prebuilt_cgr_index: Optional pre-built (block_index, vets_by_id)
                            tuple. If provided, the per-pensioner
                            build is skipped.

    Returns:
        PipelineResult with all sources populated.
    """
    record = _record_from_pensioner(pensioner)
    # If config has no engine but fag_search_fn was passed, store
    # the callback on the config so run_one() can use it.
    if config.engine is None and fag_search_fn is not None:
        config = PipelineConfig(
            throttle_seconds=config.throttle_seconds,
            max_cgr_candidates=config.max_cgr_candidates,
            max_fag_candidates=config.max_fag_candidates,
            engine=config.engine,
            page=config.page,
            fag_search_fn=fag_search_fn,
        )
    return run_one(
        record, cgr_index_vets, config,
        pensioner_dict=pensioner,  # preserve verbatim
        prebuilt_cgr_index=prebuilt_cgr_index,
    )


def run_one(
    record: SearchRecord,
    cgr_index_vets: list[dict],
    config: PipelineConfig,
    *,
    pensioner_dict: Optional[dict] = None,
    prebuilt_cgr_index: Optional[tuple] = None,
) -> PipelineResult:
    """Run the unified pipeline for one record (new engine-agnostic entry).

    The new canonical entry point. Takes a SearchRecord and an
    engine (via config.engine). For the OK pensioner use case
    the engine is FaGEngine(); for tests, FakeSearchEngine();
    for future domains, AncestryEngine() / etc.

    Stages:
      1. CGR blocking + annotate (opt-in; OK-specific).
      2. Engine search (always runs; never gated by CGR).
      3. BOTH MATCH cross-confirmation (CGR + engine).

    Args:
        record: the SearchRecord.
        cgr_index_vets: list of CGR cemetery records.
        config: PipelineConfig (with engine + page for the
                new path, or fag_search_fn for the legacy path).
        pensioner_dict: optional original dict form. When
                provided, it's preserved on the result so the
                wire-format conversion produces byte-identical
                output to the pre-refactor pipeline. New code
                that only ever uses run_one() with a SearchRecord
                can omit this; the result's pensioner dict will
                be derived from the record.
        prebuilt_cgr_index: optional pre-built (block_index,
                vets_by_id) tuple.

    Returns:
        PipelineResult with all sources populated.
    """
    result = PipelineResult(
        record=record,
        pensioner=pensioner_dict,  # may be None; __post_init__ derives
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
            record.first,
            record.last,
            limit=config.max_cgr_candidates,
        )
        cgr_annotated = annotate_cgr_matches(result.pensioner, raw_matches)
        result.cgr_records = cgr_annotated
        result.cgr_status = "cgr_found" if cgr_annotated else "no_match"
    except Exception as e:
        result.cgr_status = "error"
        result.error = f"CGR: {str(e)[:200]}"

    # Step 3: Engine search (always run; CGR must not gate).
    # Three code paths:
    #   (a) config.engine is set → use it (new engine-agnostic path).
    #   (b) config.fag_search_fn is set → use the legacy callback.
    #   (c) neither → "not_run" (CGR-only test mode).
    if config.engine is not None:
        try:
            ctx = record.to_context()
            engine_result = default_search_one(
                config.engine, config.page, ctx,
            )
            result.engine_result = engine_result
            result.fag_records = list(engine_result.get("candidates") or [])
            err = engine_result.get("error")
            if err:
                result.error = f"Engine: {err[:200]}"
            # Engine status: for FaG this maps to fag_status; for
            # other engines, the engine's classification.value
            # (or "auto_accept" if candidates exist) becomes the
            # engine-agnostic status.
            cands = engine_result.get("candidates") or []
            if cands:
                # Best-candidate scoring. Handle the case where
                # the engine didn't attach a numeric score to
                # every candidate (some engines emit candidates
                # without scores; the fag_status is then derived
                # from the engine classification below).
                def _score(c):
                    try:
                        return float(c.get("score", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        return 0.0
                best = max(cands, key=_score)
                best_score = _score(best)
                # Heuristic: if best_score >= FAG_AUTO_ACCEPT_THRESHOLD
                # → auto_accept; else if any candidates → needs_review;
                # else → low_score.
                from scripts.pipeline.scoring_constants import (
                    FAG_AUTO_ACCEPT_THRESHOLD,
                    LOW_SCORE_THRESHOLD,
                )
                if best_score >= FAG_AUTO_ACCEPT_THRESHOLD:
                    result.fag_status = "auto_accept"
                elif best_score >= LOW_SCORE_THRESHOLD:
                    result.fag_status = "needs_review"
                else:
                    result.fag_status = "low_score"
            else:
                # Empty candidates; surface the engine classification
                cls_value = (engine_result.get("classification")
                             or "no_results")
                result.fag_status = (
                    "captcha" if "captcha" in cls_value.lower()
                    or "challenge" in cls_value.lower()
                    else "no_results"
                )
            result.status = result.fag_status
        except Exception as e:
            result.fag_status = "error"
            result.status = "error"
            result.error = f"Engine: {str(e)[:200]}"
    elif config.fag_search_fn is not None:
        # Legacy callback path. Today this is what most callers use.
        try:
            fag_result, fag_status = config.fag_search_fn(
                result.pensioner, config,
            )
            if isinstance(fag_result, dict):
                result.fag_records = [fag_result] if fag_result else []
            elif isinstance(fag_result, list):
                result.fag_records = fag_result or []
            else:
                result.fag_records = []
            result.fag_status = fag_status
            result.status = fag_status
        except Exception as e:
            result.fag_status = "error"
            result.status = "error"
            result.error = f"FaG: {str(e)[:200]}"
    else:
        result.fag_status = "not_run"
        result.status = "not_run"

    # Step 4: BOTH MATCH detection
    if result.cgr_records and result.fag_records:
        bm = detect_both_match(
            result.pensioner,
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
# Issue #22: write_state_line adapter removed. Callers use
# JsonlStateRepository directly. No production callers found.