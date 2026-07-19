"""Tests for rewritten FellegiSunterMatcher — Phase 3 Slice 3.5.

Tests actual m/u estimation, MatchModel versioning, save/load, and
per-feature explainability. Replaces tests/test_fellegi_sunter.py
which tested the LogisticRegression-based path.
"""
import tempfile
from pathlib import Path

import pytest

from scripts.matching.fellegi_sunter import (
    FellegiSunterMatcher,
    MatchModel,
)


def _p(first="John", last="Smith", birth="1840", regiment="5th Alabama"):
    return {
        "first_name": first,
        "last_name": last,
        "birth_year": birth,
        "regiment": regiment,
    }


def _c(first="John", last="Smith", born="1840", unit="5 AL Inf"):
    return {
        "first_name": first,
        "last_name": last,
        "born": born,
        "unit": unit,
    }


def test_train_on_synthetic_pairs():
    """Training on labeled pairs produces non-trivial m/u values."""
    matcher = FellegiSunterMatcher()
    pairs = [
        (_p("John", "Smith", "1840"), _c("John", "Smith", "1840"), True),
        (_p("John", "Smith", "1840"), _c("John", "Smith", "1841"), True),
        (_p("Robert", "Johnson", "1850"), _c("Robert", "Johnson", "1850"), True),
        (_p("John", "Smith", "1840"), _c("Robert", "Johnson", "1850"), False),
        (_p("William", "Brown", "1835"), _c("James", "Davis", "1845"), False),
    ]
    model = matcher.train(pairs)
    assert model is not None
    assert model.model_version == "1"
    assert model.training_pair_count == 5
    assert len(model.m_probs) == 5
    # m (match) should be higher than u (non-match) for name_similarity
    assert model.m_probs["name_similarity"] > model.u_probs["name_similarity"]


def test_predict_match_high_probability():
    """Matching pair gets high probability after training."""
    matcher = FellegiSunterMatcher()
    matcher.train([
        (_p("John", "Smith"), _c("John", "Smith"), True),
        (_p("John", "Smith"), _c("John", "Smith"), True),
        (_p("Bob", "Jones"), _c("Bob", "Jones"), False),
    ])
    prob, evidence = matcher.predict(_p("John", "Smith"), _c("John", "Smith"))
    assert prob >= 0.50
    assert "name_similarity" in evidence


def test_predict_nonmatch_low_probability():
    """Non-matching pair gets low probability."""
    matcher = FellegiSunterMatcher()
    matcher.train([
        (_p("John", "Smith"), _c("John", "Smith"), True),
        (_p("Robert", "Johnson"), _c("Robert", "Johnson"), True),
        (_p("Bob", "Jones"), _c("Sam", "Wilson"), False),
        (_p("Bob", "Jones"), _c("Sam", "Wilson"), False),
    ])
    prob, _ = matcher.predict(_p("Alice", "Williams"), _c("Bob", "Taylor"))
    assert prob < 0.50


def test_predict_untrained_returns_05():
    """Untrained matcher returns 0.5 probability."""
    matcher = FellegiSunterMatcher()
    prob, evidence = matcher.predict(_p(), _c())
    assert prob == 0.5
    assert evidence["reason"] == "untrained"


def test_explain_returns_per_feature_breakdown():
    """explain() gives per-feature weights."""
    matcher = FellegiSunterMatcher()
    matcher.train([
        (_p("John", "Smith"), _c("John", "Smith"), True),
        (_p("Bob", "Jones"), _c("Sam", "Wilson"), False),
    ])
    explanation = matcher.explain(_p("John", "Smith"), _c("John", "Smith"))
    assert "name_similarity" in explanation
    assert "birth_year_match" in explanation


def test_save_load_roundtrip():
    """Model survives save() -> load() roundtrip."""
    matcher = FellegiSunterMatcher()
    matcher.train([
        (_p("John", "Smith"), _c("John", "Smith"), True),
        (_p("Bob", "Jones"), _c("Sam", "Wilson"), False),
    ])

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "model.pkl"
        matcher.save(path)

        loaded = FellegiSunterMatcher.load(path)
        prob1, _ = matcher.predict(_p("John", "Smith"), _c("John", "Smith"))
        prob2, _ = loaded.predict(_p("John", "Smith"), _c("John", "Smith"))
        assert prob1 == prob2


def test_load_works_on_local_path():
    """load() accepts normal local filesystem paths."""
    matcher = FellegiSunterMatcher()
    matcher.train([
        (_p("John", "Smith"), _c("John", "Smith"), True),
    ])
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "model.pkl"
        matcher.save(path)
        loaded = FellegiSunterMatcher.load(path)
        assert loaded.is_trained
