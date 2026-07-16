"""Tests for F7: view.html unified state rendering.

view.html processes JSONL state files. There are now two state
formats:
  - FaG-only (legacy): {ranked_candidates, best_score, status, ...}
  - Unified (new):    {cgr_records, cgr_status,
                       fag_records, fag_status, cgr_skipped_fag,
                       both_match, ...}

We test the JS-side detection/normalization logic so that
view.html can correctly render either format.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.state_normalize import (
    normalize_state_record,
    is_unified,
    is_fag_only,
    extract_fag_candidates,
    extract_cgr_records,
    get_status,
    get_both_match,
)


# ============================================================
# Format detection
# ============================================================
def test_is_unified_true():
    """Has cgr_records + fag_records → unified."""
    rec = {"cgr_records": [], "fag_records": []}
    assert is_unified(rec) is True


def test_is_unified_false_for_legacy():
    """Has only ranked_candidates → legacy fag-only."""
    rec = {"ranked_candidates": []}
    assert is_unified(rec) is False


def test_is_fag_only_true():
    """Legacy records have ranked_candidates."""
    rec = {"ranked_candidates": [], "best_score": 0.5}
    assert is_fag_only(rec) is True


def test_is_fag_only_false_for_unified():
    rec = {"cgr_records": [], "fag_records": []}
    assert is_fag_only(rec) is False


# ============================================================
# Field extractors (handle both formats)
# ============================================================
def test_extract_fag_candidates_from_unified():
    """Unified records have fag_records."""
    rec = {
        "fag_records": [
            {"memorial_id": "1", "slug": "x-y", "score": 0.5, "name": "X Y"},
        ],
        "ranked_candidates": [],
    }
    cands = extract_fag_candidates(rec)
    assert len(cands) == 1
    assert cands[0]["memorial_id"] == "1"


def test_extract_fag_candidates_from_legacy():
    """Legacy records fall back to ranked_candidates."""
    rec = {"ranked_candidates": [{"memorial_id": "2", "score": 0.7}]}
    cands = extract_fag_candidates(rec)
    assert cands[0]["memorial_id"] == "2"


def test_extract_cgr_records_unified():
    rec = {
        "cgr_records": [
            {"cgr_id": "x", "match_strength": "strong"},
        ],
    }
    out = extract_cgr_records(rec)
    assert out[0]["match_strength"] == "strong"


def test_extract_cgr_records_empty_for_legacy():
    """Legacy records don't have cgr_records."""
    rec = {"ranked_candidates": []}
    assert extract_cgr_records(rec) == []


# ============================================================
# Normalization
# ============================================================
def test_normalize_unified_record():
    """Normalize a unified record to a single uniform shape."""
    rec = {
        "cgr_records": [{"cgr_id": "1", "match_strength": "strong"}],
        "fag_records": [{"memorial_id": "99", "score": 0.8}],
        "fag_status": "auto_accept",
        "cgr_skipped_fag": True,
        "both_match": {"method": "direct_link", "confidence": 1.0},
        "pensioner_id": 5,
    }
    out = normalize_state_record(rec)
    # Out should expose fields view.html expects
    assert "ranked_candidates" in out
    assert out["cgr_records"] == rec["cgr_records"]
    assert out["both_match"] == rec["both_match"]
    assert out["cgr_skipped_fag"] is True


def test_normalize_legacy_record():
    """Legacy record normalization → ranked_candidates preserved."""
    rec = {
        "ranked_candidates": [{"memorial_id": "5"}],
        "best_score": 0.7,
        "status": "auto_accept",
        "pensioner_id": 1,
    }
    out = normalize_state_record(rec)
    assert out["ranked_candidates"][0]["memorial_id"] == "5"
    # Unified fields are empty
    assert out.get("cgr_records", []) == []
    assert out.get("both_match") is None


def test_normalize_with_cgr_strong_skip():
    """When CGR strong skipped FaG, ranked_candidates is empty but
    both sources are present."""
    rec = {
        "cgr_records": [{"match_strength": "strong", "cgr_name": "X"}],
        "fag_records": [],
        "fag_status": "skipped_cgr_strong",
        "cgr_skipped_fag": True,
    }
    out = normalize_state_record(rec)
    assert out["cgr_skipped_fag"] is True
    assert out["ranked_candidates"] == []  # FaG skipped


# ============================================================
# Status helpers
# ============================================================
def test_get_status_unified():
    """Unified: use fag_status (or cgr_status if FaG skipped)."""
    rec = {"fag_status": "auto_accept", "cgr_status": "cgr_found"}
    assert get_status(rec) == "auto_accept"


def test_get_status_unified_skipped():
    """When FaG skipped, use cgr_status."""
    rec = {"fag_status": "skipped_cgr_strong", "cgr_status": "cgr_found"}
    assert get_status(rec) == "skipped_cgr_strong"


def test_get_status_legacy():
    rec = {"status": "ambiguous"}
    assert get_status(rec) == "ambiguous"


# ============================================================
# BOTH MATCH helpers
# ============================================================
def test_get_both_match_present():
    """Returns both_match field if present."""
    rec = {"both_match": {"method": "direct_link", "confidence": 1.0}}
    out = get_both_match(rec)
    assert out["method"] == "direct_link"


def test_get_both_match_absent():
    rec = {}
    assert get_both_match(rec) is None