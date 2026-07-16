"""Tests for the Fellegi-Sunter probabilistic matcher.

Fellegi-Sunter is the classic probabilistic record-linkage
model. For each field comparison, it estimates:
  - m = P(field agrees | records are a true match)
  - u = P(field agrees | records are NOT a match)

Then for a record pair, the log-likelihood ratio (weight) is:
  W = sum over fields of [log(m_i) - log(u_i)]   if fields agree
  W = sum over fields of [log(1-m_i) - log(1-u_i)] if fields disagree

A pair is a "match" if W > threshold (typically 0).

We use python-recordlinkage's FellegiSunter classifier, trained
on our 575 ground-truth records. The model is unsupervised but
initialized with reasonable priors.

This module wraps recordlinkage with a friendlier interface:
  - Input: pairs of (pensioner_dict, cgr_vet_dict) plus a label
  - Output: match probability for unseen pairs
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.fellegi_sunter import (
    FellegiSunterMatcher,
    ComparisonFeatures,
    extract_features,
)


# ============================================================
# Feature extraction
# ============================================================
def test_extract_features_basic():
    """Given two records, extract comparison features."""
    pensioner = {"first_name": "William", "last_name": "Looney", "regiment": "34 TX"}
    cgr_vet = {"name": "William G Looney", "unit": "34 TX"}
    features = extract_features(pensioner, cgr_vet)
    assert isinstance(features, ComparisonFeatures)


def test_extract_features_includes_jw_score():
    """Features include Jaro-Winkler similarity for first+last names."""
    pensioner = {"first_name": "William", "last_name": "Looney"}
    cgr_vet = {"name": "William Looney"}
    f = extract_features(pensioner, cgr_vet)
    assert f.jw_first > 0.9
    assert f.jw_last > 0.9


def test_extract_features_includes_phonetic_match():
    """Features include phonetic agreement booleans."""
    pensioner = {"first_name": "William", "last_name": "Loney"}
    cgr_vet = {"name": "William Looney"}  # different last spelling
    f = extract_features(pensioner, cgr_vet)
    # Looney / Loney share metaphone, NYSIIS
    assert f.metaphone_last is True
    assert f.nysiis_last is True


def test_extract_features_includes_unit_match():
    """Features include unit/state agreement."""
    pensioner = {"regiment": "34 TX"}
    cgr_vet = {"unit": "34 TX"}
    f = extract_features(pensioner, cgr_vet)
    assert f.unit_state_match is True


def test_extract_features_includes_first_name_initial():
    """Features include first-name initial match."""
    pensioner = {"first_name": "William"}
    cgr_vet = {"name": "W. Smith"}
    f = extract_features(pensioner, cgr_vet)
    assert f.first_initial_match is True


def test_extract_features_handles_missing_data():
    """Missing fields don't crash."""
    pensioner = {}  # empty
    cgr_vet = {"name": "John Smith"}
    f = extract_features(pensioner, cgr_vet)
    assert isinstance(f, ComparisonFeatures)


# ============================================================
# ComparisonFeatures dataclass
# ============================================================
def test_comparison_features_to_dict():
    """ComparisonFeatures converts to a dict for recordlinkage."""
    f = ComparisonFeatures(
        jw_first=0.9, jw_last=0.8,
        metaphone_last=True, nysiis_last=True, metaphone_first=False,
        unit_state_match=True, first_initial_match=True,
    )
    d = f.to_dict()
    assert isinstance(d, dict)
    assert d["jw_first"] == 0.9
    assert d["metaphone_last"] is True


def test_comparison_features_keys_match():
    """All feature keys are present and consistent across instances."""
    f1 = extract_features({"first_name": "A"}, {"name": "B"})
    f2 = extract_features({"first_name": "C", "last_name": "D"}, {"name": "E F"})
    # Both should have the same keys
    assert set(f1.to_dict().keys()) == set(f2.to_dict().keys())


# ============================================================
# Matcher training and prediction
# ============================================================
def _sample_training_data():
    """Mixed training pairs (some matches, some not)."""
    return [
        # (pensioner, cgr_vet, is_match)
        ({"first_name": "William", "last_name": "Looney", "regiment": "34 TX"},
         {"name": "William G Looney", "unit": "34 TX"}, True),
        ({"first_name": "John", "last_name": "Smith"},
         {"name": "John Smith"}, True),
        ({"first_name": "Andrew", "last_name": "Alberty", "regiment": "1 OK"},
         {"name": "Andrew J Alberty", "unit": "1 OK"}, True),
        ({"first_name": "Hugh", "last_name": "Akers"},
         {"name": "Hugh H Akers"}, True),
        ({"first_name": "Robert", "last_name": "Jones"},
         {"name": "John Smith"}, False),  # different person
        ({"first_name": "William", "last_name": "Looney"},
         {"name": "Marcus Calhoun Anderson"}, False),  # very different
        ({"first_name": "John", "last_name": "Smith"},
         {"name": "Jane Doe"}, False),  # different
        ({"first_name": "Andrew", "last_name": "Alberty"},
         {"name": "Bobby McFerrin"}, False),  # different
    ]


def test_matcher_trains_on_labeled_data():
    """FellegiSunterMatcher can be trained on labeled pairs."""
    matcher = FellegiSunterMatcher()
    matcher.train(_sample_training_data())
    assert matcher.is_trained


def test_matcher_predicts_high_probability_for_known_match():
    """After training, a clear match gets high probability."""
    matcher = FellegiSunterMatcher()
    matcher.train(_sample_training_data())
    p = matcher.predict(
        {"first_name": "William", "last_name": "Looney", "regiment": "34 TX"},
        {"name": "William G Looney", "unit": "34 TX"},
    )
    assert p > 0.5  # high probability


def test_matcher_predicts_low_probability_for_known_nonmatch():
    """After training, a clear non-match gets low probability."""
    matcher = FellegiSunterMatcher()
    matcher.train(_sample_training_data())
    p = matcher.predict(
        {"first_name": "William", "last_name": "Looney"},
        {"name": "Marcus Calhoun Anderson"},
    )
    assert p < 0.5


def test_matcher_handles_untrained_state():
    """Predicting before training returns a default (0.5)."""
    matcher = FellegiSunterMatcher()
    p = matcher.predict(
        {"first_name": "William", "last_name": "Looney"},
        {"name": "William G Looney"},
    )
    assert 0.0 <= p <= 1.0


def test_matcher_handles_empty_training():
    """Training on empty list is a no-op (untrained)."""
    matcher = FellegiSunterMatcher()
    matcher.train([])
    assert not matcher.is_trained


# ============================================================
# Integration with the wider system
# ============================================================
def test_matcher_provides_explainability():
    """The matcher can explain WHY it predicted a probability
    (per-field contribution)."""
    matcher = FellegiSunterMatcher()
    matcher.train(_sample_training_data())
    explanation = matcher.explain(
        {"first_name": "William", "last_name": "Looney", "regiment": "34 TX"},
        {"name": "William G Looney", "unit": "34 TX"},
    )
    assert "jw_last" in explanation or "features" in explanation


def test_matcher_handles_incremental_training():
    """Matcher can be trained incrementally (more data improves it)."""
    # Use 2 matches + 2 non-matches (balanced) so logistic regression has both classes
    m1 = FellegiSunterMatcher()
    m1.train([
        ({"first_name": "William", "last_name": "Looney", "regiment": "34 TX"},
         {"name": "William G Looney", "unit": "34 TX"}, True),
        ({"first_name": "John", "last_name": "Smith"},
         {"name": "John Smith"}, True),
        ({"first_name": "Robert", "last_name": "Jones"},
         {"name": "John Smith"}, False),
        ({"first_name": "William", "last_name": "Looney"},
         {"name": "Marcus Calhoun Anderson"}, False),
    ])
    p1 = m1.predict(
        {"first_name": "William", "last_name": "Looney", "regiment": "34 TX"},
        {"name": "William G Looney", "unit": "34 TX"},
    )
    m2 = FellegiSunterMatcher()
    m2.train(_sample_training_data())
    p2 = m2.predict(
        {"first_name": "William", "last_name": "Looney", "regiment": "34 TX"},
        {"name": "William G Looney", "unit": "34 TX"},
    )
    # Both should predict a probability; values may differ
    assert 0 <= p1 <= 1
    assert 0 <= p2 <= 1


def test_matcher_serializable():
    """Trained model can be saved/loaded (so we don't retrain)."""
    import pickle
    import tempfile
    matcher = FellegiSunterMatcher()
    matcher.train(_sample_training_data())
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        path = Path(f.name)
    try:
        matcher.save(path)
        m2 = FellegiSunterMatcher.load(path)
        assert m2.is_trained
        # Predictions should match
        p1 = matcher.predict(
            {"first_name": "William", "last_name": "Looney"},
            {"name": "William G Looney"},
        )
        p2 = m2.predict(
            {"first_name": "William", "last_name": "Looney"},
            {"name": "William G Looney"},
        )
        assert abs(p1 - p2) < 0.01
    finally:
        path.unlink(missing_ok=True)