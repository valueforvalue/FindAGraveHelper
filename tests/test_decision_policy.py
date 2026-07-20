"""Tests for scripts/blackboard/decision_policy.py — Phase 3 Slice 3.3."""

from scripts.blackboard.decision_policy import (
    # Issue #37: use the FAG_-prefixed names from scoring_constants.
    # The unprefixed names still work (deprecated) but emit warnings.
    FAG_AUTO_ACCEPT_GAP,
    FAG_AUTO_ACCEPT_THRESHOLD,
    FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH,
    LOW_SCORE_THRESHOLD,
    STATUS_AUTO_ACCEPT,
    STATUS_LOW_SCORE,
    STATUS_NEEDS_REVIEW,
    STATUS_NO_CANDIDATES,
    Decision,
    DecisionContext,
    classify,
)


def _cand(score: float, memorial_id: str = "1") -> dict:
    return {"memorial_id": memorial_id, "score": score}


# ============================================================
# No candidates
# ============================================================


def test_no_candidates():
    """Empty candidate list -> no_candidates."""
    ctx = DecisionContext(candidates=[])
    d = classify(ctx)
    assert d.status == STATUS_NO_CANDIDATES


# ============================================================
# Low score
# ============================================================


def test_low_score_below_floor():
    """Score below LOW_SCORE_THRESHOLD -> low_score."""
    ctx = DecisionContext(candidates=[_cand(0.30)])
    d = classify(ctx)
    assert d.status == STATUS_LOW_SCORE


# ============================================================
# Auto-accept: single candidate
# ============================================================


def test_single_candidate_auto_accept_with_death():
    """Single candidate >= FAG_AUTO_ACCEPT_THRESHOLD with death year -> auto_accept."""
    ctx = DecisionContext(
        candidates=[_cand(0.80)],
        local_death_year="1890",
    )
    d = classify(ctx)
    assert d.status == STATUS_AUTO_ACCEPT
    assert d.threshold_used == FAG_AUTO_ACCEPT_THRESHOLD


def test_single_candidate_auto_accept_no_death():
    """Single candidate >= FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH without death -> auto_accept."""
    ctx = DecisionContext(
        candidates=[_cand(0.65)],
        local_death_year=None,
    )
    d = classify(ctx)
    assert d.status == STATUS_AUTO_ACCEPT
    assert d.threshold_used == FAG_AUTO_ACCEPT_THRESHOLD_NO_DEATH


# ============================================================
# Auto-accept: multiple candidates with gap
# ============================================================


def test_multi_candidate_auto_accept_with_gap():
    """Top >= threshold with sufficient gap -> auto_accept."""
    ctx = DecisionContext(
        candidates=[_cand(0.85), _cand(0.60)],
        local_death_year="1890",
    )
    d = classify(ctx)
    assert d.status == STATUS_AUTO_ACCEPT
    assert d.gap == pytest.approx(0.25)


def test_multi_candidate_no_gap_needs_review():
    """Top >= threshold but gap too small -> needs_review."""
    ctx = DecisionContext(
        candidates=[_cand(0.85), _cand(0.84)],
        local_death_year="1890",
    )
    d = classify(ctx)
    assert d.status == STATUS_NEEDS_REVIEW


# ============================================================
# Truncation forces review
# ============================================================


def test_truncation_forces_review():
    """Even high score with truncation -> needs_review."""
    ctx = DecisionContext(
        candidates=[_cand(0.99)],
        local_death_year="1890",
        truncation_observed=True,
    )
    d = classify(ctx)
    assert d.status == STATUS_NEEDS_REVIEW


def test_parser_warning_forces_review():
    """Even high score with parser warnings -> needs_review."""
    ctx = DecisionContext(
        candidates=[_cand(0.99)],
        parser_warnings=True,
    )
    d = classify(ctx)
    assert d.status == STATUS_NEEDS_REVIEW


# ============================================================
# Decision serialization
# ============================================================


def test_decision_to_dict():
    """Decision.to_dict() includes policy_version."""
    d = Decision(status=STATUS_AUTO_ACCEPT, top_score=0.80, reason="test")
    out = d.to_dict()
    assert out["status"] == STATUS_AUTO_ACCEPT
    assert out["policy_version"] == "1"
    assert out["top_score"] == 0.80


# ============================================================
# Parity: live vs replay produce same verdict
# ============================================================


def test_same_evidence_same_verdict():
    """Two classify() calls with identical context produce identical decisions."""
    ctx = DecisionContext(
        candidates=[_cand(0.88), _cand(0.50)],
        local_death_year="1845",
    )
    d1 = classify(ctx)
    d2 = classify(ctx)
    assert d1.status == d2.status
    assert d1.top_score == d2.top_score


import pytest
