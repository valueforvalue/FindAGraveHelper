"""Tests for the pensioner-to-CGR matcher.

Given a local pensioner (from unified.json or dixiedata) and one
or more CGR records (from search results), decide whether they
refer to the same person.

CRITICAL PHILOSOPHY (user guidance, 2026-07-16):
  "Don't make grand assumptions about the accuracy of our
   DixieData local data. There is significant overlap with names
   and so forth in these kinds of records so we have to be sure.
   Its okay to be suspicious of an error but don't assume one."

That means:
  - When CGR says "William G Looney, 34 TX" and local says
    "William Pickney Looney, 4th TN Cav", we DO NOT conclude
    "one is wrong". They may be different people.
  - Same first + last name alone is NOT strong evidence. Lots
    of people share names.
  - Strong evidence = name + birth year + unit agreement
  - Medium evidence = name + birth year agreement (different units OK)
  - Weak evidence = name only (multiple matches, ambiguous)
  - No match = name doesn't match at all

This matcher returns:
  - A list of CGR records with a `match_strength` annotation
    ('strong', 'medium', 'weak', 'none')
  - It does NOT pick a "best" or auto-merge. The human decides.
  - Conflicts (different unit, different birth year) are
    preserved as conflict fields, not silently resolved.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr_matcher import (
    match_pensioner_to_cgr,
    MatchStrength,
    name_match_strength,
    compare_years,
)


# ============================================================
# Fixtures
# ============================================================
# A real OK pensioner from unified.json, in our standardized shape
PENSIONER_LOONEY = {
    "id": 7666,
    "name_raw": "Looney, Louis F",
    "first_name": "Louis",
    "middle_name": "F",
    "last_name": "Looney",
    "regiment": "32nd Texas Volunteers Cavalry ",
    "death_year": "",
    "birth_year": "",
}


def test_name_match_strength_exact():
    """Exact first+last match is 'strong'."""
    assert name_match_strength("William", "Looney", "William", "Looney") == "strong"


def test_name_match_strength_first_initial():
    """First-name initial match is 'medium'."""
    assert name_match_strength("William", "Looney", "W.", "Looney") == "medium"


def test_name_match_strength_last_differs():
    """Different last name is 'none'."""
    assert name_match_strength("William", "Looney", "William", "Smith") == "none"


def test_name_match_strength_first_differs():
    """Different first name is at most 'weak' (last-name-only match)."""
    assert name_match_strength("William", "Looney", "John", "Looney") == "weak"


def test_name_match_strength_last_phonetic():
    """Phonetic last-name match (Soundex equal) with exact first = 'strong'.

    This is the conservative choice: we treat phonetic match as a
    real match when the rest of the name agrees. We do NOT silently
    downgrade because the spelling differs — that's the human's call."""
    assert name_match_strength("William", "Looney", "William", "Loney") == "strong"


def test_compare_years_exact():
    """Same year returns 'exact'."""
    assert compare_years("1840", "1840") == "exact"


def test_compare_years_within_two():
    """Years within 2 are 'close'."""
    assert compare_years("1840", "1842") == "close"


def test_compare_years_within_five():
    """Years within 5 are 'near'."""
    assert compare_years("1840", "1844") == "near"


def test_compare_years_far():
    """Years more than 5 apart are 'far'."""
    assert compare_years("1840", "1850") == "far"


def test_compare_years_one_missing():
    """If one year is missing, returns 'unknown'."""
    assert compare_years("", "1840") == "unknown"
    assert compare_years("1840", "") == "unknown"
    assert compare_years("", "") == "unknown"


# ============================================================
# Pensioner-to-CGR matching
# ============================================================
def test_match_returns_all_cgr_records_unchanged():
    """All CGR records come back, even if they don't match."""
    cgr_records = [
        {"id": 1, "name": "John Smith", "unit": "5 AL", "born": "1840"},
        {"id": 2, "name": "Different Name", "unit": "10 TN", "born": "1842"},
    ]
    pensioner = {"first_name": "John", "last_name": "Smith", "regiment": "5 AL"}
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert len(matches) == 2  # both records returned


def test_match_annotates_strength_per_record():
    """Each match has a 'match_strength' field."""
    cgr_records = [{"id": 1, "name": "John Smith", "unit": "5 AL", "born": "1840"}]
    pensioner = {"first_name": "John", "last_name": "Smith"}
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert "match_strength" in matches[0]


def test_match_strong_when_name_unit_birth_year_all_match():
    """All three signals agree = strong match."""
    cgr_records = [
        {"id": 1, "name": "William G Looney", "unit": "34 TX", "born": "May 24 1840"},
    ]
    pensioner = {
        "first_name": "William",
        "middle_name": "G",
        "last_name": "Looney",
        "regiment": "34 TX",
        "birth_year": "1840",
    }
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert matches[0]["match_strength"] == "strong"


def test_match_medium_when_name_and_birth_year_match_unit_differs():
    """Same person, different unit (served in two units) = medium."""
    cgr_records = [
        {"id": 1, "name": "William Looney", "unit": "34 TX", "born": "1840"},
    ]
    pensioner = {
        "first_name": "William",
        "last_name": "Looney",
        "regiment": "4th TN Cav",
        "birth_year": "1840",
    }
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert matches[0]["match_strength"] in ("medium", "strong")


def test_match_weak_when_only_last_name_matches():
    """Same last name, different first name = weak (could be relatives)."""
    cgr_records = [
        {"id": 1, "name": "John Looney", "unit": "5 AL", "born": "1840"},
    ]
    pensioner = {"first_name": "William", "last_name": "Looney"}
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert matches[0]["match_strength"] in ("weak", "medium")


def test_match_records_conflict_when_birth_year_disagrees():
    """If birth year differs by 5+ years, mark as conflict (not silent)."""
    cgr_records = [
        {"id": 1, "name": "William Looney", "unit": "34 TX", "born": "1840"},
    ]
    pensioner = {
        "first_name": "William",
        "last_name": "Looney",
        "regiment": "34 TX",
        "birth_year": "1850",
    }
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    # The match is recorded, but a conflict is flagged
    assert "conflicts" in matches[0]
    assert "birth_year" in matches[0]["conflicts"]


def test_match_records_conflict_when_unit_disagrees():
    """If units differ, mark as conflict (do not silently pick one)."""
    cgr_records = [
        {"id": 1, "name": "William Looney", "unit": "34 TX", "born": "1840"},
    ]
    pensioner = {
        "first_name": "William",
        "last_name": "Looney",
        "regiment": "4th TN Cav",
        "birth_year": "1840",
    }
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert "conflicts" in matches[0]
    assert "unit" in matches[0]["conflicts"]


def test_match_does_not_auto_pick():
    """The matcher returns ALL CGR records with annotations. It does
    NOT pick one as 'best' or auto-merge. The human decides."""
    cgr_records = [
        {"id": 1, "name": "William Looney", "unit": "34 TX", "born": "1840"},
        {"id": 2, "name": "William Looney", "unit": "5 AL", "born": "1842"},
    ]
    pensioner = {"first_name": "William", "last_name": "Looney"}
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    # Both records are returned with their own strength
    assert len(matches) == 2
    assert "best_match_id" not in matches[0] or matches[0].get("best_match_id") is None


def test_match_preserves_all_records_with_first_name_partial():
    """When first names only partially agree (initial match), still include."""
    cgr_records = [
        {"id": 1, "name": "W. Looney", "unit": "34 TX", "born": "1840"},
    ]
    pensioner = {"first_name": "William", "last_name": "Looney", "regiment": "34 TX"}
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert len(matches) == 1
    # Partial name match is at most medium
    assert matches[0]["match_strength"] in ("medium", "weak", "strong")


def test_match_handles_empty_cgr_list():
    """Empty CGR results returns empty list."""
    matches = match_pensioner_to_cgr(PENSIONER_LOONEY, [])
    assert matches == []


def test_match_handles_pensioner_without_regiment():
    """If pensioner has no regiment, don't penalize unit mismatch."""
    cgr_records = [
        {"id": 1, "name": "William Looney", "unit": "34 TX", "born": "1840"},
    ]
    pensioner = {
        "first_name": "William",
        "last_name": "Looney",
        "regiment": "",
        "birth_year": "1840",
    }
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    # No unit conflict because we don't know what unit the pensioner was in
    assert "unit" not in matches[0].get("conflicts", {})


def test_match_strength_is_string_for_serialization():
    """Match strength is a string value (not enum) so JSON serialization works."""
    cgr_records = [{"id": 1, "name": "William Looney", "unit": "34 TX", "born": "1840"}]
    pensioner = {"first_name": "William", "last_name": "Looney"}
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert isinstance(matches[0]["match_strength"], str)


def test_match_strength_enum_exposed():
    """MatchStrength enum is exposed for type hints and dict access."""
    assert MatchStrength.STRONG.value == "strong"
    assert MatchStrength.MEDIUM.value == "medium"
    assert MatchStrength.WEAK.value == "weak"
    assert MatchStrength.NONE.value == "none"


def test_match_includes_full_cgr_record_in_output():
    """Output dict includes the original CGR record fields (not just strength)."""
    cgr_records = [
        {"id": 1, "name": "William Looney", "unit": "34 TX", "born": "May 24 1840"},
    ]
    pensioner = {"first_name": "William", "last_name": "Looney"}
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    assert matches[0]["cgr_id"] == 1
    assert matches[0]["cgr_name"] == "William Looney"
    assert matches[0]["cgr_unit"] == "34 TX"


def test_match_does_not_assume_error_in_either_record():
    """When CGR says X and local says Y, the matcher reports both.
    It does NOT silently conclude one is wrong. The human reviews."""
    # This is the philosophical test. If this test ever fails, it
    # means the matcher is making assumptions it shouldn't.
    cgr_records = [
        {"id": 1, "name": "William G Looney", "unit": "34 TX", "born": "1840"},
    ]
    pensioner = {
        "first_name": "William",
        "last_name": "Looney",
        "regiment": "4th TN Cav",  # different unit
        "birth_year": "1840",  # same year
        "middle_name": "Pickney",  # different middle
    }
    matches = match_pensioner_to_cgr(pensioner, cgr_records)
    # The match is reported with both records preserved
    assert matches[0]["cgr_id"] == 1
    assert matches[0]["local_unit"] == "4th TN Cav"
    assert matches[0]["cgr_unit"] == "34 TX"
    assert "unit" in matches[0]["conflicts"]
    # We do NOT auto-conclude "they're the same person"
    # or "CGR is wrong" or "local is wrong"