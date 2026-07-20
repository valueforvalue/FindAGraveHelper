"""DecisionPolicy: single decision function for live, replay, and dry-run.

Eliminates the threshold drift between scripts/fag/search.py (0.70)
and scripts/pipeline/scoring_constants.py (0.85). One policy version
is recorded in every Decision so replay is faithful.

Public surface:
  - DecisionPolicy (dataclass)
  - classify(candidates, context) -> Decision
  - POLICY_VERSION_1 (canonical v1 thresholds)

Thresholds + status strings are imported from
scripts.pipeline.scoring_constants (issue #37). This module
keeps the prefixed names (FAG_AUTO_ACCEPT_THRESHOLD) and the
status names as re-exports for call-site readability, but the
canonical values live in scoring_constants.

DEPRECATION: the unprefixed names (AUTO_ACCEPT_THRESHOLD,
AUTO_ACCEPT_THRESHOLD_NO_DEATH, AUTO_ACCEPT_GAP) remain as
aliases for one release, emitting DeprecationWarning. They
will be removed in the next major version. New code should
use the FAG_-prefixed names.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

# ============================================================
# Canonical thresholds + statuses (issue #37)
# ============================================================
# Single source of truth: scripts.pipeline.scoring_constants.
# We import here so call sites can write either
#   from scripts.blackboard.decision_policy import FAG_AUTO_ACCEPT_THRESHOLD
# or
#   from scripts.pipeline.scoring_constants import FAG_AUTO_ACCEPT_THRESHOLD
# and get the same value.

from scripts.pipeline.scoring_constants import (  # noqa: F401
    FAG_AUTO_ACCEPT_THRESHOLD,
    FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH,
    FAG_AUTO_ACCEPT_GAP,
    LOW_SCORE_THRESHOLD,
    STATUS_AUTO_ACCEPT,
    STATUS_NEEDS_REVIEW,
    STATUS_LOW_SCORE,
    STATUS_NO_CANDIDATES,
    STATUS_ERROR,
    STATUS_AMBIGUOUS,
)


POLICY_VERSION_1 = "1"


# ============================================================
# Back-compat aliases (deprecated; will be removed)
# ============================================================
# The unprefixed names AUTO_ACCEPT_THRESHOLD / etc. are kept
# for one release as aliases. They emit DeprecationWarning on
# attribute access (not on import) so tests can pin the
# warning behaviour.

def __getattr__(name):
    """PEP 562 module-level __getattr__: emit DeprecationWarning
    when legacy names are accessed, then return the canonical
    value. Keeps existing callers compiling while signalling
    that the names are going away."""
    _legacy = {
        "AUTO_ACCEPT_THRESHOLD": FAG_AUTO_ACCEPT_THRESHOLD,
        "AUTO_ACCEPT_THRESHOLD_NO_DEATH": FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH,
        "AUTO_ACCEPT_GAP": FAG_AUTO_ACCEPT_GAP,
    }
    if name in _legacy:
        warnings.warn(
            f"scripts.blackboard.decision_policy.{name} is deprecated; "
            f"use FAG_AUTO_ACCEPT_THRESHOLD (or import from "
            f"scripts.pipeline.scoring_constants). The unprefixed name "
            f"is being removed in the next major version.",
            DeprecationWarning,
            stacklevel=2,
        )
        return _legacy[name]
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )


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
        else FAG_AUTO_ACCEPT_THRESHOLD
    )
    _auto_accept_no_death = (
        auto_accept_threshold_no_death
        if auto_accept_threshold_no_death is not None
        else FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH
    )
    _gap = auto_accept_gap if auto_accept_gap is not None else FAG_AUTO_ACCEPT_GAP
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
