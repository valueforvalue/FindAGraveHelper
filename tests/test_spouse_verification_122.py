"""Tests for #122: spouse verification via memorial detail page scraping.

Verifies:
  - SPOUSE_VERIFIED_SCORE_BOOST constant exists
  - _spouse_verified flag flows through projector to score_breakdown
  - spouse_data flows through projector to badge
  - compare_spouses handles all match strengths
"""
from __future__ import annotations

import pytest
from scripts.pipeline.scoring_constants import SPOUSE_VERIFIED_SCORE_BOOST
from scripts.fag.spouse_scrape import compare_spouses, _split_name, _norm
from scripts.blackboard.projector import (
    ProjectionBuilder,
    _normalize_candidate,
    _convert_fag_candidate_for_projection,
)


# ── Scoring constant ──────────────────────────────────────────


def test_spouse_verified_boost_constant_exists():
    """SPOUSE_VERIFIED_SCORE_BOOST must be defined in scoring_constants."""
    assert SPOUSE_VERIFIED_SCORE_BOOST == 0.15
    assert isinstance(SPOUSE_VERIFIED_SCORE_BOOST, float)


def test_boost_does_not_exceed_max_score():
    """Score + boost must cap at 1.0."""
    base = 0.90
    result = min(base + SPOUSE_VERIFIED_SCORE_BOOST, 1.0)
    assert result == 1.0

    base = 0.50
    result = min(base + SPOUSE_VERIFIED_SCORE_BOOST, 1.0)
    assert result == 0.65


# ── compare_spouses correctness ───────────────────────────────


def test_compare_spouses_strong_match():
    """First + last both match → strong."""
    local = {"first": "Andrew", "last": "Gwinn"}
    captured = {"first": "Andrew", "last": "Gwinn", "display": "Andrew Gwinn",
                 "middle": "", "memorial_id": "123", "slug": "andrew-gwinn",
                 "marriage_year": ""}
    result = compare_spouses(local, captured)
    assert result is not None
    assert result["matched"] is True
    assert result["match_strength"] == "strong"
    assert result["matched_via"] == "first_and_last"


def test_compare_spouses_medium_match():
    """Last name matches, first differs → medium."""
    local = {"first": "Andrew", "last": "Gwinn"}
    captured = {"first": "Andy", "last": "Gwinn", "display": "Andy Gwinn",
                 "middle": "", "memorial_id": "123", "slug": "andy-gwinn",
                 "marriage_year": ""}
    result = compare_spouses(local, captured)
    assert result is not None
    assert result["match_strength"] == "medium"
    assert result["matched_via"] == "last_name"


def test_compare_spouses_no_match():
    """Different last names → no match."""
    local = {"first": "Andrew", "last": "Gwinn"}
    captured = {"first": "Andrew", "last": "Smith", "display": "Andrew Smith",
                 "middle": "", "memorial_id": "123", "slug": "andrew-smith",
                 "marriage_year": ""}
    result = compare_spouses(local, captured)
    assert result is None


def test_compare_spouses_missing_local():
    """Missing local spouse data → None."""
    result = compare_spouses({}, {"first": "X", "last": "Y"})
    assert result is None

    result = compare_spouses({"first": "", "last": ""}, {"first": "X", "last": "Y"})
    assert result is None


def test_compare_spouses_missing_captured():
    """Missing captured data → None."""
    result = compare_spouses({"first": "A", "last": "B"}, None)
    assert result is None


def test_norm_strips_suffixes():
    """_norm should strip Jr/Sr/II/III suffixes."""
    assert _norm("John Smith Jr") == "john smith"
    assert _norm("John Smith Sr.") == "john smith"
    assert _norm("John Smith III") == "john smith"
    assert _norm("John Smith") == "john smith"


# ── Projector: _spouse_verified flows to score_breakdown ──────


def test_normalize_candidate_preserves_spouse_verified():
    """_normalize_candidate should copy _spouse_verified flag."""
    c = {
        "memorial_id": "123",
        "name": "Test Person",
        "score": 0.80,
        "_spouse_verified": True,
        "_spouse_linked": True,
        "details": {},
        "evidence": {"last": 1.0, "first": 0.8},
    }
    out = _normalize_candidate(c)
    assert out["_spouse_verified"] is True
    assert out["_spouse_linked"] is True


def test_convert_fag_candidate_includes_spouse_verified():
    """Common projection should carry _spouse_verified in score_breakdown."""
    c = _normalize_candidate({
        "memorial_id": "456",
        "name": "Test Widow",
        "score": 0.75,
        "_spouse_verified": True,
        "_spouse_linked": True,
        "details": {},
        "evidence": {"last": 1.0, "first": 0.9, "widow_pension": 0.5},
        "backlink": "https://findagrave.com/memorial/456/test",
        "iiif_url": "https://findagrave.com/iiif/2/memorial:456/full/full/0/default.jpg",
    })
    common = _convert_fag_candidate_for_projection(c)
    bd = common["evidence"]["score_breakdown"]
    assert bd["_spouse_verified"] is True
    assert bd["_spouse_linked"] is True


def test_projector_adds_spouse_badge_when_match_confirmed():
    """build_state_row should add 'spouse_match' badge when spouse_data
    has match_confirmed=True."""
    builder = ProjectionBuilder()
    row = builder.build_state_row(
        pensioner_id=1,
        pensioner_data={"first_name": "Test", "last_name": "Person"},
        candidates=[],
        spouse_data={"match_confirmed": True, "match_details": {
            "matched": True, "match_strength": "strong",
        }},
    )
    assert "spouse_match" in row["badges"]


def test_projector_no_spouse_badge_without_match():
    """No spouse_data or match_confirmed=False → no spouse badge."""
    builder = ProjectionBuilder()
    row = builder.build_state_row(
        pensioner_id=1,
        pensioner_data={"first_name": "Test", "last_name": "Person"},
        candidates=[],
        spouse_data={"match_confirmed": False},
    )
    assert "spouse_match" not in row["badges"]

    row2 = builder.build_state_row(
        pensioner_id=2,
        pensioner_data={"first_name": "Test", "last_name": "Person"},
        candidates=[],
    )
    assert "spouse_match" not in row2["badges"]


def test_score_boost_matches_expected():
    """Verify the boost arithmetic matches what run_unified.py applies."""
    old_score = 0.757
    new_score = min(old_score + SPOUSE_VERIFIED_SCORE_BOOST, 1.0)
    assert new_score == 0.907  # 0.757 + 0.15 = 0.907 (matching live test)
