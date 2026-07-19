"""Tests for Phase 3 remaining slices."""

from scripts.matching.name_evidence import NameEvidence
from scripts.matching.candidate_scorer import CandidateScorer, CandidateScore
from scripts.cgr.match_evidence import (
    CGRMatchEvidence,
    MatchStrength,
    MATCH_STRONG,
    MATCH_MEDIUM,
    MATCH_WEAK,
    MATCH_NONE,
)
from scripts.evaluation import ScoringEvaluator, EvalResult, EvalSummary


# ============================================================
# NameEvidence
# ============================================================


def test_name_evidence_normalization():
    """Names are normalized: lowercase, no punctuation."""
    n = NameEvidence.from_record({"first_name": "John", "last_name": "O'Brien-Smith"})
    assert n.first_normalized == "john"
    assert n.last_normalized == "obriensmith"


def test_name_evidence_variants():
    """Common nicknames are expanded."""
    n = NameEvidence.from_record({"first_name": "William", "last_name": "Smith"})
    assert "will" in n.first_variants
    assert "bill" in n.first_variants


def test_name_evidence_slug_shape():
    """Slug matches FaG memorial URL format."""
    n = NameEvidence.from_record({"first_name": "John", "last_name": "Smith"})
    assert n.slug_shape == "john-smith"


def test_fuzzy_match_exact():
    """Exact name match returns high score."""
    a = NameEvidence.from_record({"first_name": "John", "last_name": "Smith"})
    b = NameEvidence.from_record({"first_name": "John", "last_name": "Smith"})
    assert a.fuzzy_match(b) >= 0.85


def test_fuzzy_match_nickname():
    """Nickname variant match is detected."""
    a = NameEvidence.from_record({"first_name": "William", "last_name": "Smith"})
    b = NameEvidence.from_record({"first_name": "Bill", "last_name": "Smith"})
    # Should match via nickname table
    assert a.fuzzy_match(b) >= 0.70


def test_fuzzy_match_different():
    """Completely different names score low."""
    a = NameEvidence.from_record({"first_name": "John", "last_name": "Smith"})
    b = NameEvidence.from_record({"first_name": "Robert", "last_name": "Johnson"})
    assert a.fuzzy_match(b) < 0.30


def test_fuzzy_match_initial():
    """Initial matches full name."""
    a = NameEvidence.from_record({"first_name": "J", "last_name": "Smith"})
    b = NameEvidence.from_record({"first_name": "John", "last_name": "Smith"})
    score = a.fuzzy_match(b)
    assert score >= 0.50  # last name exact + initial match


# ============================================================
# CandidateScorer
# ============================================================


def test_candidate_scorer_returns_version():
    """Scorer produces versioned CandidateScores."""
    scorer = CandidateScorer()
    local = {"first_name": "John", "last_name": "Smith"}
    cand = {"memorial_id": "123", "slug": "john-smith"}
    result = scorer.score(local, cand)
    assert result.scorer_version == "1"
    assert result.memorial_id == "123"


def test_candidate_scorer_batch():
    """score_all sorts by score descending."""
    scorer = CandidateScorer()
    local = {"first_name": "John", "last_name": "Smith"}
    candidates = [
        {"memorial_id": "1", "slug": "john-smith"},
        {"memorial_id": "2", "slug": "bob-jones"},
    ]
    results = scorer.score_all(local, candidates)
    assert len(results) == 2
    assert results[0].score >= results[1].score


# ============================================================
# CGRMatchEvidence
# ============================================================


def test_cgr_strong_match():
    """Same name + same birth year + same unit -> strong."""
    ev = CGRMatchEvidence()
    p = {"first_name": "John", "last_name": "Smith", "birth_year": "1840",
         "regiment": "5th Alabama", "_state_abbr": "AL"}
    c = {"first_name": "John", "last_name": "Smith", "born": "1840",
         "unit": "5 AL Inf", "state": "AL"}
    result = ev.match_strength(p, c)
    assert result.strength == MATCH_STRONG


def test_cgr_weak_match():
    """Different names + different years -> weak/none."""
    ev = CGRMatchEvidence()
    p = {"first_name": "John", "last_name": "Smith", "birth_year": "1840"}
    c = {"first_name": "Robert", "last_name": "Johnson", "born": "1850"}
    result = ev.match_strength(p, c)
    assert result.strength in (MATCH_WEAK, MATCH_NONE)


def test_cgr_year_conflict_demotes():
    """Year conflict demotes strong -> medium."""
    ev = CGRMatchEvidence()
    p = {"first_name": "John", "last_name": "Smith", "birth_year": "1840"}
    c = {"first_name": "John", "last_name": "Smith", "born": "1860"}
    result = ev.match_strength(p, c)
    assert result.year_conflict is True
    assert result.strength != MATCH_STRONG


def test_cgr_same_person():
    """same_person returns True for strong matches."""
    ev = CGRMatchEvidence()
    p = {"first_name": "John", "last_name": "Smith", "birth_year": "1840",
         "regiment": "5th Alabama", "_state_abbr": "AL"}
    c = {"first_name": "John", "last_name": "Smith", "born": "1840",
         "unit": "5 AL", "state": "AL"}
    assert ev.same_person(p, c) is True


# ============================================================
# ScoringEvaluator
# ============================================================


def test_evaluator_empty():
    """Empty records returns empty results."""
    evaluator = ScoringEvaluator()
    results, summary = evaluator.evaluate([])
    assert summary.total == 0


def test_evaluator_with_records():
    """Evaluator scores and classifies records."""
    evaluator = ScoringEvaluator()
    records = [
        {
            "pensioner_id": 1,
            "first_name": "John", "last_name": "Smith",
            "fag_records": [
                {"memorial_id": "123", "slug": "john-smith", "score": 0.90}
            ],
        }
    ]
    results, summary = evaluator.evaluate(records)
    assert len(results) == 1
    assert results[0].pensioner_id == 1
    assert summary.total == 1
