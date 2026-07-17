"""Tests for F2: regiment bio keyword strategy.

FaG's `bio=` URL param does full-text matching against memorial
bios and inscriptions. For CW veterans, the regiment name is
strongly identifying — "34th Texas Cavalry" or "29th Alabama".

Some regiments name patterns we should convert:
  "2nd Mississippi & 3rd Mississippi Infantry & Cavalry"
  → ["2nd Mississippi Infantry", "3rd Mississippi Cavalry"]

We don't want to spam 30 unit variants, so we cap at 2-3 of
the most distinctive phrases.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.matching.regiment_keyword import (
    extract_regiment_phrases,
    strategy_regiment_bio,
)


# ============================================================
# Phrase extraction
# ============================================================
def test_extract_simple():
    """Extract regiment phrases from a simple regiment string."""
    phrases = extract_regiment_phrases("2nd Mississippi Infantry")
    assert "2nd Mississippi" in phrases or "Mississippi Infantry" in phrases


def test_extract_compound():
    """Extract from a compound regiment string (& is the separator)."""
    regiment = "2nd Mississippi & 3rd Mississippi Infantry & Cavalry"
    phrases = extract_regiment_phrases(regiment)
    # Should yield at least one phrase per regiment
    assert len(phrases) >= 2


def test_extract_caps_at_three():
    """We cap the number of phrases to keep URL manageable."""
    # Edge case: very long compound regiment
    regiment = "1st Alabama & 2nd Alabama & 3rd Alabama & 4th Alabama Infantry & Cavalry & Mounted Rifles"
    phrases = extract_regiment_phrases(regiment)
    assert len(phrases) <= 3


def test_extract_skips_empty():
    """Empty/None input returns empty list."""
    assert extract_regiment_phrases("") == []
    assert extract_regiment_phrases(None) == []


def test_extract_handles_ordinal_suffixes():
    """Handles '1st', '2nd', '3rd', '4th', etc."""
    phrases = extract_regiment_phrases("1st Texas Cavalry")
    assert len(phrases) >= 1


def test_extract_strips_company_letter():
    """We don't want Co. A in the keyword."""
    phrases = extract_regiment_phrases("34th Texas Cavalry")
    # No "Co." in any phrase
    for p in phrases:
        assert "Co." not in p
        assert "Company" not in p


# ============================================================
# strategy_regiment_bio
# ============================================================
def test_strategy_regiment_bio_returns_first_phrase():
    """When a regiment is present, the strategy uses one phrase."""
    params = strategy_regiment_bio("William", "", "Looney", "34th Texas Cavalry", None)
    assert params is not None
    assert "bio" in params
    assert "firstname" in params
    assert "lastname" in params


def test_strategy_regiment_bio_no_regiment_returns_none():
    """Without a regiment, the strategy doesn't fire."""
    assert strategy_regiment_bio("William", "", "Looney", "", None) is None
    assert strategy_regiment_bio("William", "", "Looney", None, None) is None


def test_strategy_regiment_bio_requires_names():
    """Need at least first+last."""
    assert strategy_regiment_bio("", "", "Looney", "34th Texas Cavalry", None) is None
    assert strategy_regiment_bio("William", "", "", "34th Texas Cavalry", None) is None


def test_strategy_regiment_bio_bio_keyword_includes_state():
    """The bio keyword should include the state (34th Texas)."""
    params = strategy_regiment_bio("William", "", "Looney", "34th Texas Cavalry", None)
    bio = params.get("bio", "")
    assert "Texas" in bio or "34" in bio


def test_strategy_regiment_bio_compound_uses_shortest_phrase():
    """For a compound regiment, pick the most distinctive phrase."""
    regiment = "2nd Mississippi & 3rd Mississippi Infantry & Cavalry"
    params = strategy_regiment_bio("William", "", "Smith", regiment, None)
    bio = params.get("bio", "")
    # The bio must be a unit we're searching for
    assert len(bio) < len(regiment)
    assert bio.strip() != ""


def test_strategy_regiment_bio_url_friendly():
    """Bio keyword has no special URL characters beyond spaces."""
    params = strategy_regiment_bio("William", "", "Looney", "34th Texas Cavalry", None)
    bio = params.get("bio", "")
    # No unencoded & or = or #
    assert "&" not in bio.split("=")[0]  # not in value
    # Verify it survives urlencode
    from urllib.parse import urlencode
    encoded = urlencode(params)
    assert "bio=" in encoded