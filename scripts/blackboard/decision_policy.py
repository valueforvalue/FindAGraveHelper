"""DecisionPolicy: single decision function for live, replay, and dry-run.

Eliminates the threshold drift between scripts/fag/search.py (0.70)
and scripts/pipeline/scoring_constants.py (0.85). One policy version
is recorded in every Decision so replay is faithful.

Public surface:
  - DecisionPolicy (dataclass)
  - classify(candidates, context) -> Decision
  - POLICY_VERSION_1 (canonical v1 thresholds)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ============================================================
# Canonical thresholds — single source of truth
# ============================================================

POLICY_VERSION_1 = "1"

#: Top score must reach this for auto-accept when death year is known.
AUTO_ACCEPT_THRESHOLD: float = 0.70

#: Top score must reach this for auto-accept when death year is missing.
AUTO_ACCEPT_THRESHOLD_NO_DEATH: float = 0.60

#: Top candidate must beat #2 by this gap for auto-accept with multiple
#: candidates.
AUTO_ACCEPT_GAP: float = 0.10

#: Scores below this are classified as low_score (needs human review).
LOW_SCORE_THRESHOLD: float = 0.40


# ============================================================
# Status constants
# ============================================================

STATUS_AUTO_ACCEPT = "auto_accept"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_LOW_SCORE = "low_score"
STATUS_NO_CANDIDATES = "no_candidates"
STATUS_ERROR = "error"
STATUS_AMBIGUOUS = "ambiguous"


# ============================================================
# Decision
# ============================================================


@dataclass
class Decision:
    """Single verdict produced by the decision policy.

    Carries policy_version so replay can attribute decisions to a
    specific policy — even if thresholds change later.
    """

    status: str
    policy_version: str = POLICY_VERSION_1
    top_score: float = 0.0
    second_score: float = 0.0
    candidate_count: int = 0
    gap: float = 0.0
    threshold_used: float = 0.0
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "policy_version": self.policy_version,
            "top_score": self.top_score,
            "second_score": self.second_score,
            "candidate_count": self.candidate_count,
            "gap": self.gap,
            "threshold_used": self.threshold_used,
            "reason": self.reason,
        }


# ============================================================
# Classify
# ============================================================


@dataclass
class DecisionContext:
    """Input context for the decision policy.

    All fields are optional — the policy handles missing data.
    """

    candidates: list[dict[str, Any]] = field(default_factory=list)
    local_death_year: str | None = None
    truncation_observed: bool = False
    parser_warnings: bool = False
    provider_warnings: bool = False
    request_budget_exhausted: bool = False


def classify(
    context: DecisionContext,
    policy_version: str = POLICY_VERSION_1,
    *,
    auto_accept_threshold: float | None = None,
    auto_accept_threshold_no_death: float | None = None,
    auto_accept_gap: float | None = None,
    low_score_threshold: float | None = None,
) -> Decision:
    """Classify a set of scored candidates into a decision.

    This is the single entry point for live search, replay, and
    dry-run. All paths use the same thresholds and logic.

    Args:
        context: scored candidates + metadata about the search.
        policy_version: which policy version to apply (default "1").

    Returns:
        Decision with status, scores, gap, and rationale.
    """
    candidates = context.candidates

    # No candidates
    if not candidates:
        return Decision(
            status=STATUS_NO_CANDIDATES,
            policy_version=policy_version,
            reason="No candidates returned.",
        )

    # Sort by score descending
    sorted_candidates = sorted(
        candidates,
        key=lambda c: c.get("score", 0.0),
        reverse=True,
    )
    top = sorted_candidates[0]
    top_score = float(top.get("score", 0.0))
    second_score = float(sorted_candidates[1].get("score", 0.0)) if len(sorted_candidates) > 1 else 0.0
    gap = top_score - second_score

    # Determine threshold based on death-year availability
    has_death = bool(context.local_death_year and context.local_death_year != "0")
    _auto_accept = (
        auto_accept_threshold
        if auto_accept_threshold is not None
        else AUTO_ACCEPT_THRESHOLD
    )
    _auto_accept_no_death = (
        auto_accept_threshold_no_death
        if auto_accept_threshold_no_death is not None
        else AUTO_ACCEPT_THRESHOLD_NO_DEATH
    )
    _gap = auto_accept_gap if auto_accept_gap is not None else AUTO_ACCEPT_GAP
    _low_score = (
        low_score_threshold if low_score_threshold is not None else LOW_SCORE_THRESHOLD
    )
    threshold = _auto_accept if has_death else _auto_accept_no_death

    # Low score — doesn't reach the floor
    if top_score < _low_score:
        return Decision(
            status=STATUS_LOW_SCORE,
            policy_version=policy_version,
            top_score=top_score,
            second_score=second_score,
            candidate_count=len(candidates),
            gap=gap,
            threshold_used=threshold,
            reason=f"Top score {top_score:.3f} below low-score floor {_low_score}.",
        )

    # Truncation/parser warnings — force human review regardless of score
    if context.truncation_observed or context.parser_warnings:
        return Decision(
            status=STATUS_NEEDS_REVIEW,
            policy_version=policy_version,
            top_score=top_score,
            second_score=second_score,
            candidate_count=len(candidates),
            gap=gap,
            threshold_used=threshold,
            reason="Truncation or parser warning; human review required.",
        )

    # Single candidate with sufficient score
    if len(candidates) == 1 and top_score >= threshold:
        return Decision(
            status=STATUS_AUTO_ACCEPT,
            policy_version=policy_version,
            top_score=top_score,
            second_score=second_score,
            candidate_count=1,
            gap=gap,
            threshold_used=threshold,
            reason=f"Single candidate with score {top_score:.3f} >= {threshold}.",
        )

    # Multiple candidates — require gap
    if top_score >= threshold and gap >= _gap:
        return Decision(
            status=STATUS_AUTO_ACCEPT,
            policy_version=policy_version,
            top_score=top_score,
            second_score=second_score,
            candidate_count=len(candidates),
            gap=gap,
            threshold_used=threshold,
            reason=f"Top score {top_score:.3f} >= {threshold} with gap {gap:.3f} >= {_gap}.",
        )

    # Ambiguous — score above low but below auto-accept, or gap too small
    if top_score >= _low_score:
        return Decision(
            status=STATUS_NEEDS_REVIEW,
            policy_version=policy_version,
            top_score=top_score,
            second_score=second_score,
            candidate_count=len(candidates),
            gap=gap,
            threshold_used=threshold,
            reason=(
                f"Score {top_score:.3f} in review range or gap {gap:.3f} insufficient."
            ),
        )

    # Fallback
    return Decision(
        status=STATUS_NEEDS_REVIEW,
        policy_version=policy_version,
        top_score=top_score,
        second_score=second_score,
        candidate_count=len(candidates),
        gap=gap,
        threshold_used=threshold,
        reason="Fallback: does not meet any auto-accept criteria.",
    )
