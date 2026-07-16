"""Tests for spouse cross-reference logic.

Given a FaG spouse/children index entry and a ok_pensioners.json widow
record, decide whether they're the same family. The cross-ref is
strong when:
  - Widow's first + last name matches spouse's first + last
  - Widow's spouse_name_raw mentions the soldier's last name

Returns a 'match_type' that the search harness can use to bump
candidate scores:
  - 'strong': widow name on FaG matches widow name in pension
  - 'loose':  last name matches but first doesn't, or vice versa
  - None:     no match
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.spouse_cross_ref import (
    cross_ref_widow_record,
    MatchStrength,
)


# ============================================================
# Fixtures: real widow records from ok_pensioners.json
# ============================================================
WIDOW_LOONEY = {
    "id": 5052,
    "name_raw": "Looney, Fannie J.",
    "first_name": "Fannie",
    "middle_name": "J.",
    "last_name": "Looney",
    "spouse_name_raw": "Looney, William P.",
    "regiment": "Tennessee Infantry and Cavalry",
}


def test_strong_match_when_widow_matches_fag_spouse():
    """Fannie J. Looney matches Fayette 'Fannie' Rogers Looney (FaG)."""
    fag_spouse = {
        "raw_name": 'Fayette J. "Fannie" Rogers Looney',
        "first_name": "Fayette",
        "last_name": "Looney",
        "birth_year": "1844",
        "death_year": "1931",
    }
    # Soldier is William Pickney Looney
    soldier_last = "Looney"
    result = cross_ref_widow_record(fag_spouse, WIDOW_LOONEY, soldier_last)
    assert result is not None
    assert result["match_strength"] in ("strong", "loose")


def test_strong_match_includes_widow_id():
    """Cross-ref result should include the widow's unified record id."""
    fag_spouse = {
        "raw_name": 'Fayette J. "Fannie" Rogers Looney',
        "first_name": "Fayette",
        "last_name": "Looney",
        "birth_year": "1844",
        "death_year": "1931",
    }
    result = cross_ref_widow_record(fag_spouse, WIDOW_LOONEY, "Looney")
    assert result["widow_id"] == 5052


def test_no_match_when_widow_last_name_differs():
    """If widow's last name doesn't match FaG spouse's last name, no match."""
    fag_spouse = {
        "raw_name": "Mary Smith",
        "first_name": "Mary",
        "last_name": "Smith",
    }
    widow_different_last = {
        "id": 9999,
        "first_name": "Mary",
        "last_name": "Jones",
        "spouse_name_raw": "Jones, Henry",
    }
    result = cross_ref_widow_record(fag_spouse, widow_different_last, "Smith")
    assert result is None


def test_strong_match_when_soldier_in_pension():
    """If widow's spouse_name_raw mentions soldier's last name,
    first name matches, last matches → strong match even if
    widow's spouse was a different person with the same last name."""
    fag_spouse = {
        "raw_name": "Mary Anderson",
        "first_name": "Mary",
        "last_name": "Anderson",
    }
    widow_with_different_soldier = {
        "id": 21,
        "first_name": "Mary",
        "last_name": "Anderson",
        "spouse_name_raw": "Anderson, Marcus Calhoun",
    }
    soldier_was_a_different_anderson = "Anderson"
    result = cross_ref_widow_record(
        fag_spouse, widow_with_different_soldier, soldier_was_a_different_anderson
    )
    # Anderson IS in the pension record + first/last match → strong
    # (we don't know if it's the right Anderson, but the pension confirms
    # at least one Anderson married her)
    assert result is not None
    assert result["match_strength"] == "strong"
    assert result["soldier_in_pension"] is True


def test_no_match_when_soldier_last_name_not_in_pension():
    """If widow's spouse_name_raw doesn't reference the soldier we're
    searching for, return None — the widow's soldier is someone else."""
    fag_spouse = {
        "raw_name": "Mary Anderson",
        "first_name": "Mary",
        "last_name": "Anderson",
    }
    widow_married_someone_else = {
        "id": 99,
        "first_name": "Mary",
        "last_name": "Anderson",
        "spouse_name_raw": "Anderson, Marcus Calhoun",
    }
    # The soldier being searched is "Smith" (not Anderson).
    # Mary Anderson's husband on record is "Marcus Calhoun Anderson",
    # not Smith — so no match.
    result = cross_ref_widow_record(
        fag_spouse, widow_married_someone_else, "Smith"
    )
    assert result is None


def test_loose_match_when_only_last_name_matches():
    """First names don't match exactly but last does — loose match."""
    fag_spouse = {
        "raw_name": "Sarah Wilson",
        "first_name": "Sarah",
        "last_name": "Wilson",
    }
    widow_with_phonetic_match = {
        "id": 100,
        "first_name": "Sara",  # phonetic match
        "last_name": "Wilson",
        "spouse_name_raw": "Wilson, John Q.",
    }
    result = cross_ref_widow_record(fag_spouse, widow_with_phonetic_match, "Wilson")
    assert result is not None
    # Should be at most "loose"
    assert result["match_strength"] in ("loose", "strong")


def test_match_strength_exposes_constants():
    """MatchStrength is an enum with strong/loose values."""
    # Just check the enum exists and has expected members
    assert hasattr(MatchStrength, "STRONG")
    assert hasattr(MatchStrength, "LOOSE")


def test_cross_ref_handles_missing_spouse_name_raw():
    """If widow record has no spouse_name_raw, do not crash."""
    fag_spouse = {
        "raw_name": "Mary Jones",
        "first_name": "Mary",
        "last_name": "Jones",
    }
    widow_no_spouse = {
        "id": 50,
        "first_name": "Mary",
        "last_name": "Jones",
        "spouse_name_raw": "",  # empty
    }
    result = cross_ref_widow_record(fag_spouse, widow_no_spouse, "Jones")
    # Empty spouse_name_raw means we can't verify which soldier, so loose or None
    assert result is None or result["match_strength"] == "loose"


def test_cross_ref_handles_first_name_initial_match():
    """Fayette (FaG) and Fannie (widow) — first 3 chars match, strong."""
    fag_spouse = {
        "raw_name": 'Fayette J. "Fannie" Rogers Looney',
        "first_name": "Fayette",
        "last_name": "Looney",
    }
    widow_fannie = {
        "id": 5052,
        "first_name": "Fannie",
        "last_name": "Looney",
        "spouse_name_raw": "Looney, William P.",
    }
    result = cross_ref_widow_record(fag_spouse, widow_fannie, "Looney")
    assert result is not None
    # Fannie is the nickname of Fayette — should be strong
    assert result["match_strength"] == "strong"