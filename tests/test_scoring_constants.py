"""Tests for scripts/pipeline/scoring_constants.py.

Issue #28 follow-up: extract the magic thresholds and status
strings into one place so dry_run.py and production code can
never drift.
"""
from __future__ import annotations

import pytest

from scripts.pipeline.scoring_constants import (
    AUTO_ACCEPT_THRESHOLD,
    LOW_SCORE_THRESHOLD,
    STATUS_AUTO_ACCEPT,
    STATUS_AMBIGUOUS,
    STATUS_TOO_MANY,
    STATUS_NO_RESULTS,
    STATUS_ERROR,
    STATUS_LOW_SCORE,
    STATUS_NEEDS_REVIEW,
    STATUS_NOT_RUN,
    INVESTIGATE_FAG_STATUSES,
    derive_status,
    derive_status_from_score_only,
)


# ============================================================
# Threshold constants
# ============================================================

def test_auto_accept_threshold_is_0_85():
    """The production FaG strategy uses 0.85 as the strong-match
    cutoff (see scripts/pipeline/core.py docstring). Changing this
    here without updating the production strategy would cause
    dry-run to disagree with live runs."""
    assert AUTO_ACCEPT_THRESHOLD == 0.85


def test_low_score_threshold_is_0_40():
    """The CLI default for --low-score-threshold is 0.40. Same
    drift concern as AUTO_ACCEPT_THRESHOLD."""
    assert LOW_SCORE_THRESHOLD == 0.40


def test_thresholds_are_in_order():
    """Sanity check: low_score < auto_accept. If this fails, the
    scoring bands don't make sense."""
    assert LOW_SCORE_THRESHOLD < AUTO_ACCEPT_THRESHOLD


# ============================================================
# Status string constants
# ============================================================

def test_status_strings_have_canonical_values():
    """The status string values are part of the wire format
    (state.jsonl + view.html + the JS normalizer). They must
    not change without a coordinated update across layers."""
    assert STATUS_AUTO_ACCEPT == "auto_accept"
    assert STATUS_AMBIGUOUS == "ambiguous"
    assert STATUS_TOO_MANY == "too_many"
    assert STATUS_NO_RESULTS == "no_results"
    assert STATUS_ERROR == "error"
    assert STATUS_LOW_SCORE == "low_score"
    assert STATUS_NEEDS_REVIEW == "needs_review"
    assert STATUS_NOT_RUN == "not_run"


def test_investigate_fag_statuses_includes_relevant_set():
    """Per scripts/pipeline/leftover_investigation.py:79, the
    follow-up phase investigates records with fag_status in
    {auto_accept, ambiguous, too_many, no_results}. The set
    must stay in sync with the consumer's check."""
    assert "auto_accept" in INVESTIGATE_FAG_STATUSES
    assert "ambiguous" in INVESTIGATE_FAG_STATUSES
    assert "too_many" in INVESTIGATE_FAG_STATUSES
    assert "no_results" in INVESTIGATE_FAG_STATUSES
    assert "error" not in INVESTIGATE_FAG_STATUSES
    assert "low_score" not in INVESTIGATE_FAG_STATUSES


# ============================================================
# derive_status()
# ============================================================

def test_derive_status_trusts_fag_status_when_present():
    """Production has already classified the record; defer to it."""
    assert derive_status(0.5, STATUS_NO_RESULTS) == STATUS_NO_RESULTS
    assert derive_status(0.95, STATUS_AUTO_ACCEPT) == STATUS_AUTO_ACCEPT
    assert derive_status(0.3, STATUS_TOO_MANY) == STATUS_TOO_MANY


def test_derive_status_falls_back_to_score_when_no_fag_status():
    """Dry-run path: no fag_status, derive from best_score alone."""
    assert derive_status(0.95, None) == STATUS_AUTO_ACCEPT
    assert derive_status(0.85, None) == STATUS_AUTO_ACCEPT  # boundary
    assert derive_status(0.50, None) == STATUS_NEEDS_REVIEW
    assert derive_status(0.40, None) == STATUS_NEEDS_REVIEW  # boundary
    assert derive_status(0.39, None) == STATUS_LOW_SCORE
    assert derive_status(0.0, None) == STATUS_LOW_SCORE


def test_derive_status_with_empty_string_fag_status():
    """An empty string is falsy — should be treated as missing."""
    assert derive_status(0.95, "") == STATUS_AUTO_ACCEPT
    assert derive_status(0.5, "") == STATUS_NEEDS_REVIEW


def test_derive_status_respects_custom_thresholds():
    """Operators can pass tighter thresholds (e.g. for a stricter
    v6 strategy). The function honors them without hardcoding."""
    assert derive_status(0.90, None, low_score_threshold=0.30) == STATUS_AUTO_ACCEPT
    assert derive_status(0.60, None, low_score_threshold=0.30) == STATUS_NEEDS_REVIEW
    assert derive_status(0.20, None, low_score_threshold=0.30) == STATUS_LOW_SCORE


def test_derive_status_threshold_boundaries():
    """0.85 exactly -> auto_accept (>= boundary inclusive).
    0.40 exactly -> needs_review (>= boundary inclusive).
    0.39 -> low_score."""
    assert derive_status(AUTO_ACCEPT_THRESHOLD, None) == STATUS_AUTO_ACCEPT
    assert derive_status(LOW_SCORE_THRESHOLD, None) == STATUS_NEEDS_REVIEW
    just_below_auto = AUTO_ACCEPT_THRESHOLD - 0.001
    just_below_low = LOW_SCORE_THRESHOLD - 0.001
    assert derive_status(just_below_auto, None) == STATUS_NEEDS_REVIEW
    assert derive_status(just_below_low, None) == STATUS_LOW_SCORE


# ============================================================
# derive_status_from_score_only()
# ============================================================

def test_score_only_ignores_fag_status():
    """The score-only path is for dry-run / state-replay where
    the operator wants to test a new threshold against historical
    state, ignoring whatever the original pipeline classified."""
    assert derive_status_from_score_only(0.95) == STATUS_AUTO_ACCEPT
    # Even if fag_status was set to something non-canonical, the
    # score-only path doesn't see it.
    assert derive_status_from_score_only(0.95) == STATUS_AUTO_ACCEPT  # score wins


def test_score_only_boundary_conditions():
    """Same boundaries as derive_status (no fag_status path)."""
    assert derive_status_from_score_only(AUTO_ACCEPT_THRESHOLD) == STATUS_AUTO_ACCEPT
    assert derive_status_from_score_only(LOW_SCORE_THRESHOLD) == STATUS_NEEDS_REVIEW
    assert derive_status_from_score_only(AUTO_ACCEPT_THRESHOLD - 0.001) == STATUS_NEEDS_REVIEW
    assert derive_status_from_score_only(LOW_SCORE_THRESHOLD - 0.001) == STATUS_LOW_SCORE


def test_score_only_with_custom_thresholds():
    assert derive_status_from_score_only(0.90, low_score_threshold=0.30) == STATUS_AUTO_ACCEPT
    assert derive_status_from_score_only(0.60, low_score_threshold=0.30) == STATUS_NEEDS_REVIEW
    assert derive_status_from_score_only(0.20, low_score_threshold=0.30) == STATUS_LOW_SCORE


def test_derive_status_falls_back_to_score_only_when_fag_missing():
    """When fag_status is None/empty, derive_status delegates to
    derive_status_from_score_only. The two paths should agree
    for the same (score, threshold) inputs."""
    for score, low, auto in [
        (0.95, 0.40, 0.85),
        (0.60, 0.40, 0.85),
        (0.20, 0.40, 0.85),
        (0.85, 0.40, 0.85),  # boundary
    ]:
        from_fag = derive_status(score, None, low_score_threshold=low, auto_accept_threshold=auto)
        from_score = derive_status_from_score_only(score, low_score_threshold=low, auto_accept_threshold=auto)
        assert from_fag == from_score, (
            f"derive_status and derive_status_from_score_only "
            f"disagree for score={score}: {from_fag} vs {from_score}"
        )
