"""Tests for F6: BOTH MATCH detector.

Detects when CGR and FaG both point to the same person.
Two match methods:

  - Direct link:  CGR record has a findagrave.com URL pointing
                  to a specific memorial that FaG also found.
  - Corroboration: CGR + FaG agree on a person by inference —
                  name match + death year (within ±2) + burial
                  state OK.

The detector returns a BOTH MATCH struct for view.html to
display, with the method clearly labeled.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.matching.both_match import (
    detect_both_match,
    BothMatchResult,
    MatchMethod,
    corroborate,
    check_direct_link,
)


# ============================================================
# MatchMethod enum
# ============================================================
def test_match_method_enum_has_both_methods():
    """MatchMethod has DIRECT_LINK and CORROBORATION."""
    assert hasattr(MatchMethod, "DIRECT_LINK")
    assert hasattr(MatchMethod, "CORROBORATION")
    assert hasattr(MatchMethod, "NONE")


# ============================================================
# check_direct_link
# ============================================================
def test_check_direct_link_match():
    """CGR and FaG both have the same memorial_id."""
    cgr_link = {"memorial_id": "123456", "url": "https://..."}
    fag_candidate = {"memorial_id": "123456", "score": 0.5}
    result = check_direct_link(cgr_link, fag_candidate)
    assert result is not None


def test_check_direct_link_no_match_different_ids():
    """Different memorial_ids → no direct link match."""
    cgr_link = {"memorial_id": "123456"}
    fag_candidate = {"memorial_id": "999999"}
    result = check_direct_link(cgr_link, fag_candidate)
    assert result is None


def test_check_direct_link_no_cgr_link():
    """No CGR link → no direct link."""
    result = check_direct_link(None, {"memorial_id": "123"})
    assert result is None


def test_check_direct_link_no_fag():
    """No FaG candidate → no direct link."""
    result = check_direct_link({"memorial_id": "123"}, None)
    assert result is None


# ============================================================
# corroborate (inferred match)
# ============================================================
def test_corroborate_strong_match():
    """Name + death year + state all agree."""
    # Same person: William Looney, died 1932 in OK
    cgr_record = {
        "first_name": "William",
        "last_name": "Looney",
        "cgr_died": "1932-02-28",
        "died_state": "OK",
    }
    fag_candidate = {
        "first_name": "William",
        "last_name": "Looney",
        "details": {"death_year": "1932"},
        "details_state": "OK",
    }
    result = corroborate(cgr_record, fag_candidate)
    assert result is not None


def test_corroborate_year_off_by_2():
    """Death year ±2 still matches."""
    cgr_record = {
        "first_name": "William", "last_name": "Looney",
        "cgr_died": "1932-02-28", "died_state": "OK",
    }
    fag_candidate = {
        "first_name": "William", "last_name": "Looney",
        "details": {"death_year": "1930"},
        "details_state": "OK",
    }
    result = corroborate(cgr_record, fag_candidate)
    assert result is not None


def test_corroborate_year_off_by_five_fails():
    """Death year off by >2 → no corroboration."""
    cgr_record = {
        "first_name": "William", "last_name": "Looney",
        "cgr_died": "1932-02-28", "died_state": "OK",
    }
    fag_candidate = {
        "first_name": "William", "last_name": "Looney",
        "details": {"death_year": "1925"},  # 7 years off
        "details_state": "OK",
    }
    result = corroborate(cgr_record, fag_candidate)
    assert result is None


def test_corroborate_different_last_names():
    """Different last names → no corroboration."""
    cgr_record = {
        "first_name": "William", "last_name": "Looney",
        "cgr_died": "1932", "died_state": "OK",
    }
    fag_candidate = {
        "first_name": "William", "last_name": "Smith",
        "details": {"death_year": "1932"},
        "details_state": "OK",
    }
    result = corroborate(cgr_record, fag_candidate)
    assert result is None


def test_corroborate_different_states():
    """Same person but in different states → no corroboration."""
    cgr_record = {
        "first_name": "William", "last_name": "Looney",
        "cgr_died": "1932", "died_state": "OK",
    }
    fag_candidate = {
        "first_name": "William", "last_name": "Looney",
        "details": {"death_year": "1932"},
        "details_state": "AR",  # buried in AR, not OK
    }
    result = corroborate(cgr_record, fag_candidate)
    # When states differ, we don't immediately reject — burial
    # state is a tiebreaker but not a hard requirement.
    # Per user decision: 'OK-connected, not require OK-burial'
    assert result is not None  # we still corroborate


# ============================================================
# detect_both_match orchestrator
# ============================================================
def _sample_pensioner():
    return {
        "first_name": "William",
        "last_name": "Looney",
        "pensioner_death_year": "1932",
    }


def test_detect_both_match_direct_link():
    """When CGR has direct link to a FaG candidate, use that."""
    fag_records = [
        {"memorial_id": "123456", "slug": "william-looney", "score": 0.8, "details": {}},
    ]
    cgr_records = [{"match_strength": "strong", "name": "William Looney"}]
    fag_link = {"memorial_id": "123456"}
    result = detect_both_match(_sample_pensioner(), cgr_records, fag_records, fag_link)
    assert result is not None
    assert result.method == MatchMethod.DIRECT_LINK
    assert result.fag_memorial_id == "123456"


def test_detect_both_match_corroboration():
    """When CGR strong match + FaG top candidate agrees by inference."""
    fag_records = [
        {
            "memorial_id": "999",
            "name": "William Looney",
            "slug": "william-looney",
            "score": 0.6,
            "details": {"death_year": "1932"},
        },
    ]
    cgr_records = [
        {
            "match_strength": "strong",
            "cgr_first": "William",
            "cgr_last": "Looney",
            "died": "1932-02-28",
            "died_state": "OK",
        },
    ]
    result = detect_both_match(_sample_pensioner(), cgr_records, fag_records, None)
    assert result is not None
    assert result.method == MatchMethod.CORROBORATION


def test_detect_both_match_no_match():
    """No CGR + FaG agreement → no BOTH MATCH."""
    result = detect_both_match(_sample_pensioner(), [], [], None)
    assert result is None


def test_detect_both_match_no_cgr():
    """No CGR records at all → no BOTH MATCH."""
    fag_records = [{"memorial_id": "999", "score": 0.5, "details": {}}]
    result = detect_both_match(_sample_pensioner(), [], fag_records, None)
    assert result is None


def test_detect_both_match_no_fag():
    """No FaG records → no BOTH MATCH (would need at least one)."""
    cgr_records = [{"match_strength": "strong", "died": "1932", "died_state": "OK"}]
    result = detect_both_match(_sample_pensioner(), cgr_records, [], None)
    assert result is None


# ============================================================
# BothMatchResult serialization
# ============================================================
def test_both_match_result_to_dict():
    """Result serializes to JSONL."""
    result = BothMatchResult(
        method=MatchMethod.DIRECT_LINK,
        cgr_cem_id="123456",
        fag_memorial_id="999",
        reason="Direct findagrave URL in CGR source",
        confidence=1.0,
    )
    d = result.to_dict()
    assert d["method"] == "direct_link"
    assert d["fag_memorial_id"] == "999"
    assert d["confidence"] == 1.0