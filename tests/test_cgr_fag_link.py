"""Tests for F5: CGR -> FaG backlink extractor.

CGR vet details pages may have a 'Source' field that contains
a Find a Grave URL or memorial ID. We extract it for the
direct-link badge in view.html.

Patterns we've seen (need verification by inspecting real pages):
  - Source: "Find a Grave Memorial #12345"
  - Source: "http://www.findagrave.com/memorial/12345"
  - Source: "https://www.findagrave.com/memorial/12345/foo"
  - Source: "Find a Grave: 12345"

If we find a link, we extract the FaG memorial ID.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr.cgr_fag_link import (
    find_fag_url,
    extract_fag_memorial_id,
    extract_fag_source_fields,
    has_fag_link,
    FagLink,
)


# ============================================================
# URL detection
# ============================================================
def test_find_fag_url_in_text():
    """Find an FaG URL in free text."""
    text = "Source: Okla SCV Archives. See http://www.findagrave.com/memorial/12345/foo"
    url = find_fag_url(text)
    assert url is not None
    assert "findagrave.com/memorial/12345" in url


def test_find_fag_url_handles_https():
    """https://findagrave.com URLs are detected."""
    text = "https://www.findagrave.com/memorial/123456"
    url = find_fag_url(text)
    assert url is not None
    assert "123456" in url


def test_find_fag_url_handles_bare_id():
    """A bare memorial ID without URL may be present."""
    text = "Find a Grave Memorial 123456"
    link = extract_fag_memorial_id(text)
    assert link is not None
    assert link.memorial_id == "123456"


def test_extract_fag_memorial_id_bare_memorial_pattern():
    """Issue #10: 'Memorial NNNNN' (no 'Find a Grave' prefix) must match.

    The third regex (_FAG_BARE_RE) catches the bare 'memorial NNNNN'
    pattern that shows up in some CGR records. Regression guard so
    the regex literal doesn't regress to the unterminated state
    `r"memorial[:` that bit an earlier version of this module.
    """
    assert extract_fag_memorial_id("Memorial 12345").memorial_id == "12345"
    assert extract_fag_memorial_id("memorial:99999").memorial_id == "99999"
    assert extract_fag_memorial_id("memorial 88888").memorial_id == "88888"
    # Must NOT match unrelated numbers (e.g. dates, app numbers).
    assert extract_fag_memorial_id("Adair, R. W. 1844 1932") is None
    # Must NOT match words that just contain "memorial".
    assert extract_fag_memorial_id("memorial park") is None


def test_find_fag_url_returns_none_for_no_fag():
    """No FaG reference → None."""
    text = "Source: Okla. SCV Archives"
    url = find_fag_url(text)
    assert url is None


def test_find_fag_url_handles_full_memorial_link():
    """Full URL with slug."""
    text = "Source: https://www.findagrave.com/memorial/123456/william-g-looney"
    link = extract_fag_memorial_id(text)
    assert link.memorial_id == "123456"


# ============================================================
# has_fag_link (heuristic check)
# ============================================================
def test_has_fag_link_returns_true_when_findagrave_url():
    """True when 'findagrave' URL is present."""
    text = "See https://www.findagrave.com/memorial/12345"
    assert has_fag_link(text) is True


def test_has_fag_link_handles_find_a_grave_text():
    """Catches written-out 'Find a Grave' references."""
    text = "Find a Grave Memorial: 12345"
    assert has_fag_link(text) is True


def test_has_fag_link_returns_false_when_absent():
    """No FaG → False."""
    text = "Source: Okla. SCV Archives"
    assert has_fag_link(text) is False


# ============================================================
# Source field extraction
# ============================================================
def test_extract_fag_from_source_field():
    """If the vet record has a 'source' field, find FaG there."""
    rec = {"source": "https://www.findagrave.com/memorial/12345"}
    link = extract_fag_source_fields(rec)
    assert link is not None
    assert link.memorial_id == "12345"
    assert "findagrave.com" in link.url


def test_extract_fag_skips_irrelevant_source():
    """No FaG link → None."""
    rec = {"source": "Okla. SCV Archives"}
    link = extract_fag_source_fields(rec)
    assert link is None


def test_extract_fag_finds_link_in_notes():
    """Sometimes the link is in notes."""
    rec = {"notes": "Photo from https://www.findagrave.com/memorial/9999"}
    link = extract_fag_source_fields(rec)
    assert link is not None
    assert link.memorial_id == "9999"


# ============================================================
# FagLink dataclass
# ============================================================
def test_faglink_to_dict():
    """FagLink serializes to a dict for view.html."""
    link = FagLink(memorial_id="123456", url="https://www.findagrave.com/memorial/123456")
    d = link.to_dict()
    assert d["memorial_id"] == "123456"
    assert "findagrave.com" in d["url"]


def test_faglink_handles_no_url():
    """Memorial ID only, no URL."""
    link = FagLink(memorial_id="123456", url="")
    d = link.to_dict()
    assert d["memorial_id"] == "123456"
    assert d["url"] == ""