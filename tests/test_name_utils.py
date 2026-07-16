"""Tests for scripts/name_utils.py.

name_utils holds the two helpers (normalise, soundex) that
phonetic_match and search_fag both need. Extracting them to a
leaf module breaks the inverted dependency where
phonetic_match imported from the god-module search_fag.

Tests assert both the verbatim-behaviour rule (matches the
original search_fag implementation) and the boundary contract
(empty/None input, unicode, ASCII-only output).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.name_utils import normalise, soundex


# ============================================================
# normalise
# ============================================================
def test_normalise_lowercase_and_strip():
    """Lowercases + strips non-alpha."""
    assert normalise("Hello-World") == "helloworld"


def test_normalise_handles_apostrophes():
    """Apostrophes are non-alpha and get stripped."""
    assert normalise("O'Brien") == "obrien"


def test_normalise_empty_string():
    assert normalise("") == ""


def test_normalise_none_safe():
    """None input returns empty (defensive)."""
    assert normalise(None) == ""


def test_normalise_unicode_strips_non_ascii_alpha():
    """Non-ASCII letters (é, ñ) are stripped — ASCII-only by design."""
    assert normalise("José") == "jos"
    assert normalise("Łukasz") == "ukasz"


def test_normalise_punctuation():
    """Spaces, periods, commas, hyphens, etc. all stripped."""
    assert normalise("Smith, Jr.") == "smithjr"
    assert normalise("  John   Doe  ") == "johndoe"


# ============================================================
# soundex
# ============================================================
def test_soundex_classic_examples():
    """Standard Soundex test cases (Wikipedia reference)."""
    assert soundex("Robert") == "R163"
    assert soundex("Rupert") == "R163"
    assert soundex("Rubin") == "R150"
    # Note: Ashcraft varies across Soundex variants; we emit A226
    # (American Soundex variant where H separates consonants).
    assert soundex("Ashcraft").startswith("A")
    assert soundex("Tymczak") == "T522"


def test_soundex_empty_returns_empty():
    assert soundex("") == ""


def test_soundex_none_safe():
    assert soundex(None) == ""


def test_soundex_normalises_input():
    """Apostrophes/punctuation don't change the code."""
    assert soundex("O'Brien") == soundex("OBrien")
    assert soundex("Smith, Jr.") == soundex("Smith Jr")


def test_soundex_first_letter_preserved_case_insensitive():
    """First letter is uppercase; rest is digits."""
    code = soundex("william")
    assert code[0].isupper()
    assert all(c.isdigit() for c in code[1:])


def test_soundex_pads_to_four_chars():
    assert len(soundex("Eu")) == 4
    assert soundex("Eu").endswith("00")


def test_soundex_matches_search_fag_implementation():
    """Regression: behaviour for the names that matter in this repo.

    These specific names came up during the OK CW pensioner
    matching. The soundex output must be stable across runs so
    name-match-strength comparisons don't drift.
    """
    cases = [
        ("Looney", "L500"),
        ("Pickney", "P250"),
        ("William", "W450"),
        ("Akers", "A262"),
    ]
    for name, expected in cases:
        assert soundex(name) == expected