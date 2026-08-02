"""Tests for scripts/ingest/recover_missed_dates.py.

The recovery pass generates *candidates* (with confidence scores)
from records where the strict find_death_date returned None but
'easy_text' is present. It does NOT auto-write death_date. A
human reviews the candidate list and writes back only the
accepted ones. This module tests:

1. Each generator's regex/heuristic.
2. Confidence score ordering (high-confidence before low).
3. Anti-keyword guards: GRANTED, FILED, address-change, etc.
   must suppress candidates (per L3 lessons).
4. The full pipeline: missed-set -> candidate list -> dedup.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ingest import recover_missed_dates as recover  

# ---- 1. Date hint extractors ------------------------------------------

def test_clean_mdY_date_extracted():
    """The trivial case: '4-14-1953' should match cleanly."""
    cands = recover.extract_candidates("DECEASED 4-14-1953")
    assert any(c.match == "4-14-1953" and c.year == 1953 for c in cands)


def test_2digit_year_mdY():
    """'4-11-29' — standard 2-digit year, maps to 1929."""
    cands = recover.extract_candidates("DECEASED 4-11-29")
    assert any(c.year == 1929 and c.month == 4 and c.day == 11
               for c in cands), f"got {[c.iso for c in cands]}"


def test_3digit_day_mdY():
    """'4-117-1929' — extra digit in day position (OCR noise).
    Most plausible read: 4-11-1929 (the 7 is OCR noise)."""
    cands = recover.extract_candidates("DECEASED 4-117-1929")
    assert any(c.year == 1929 and c.month == 4 and c.day == 117
               for c in cands), f"got {[c.iso for c in cands]}"


def test_month_word_with_year():
    """'MARCH 17 1920' — month word, day, year."""
    cands = recover.extract_candidates("DECEASED MARCH 17 1920")
    assert any(c.year == 1920 and c.month == 3 and c.day == 17
               for c in cands), f"got {[c.iso for c in cands]}"


def test_year_only_in_range():
    """'1920' alone with 'Deceased' in the chunk should be a
    year-only candidate (confidence lower)."""
    cands = recover.extract_candidates("Deceased 1920")
    assert any(c.year == 1920 and c.kind == "year-only"
               for c in cands), f"got {[c.iso for c in cands]}"


def test_obvious_garbage_rejected():
    """'DECEASED 1-!2' — too short to be a real date.
    No full-date candidate (avoids spam)."""
    cands = recover.extract_candidates("DECEASED 1-!2")
    assert not any(c.year and c.year > 1900 and c.month and c.day
                   for c in cands), (
        f"should not extract a full date from '1-!2', got {[c.iso for c in cands]}"
    )


# ---- 2. Anti-keyword guards ------------------------------------------

def test_granted_keyword_suppresses_candidate():
    """'GRANTED 4-14-1953' is a grant stamp, not a death."""
    cands = recover.extract_candidates("GRANTED 4-14-1953")
    assert not any(c.year == 1953 for c in cands), (
        "GRANTED keyword must suppress the candidate"
    )


def test_filed_keyword_suppresses_candidate():
    """'Filed 6/14/15' is a filing date, not a death."""
    cands = recover.extract_candidates("Filed 6/14/15")
    assert not any(c.year == 1915 for c in cands), (
        "FILED keyword must suppress the candidate"
    )


def test_address_change_keyword_suppresses_candidate():
    """'gives Temp Address 9/14/20' is an address-change entry.
    'Changed from X to Y' is also an address change even without
    a number glued to the keyword."""
    
    cands1 = recover.extract_candidates("gives Temp Address 9/14/20")
    assert not any(c.year == 1920 for c in cands1), (
        "gives Temp Address must suppress the candidate"
    )
    
    cands2 = recover.extract_candidates("Changed from Hollis to Gould 9/18/19")
    assert not any(c.year == 1919 for c in cands2), (
        "Changed from must suppress the candidate"
    )


def test_rejected_keyword_suppresses_candidate():
    """'REJECTED 8/31-20' is a rejection stamp."""
    cands = recover.extract_candidates("REJECTED 8/31-20")
    assert not any(c.year == 1920 for c in cands), (
        "REJECTED keyword must suppress the candidate"
    )


def test_window_keyword_must_be_near():
    """'DECEASED 4-14-1953 ... (100 chars later) ... Filed 6/14/15'
    — the FILED keyword is too far from the candidate to count
    against it (L2 widow-strictness lesson)."""
    text = "DECEASED 4-14-1953 " + ("x " * 60) + "Filed 6/14/15"
    cands = recover.extract_candidates(text)
    assert any(c.year == 1953 for c in cands), (
        "candidate should survive when FILED is far from the date"
    )


# ---- 3. Confidence scoring -------------------------------------------

def test_full_mdY_scores_higher_than_year_only():
    """'DECEASED 4-14-1953' (full) should outrank 'DECEASED 1920'
    (year-only) in confidence."""
    full = recover.extract_candidates("DECEASED 4-14-1953")
    year_only = recover.extract_candidates("DECEASED 1920")
    assert full and year_only
    assert max(c.confidence for c in full) > max(c.confidence for c in year_only)


def test_keyword_nearby_boosts_confidence():
    """A date within 60 chars of 'Deceased' should score higher
    than the same date without a nearby death keyword."""
    near = recover.extract_candidates("Deceased 4-14-1953")
    far = recover.extract_candidates("xyz abc 4-14-1953")
    assert near and far
    assert max(c.confidence for c in near) > max(c.confidence for c in far)


# ---- 4. Year range boundary ------------------------------------------

def test_pre_1860_year_rejected():
    # Issue #144: MIN_YEAR lowered from 1865 to 1860 to catch
    # Civil War death dates. Pre-1860 years (birth, marriage)
    # must still be rejected.
    cands = recover.extract_candidates("Deceased 4-14-1859")
    assert not any(c.year and c.year < 1860 for c in cands), (
        "pre-1860 years must be rejected"
    )


def test_post_1955_year_rejected():
    cands = recover.extract_candidates("Deceased 4-14-2000")
    assert not any(c.year and c.year > 1955 for c in cands), (
        "post-1955 years must be rejected"
    )


# ---- 5. Full record-level pipeline -----------------------------------

def test_process_record_filters_correctly():
    """A red_ocr_results record with easy_text containing a
    recoverable date but no death_date should produce a
    candidate. A record where the easy_text is pure admin
    (no death keyword) should produce nothing."""
    rec_recoverable = {
        "pensioncard_id": 10540,
        "image": "10540.jpg",
        "easy_text": "DECEASED 4-14-1953 Name Smith, J Filed 6/3/15",
        "red_text": "",
        "death_date": None,
    }
    rec_pure_admin = {
        "pensioncard_id": 9999,
        "image": "9999.jpg",
        "easy_text": "GRANTED 4-14-1953 Filed 6/3/15 REJECTED 5/2/19",
        "red_text": "",
        "death_date": None,
    }
    cands_recoverable = recover.process_record(rec_recoverable)
    cands_admin = recover.process_record(rec_pure_admin)
    assert any(c.year == 1953 for c in cands_recoverable), (
        "DECEASED + date should produce a candidate"
    )
    assert cands_admin == [], (
        "pure admin text should produce no candidates"
    )


def test_process_record_skips_already_dated():
    rec = {
        "pensioncard_id": 1,
        "easy_text": "DECEASED 4-14-1953",
        "death_date": {"year": 1953},
    }
    assert recover.process_record(rec) == [], (
        "records with existing death_date must be skipped"
    )


def test_process_record_skips_missing_easy_text():
    rec = {
        "pensioncard_id": 1,
        "easy_text": None,
        "death_date": None,
    }
    assert recover.process_record(rec) == []


# ---- 6. Candidate serialization --------------------------------------

def test_candidate_to_dict_round_trip():
    """The candidate must be JSON-serializable for the audit trail."""
    cands = recover.extract_candidates("DECEASED 4-14-1953")
    assert cands
    d = cands[0].to_dict()
    assert d["year"] == 1953
    assert d["month"] == 4
    assert d["day"] == 14
    assert "iso" in d
    assert "confidence" in d
    assert "match" in d
    assert "reasoning" in d
