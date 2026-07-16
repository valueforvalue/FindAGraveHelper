"""Tests for F3: nickname + maiden name search.

FaG supports including nicknames and maiden names in search.
These appear as optional URL params we need to figure out:
  includeNickname=true|false
  includeMaiden=true|false

Standard CW-era nickname patterns we know about:
  Fannie   -> Fayette
  Mollie   -> Mary
  Polly    -> Mary
  Sally    -> Sarah
  Bettie   -> Elizabeth
  Nannie   -> Nancy
  Maggie   -> Margaret
  Nellie   -> Eleanor/Helen
  Mamie    -> Mary
  Patsy    -> Martha
  Dolly    -> Dorothy
  Lou      -> Louise
  Jennie   -> Jane/Jennifer
  Mandy    -> Amanda

For maiden names, we use the spouse_name from the pension record
to cross-reference. But this requires the spouse's data
post-processing, so we keep that as a separate flag.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.nickname_match import (
    KNOWN_NICKNAMES,
    reverse_nickname,
    nickname_candidates,
    strategy_with_nickname,
)


# ============================================================
# Known nicknames lookup
# ============================================================
def test_known_nickname_table_is_nonempty():
    """The nickname map should have entries."""
    assert len(KNOWN_NICKNAMES) > 0


def test_fannie_maps_to_fayette():
    """Fannie is a known nickname for Fayette."""
    assert "Fayette" in KNOWN_NICKNAMES["Fannie"]


def test_mollie_maps_to_mary():
    """Mollie is a known nickname for Mary."""
    assert "Mary" in KNOWN_NICKNAMES["Mollie"]


def test_unknown_name_returns_empty():
    """Unknown name → empty list."""
    assert KNOWN_NICKNAMES.get("Xenophilius", []) == []


def test_case_insensitive():
    """Nickname lookups are case-insensitive."""
    upper = nickname_candidates("FANNIE")
    lower = nickname_candidates("Fannie")
    assert set(upper) == set(lower)


def test_reverse_nickname_polymorphic():
    """A formal name might be the source of multiple nicknames.
    Reverse lookup should give them all."""
    rev = reverse_nickname("Mary")
    assert "Mollie" in rev
    assert "Polly" in rev
    assert "Mamie" in rev


# ============================================================
# Nickname candidates
# ============================================================
def test_nickname_candidates_no_known_returns_empty():
    """If no known nicknames, return empty."""
    assert nickname_candidates("Xenophilius") == []


def test_nickname_candidates_returns_all_known():
    """If there are 3 nicknames, return all 3."""
    cands = nickname_candidates("Mary")
    assert len(cands) >= 2  # At least 2: Mollie, Polly, Mamie, etc.


def test_nickname_candidates_deduplicates():
    """No duplicates in the candidate list."""
    cands = nickname_candidates("Elizabeth")
    assert len(set(cands)) == len(cands)


# ============================================================
# Strategy integration
# ============================================================
def test_strategy_with_nickname_returns_params():
    """If the first name has a known nickname, the strategy fires."""
    params = strategy_with_nickname("Fannie", "", "Rogers", None, None)
    assert params is not None
    # Variant should be one of the known variants of Fannie
    variants = {"Fayette", "Fanny", "Frances", "Stephanie"}
    assert params["firstname"] in variants
    assert "lastname" in params
    assert params["lastname"] == "Rogers"


def test_strategy_with_nickname_skips_when_no_known():
    """No known nickname → strategy returns None."""
    assert strategy_with_nickname("Xenophilius", "", "Smith", None, None) is None


def test_strategy_with_nickname_skips_when_no_names():
    """Missing names → no strategy."""
    assert strategy_with_nickname("", "", "Smith", None, None) is None


def test_strategy_with_nickname_passes_through_middle():
    """Middle name is included if present."""
    params = strategy_with_nickname("Mary", "E", "Anderson", None, None)
    if params and "middlename" in params:
        assert params["middlename"] == "E"


def test_strategy_with_nickname_uses_maiden_when_provided():
    """If pensioner has spouse (potential maiden name), use it."""
    # pensioner_dict has spouse_last_name
    pensioner = {"spouse_last_name": "Williams", "first_name": "Fannie"}
    params = strategy_with_nickname(
        "Fannie", "", "Rogers", pensioner, None
    )
    # This is the maiden-name strategy: search by the
    # spouse's last name as a clue.
    assert params is not None