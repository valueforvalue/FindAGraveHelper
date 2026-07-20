"""Scoring + status constants for the unified pipeline.

Single source of truth for the threshold values that decide
whether a pensioner's FaG search result is auto-accepted,
needs human review, or marked low-score. Used by:

  - scripts/pipeline/dry_run.py (--dry-run prediction)
  - scripts/pipeline/core.py (follow-up phase eligibility)
  - scripts/pipeline/run_unified.py (CLI default for
    --low-score-threshold)
  - scripts/matching/outlier_classifier.py (default threshold)

Plus the canonical status string values used by every layer
that emits a PensionerRecord. Kept here so the dry-run
predictor and the production scorer never drift.

Per issue #28 follow-up: extract magic numbers + status
strings into one place.
"""
from __future__ import annotations

# ============================================================
# Thresholds (float, in [0, 1])
# ============================================================

#: best_score at or above which a record is auto-accepted
#: without human review. Mirrors the production FaG search
#: strategy's "strong match" cutoff.
AUTO_ACCEPT_THRESHOLD: float = 0.85

#: best_score below this is marked 'low_score' / outlier.
#: CLI default for --low-score-threshold; configurable.
LOW_SCORE_THRESHOLD: float = 0.40

#: best_score in [LOW_SCORE_THRESHOLD, AUTO_ACCEPT_THRESHOLD)
#: is 'needs_review' (auto-derived, not a constant itself).
NEEDS_REVIEW_THRESHOLD: float = LOW_SCORE_THRESHOLD

# ============================================================
# FaG-search decision thresholds
# ============================================================
# These are the gates the blackboard DecisionPolicy applies
# to one search run (per strategy ladder result). Distinct
# from the pipeline-decision AUTO_ACCEPT_THRESHOLD above,
# which is the gate the unified pipeline applies to a
# pensioner record as a whole. Both gates must clear for a
# pensioner to be marked STATUS_AUTO_ACCEPT.
#
#   FAG-search auto-accept    pipeline-decision auto-accept
#   FAG_AUTO_ACCEPT_THRESHOLD   AUTO_ACCEPT_THRESHOLD
#             0.70                        0.85
#
# The two are intentionally different values for different
# stages. Don't "consolidate" them.

#: FaG-search auto-accept threshold when the pensioner has a
#: known death year. Top-1 candidate must hit this score.
FAG_AUTO_ACCEPT_THRESHOLD: float = 0.70

#: FaG-search auto-accept threshold when the pensioner has NO
#: known death year. Lower because the max achievable score
#: is smaller (no death-year evidence to add).
FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH: float = 0.60

#: Top candidate must beat #2 by this gap for auto-accept
#: when multiple candidates exist.
FAG_AUTO_ACCEPT_GAP: float = 0.10

#: Score assigned by the Soundex-only fallback in
#: scripts/cgr/cgr_matcher.py when two names share a Soundex
#: code but are not identical. NOT the same as the
#: auto-accept threshold — this is the confidence that a
#: phonetic-only match is meaningful on its own. Kept here
#: so the Soundex fallback and the rest of the scoring
#: pipeline share a single source of truth.
SOUNDEX_MATCH_SCORE: float = 0.85


# ============================================================
# Status strings (the canonical enum of PensionerRecord.status)
# ============================================================

#: FaG found a strong match (>= AUTO_ACCEPT_THRESHOLD). The
#: pensioner's match is auto-accepted without human review.
STATUS_AUTO_ACCEPT: str = "auto_accept"

#: FaG found multiple top candidates within scoring tolerance.
#: Needs human review to pick the right one.
STATUS_AMBIGUOUS: str = "ambiguous"

#: FaG returned more than the page-parse cap (>20 candidates).
#: Needs human review or strategy refinement.
STATUS_TOO_MANY: str = "too_many"

#: FaG returned no candidates for this pensioner.
STATUS_NO_RESULTS: str = "no_results"

#: A pipeline error prevented FaG from running. The record
#: carries an `error` field with the failure detail.
STATUS_ERROR: str = "error"

#: FaG ran but the top score fell below LOW_SCORE_THRESHOLD.
#: Candidate is preserved for the follow-up phase.
STATUS_LOW_SCORE: str = "low_score"

#: FaG ran and the top score fell in
#: [LOW_SCORE_THRESHOLD, AUTO_ACCEPT_THRESHOLD). Human review
#: optional; usually left to view.html's decision UI.
STATUS_NEEDS_REVIEW: str = "needs_review"

#: FaG strategy didn't run for this record (dry-run mode, or
#: pipeline short-circuited).
STATUS_NOT_RUN: str = "not_run"

#: DecisionPolicy output: the candidate list was empty. This
#: is a Decision.status (the policy's verdict), NOT a
#: PensionerRecord.status (the wire-format value the pipeline
#: emits). It can map to STATUS_NO_RESULTS at the record
#: boundary, but the strings are kept distinct because the
#: concepts are at different layers.
STATUS_NO_CANDIDATES: str = "no_candidates"

#: All Fag statuses that should trigger the follow-up phase
#: (per scripts/pipeline/leftover_investigation.py).
INVESTIGATE_FAG_STATUSES: frozenset[str] = frozenset({
    STATUS_AUTO_ACCEPT,
    STATUS_AMBIGUOUS,
    STATUS_TOO_MANY,
    STATUS_NO_RESULTS,
})


# ============================================================
# Helpers
# ============================================================

def derive_status(best_score: float, fag_status: str | None,
                  low_score_threshold: float = LOW_SCORE_THRESHOLD,
                  auto_accept_threshold: float = AUTO_ACCEPT_THRESHOLD) -> str:
    """Derive a canonical status from a best_score and a fag_status.

    Order matters: fag_status takes precedence (the production
    pipeline has already classified the record, so we trust it).
    Only when fag_status is missing/empty do we re-derive from
    best_score.

    For dry-run / state-replay paths that want to TEST a new
    threshold (ignoring whatever fag_status was previously set),
    use `derive_status_from_score_only` instead.
    """
    if fag_status:
        return fag_status
    return derive_status_from_score_only(
        best_score=best_score,
        low_score_threshold=low_score_threshold,
        auto_accept_threshold=auto_accept_threshold,
    )


def derive_status_from_score_only(
    best_score: float,
    low_score_threshold: float = LOW_SCORE_THRESHOLD,
    auto_accept_threshold: float = AUTO_ACCEPT_THRESHOLD,
) -> str:
    """Derive a canonical status from best_score alone.

    Ignores any existing fag_status on the record. Used by the
    dry-run + state-replay paths where the operator wants to
    classify as if the current threshold were applied fresh
    (so they can A/B test a new threshold against historical
    state).
    """
    if best_score >= auto_accept_threshold:
        return STATUS_AUTO_ACCEPT
    if best_score >= low_score_threshold:
        return STATUS_NEEDS_REVIEW
    return STATUS_LOW_SCORE
