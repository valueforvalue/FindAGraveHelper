"""Tests for spouse/children extraction from FaG memorial pages.

These tests use fixture text captured from real FaG memorial pages
during the spouse prototype run (2026-07-16). The HTML/text structure
of FaG pages is consistent: a "Spouse" section followed by an entry
with name + dates, optionally marriage year. Same for "Children".

If FaG changes its layout, these tests will need updating.
"""
import sys
from pathlib import Path

# Allow imports from scripts/ without packaging
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.spouse_extract import extract_spouse, extract_children


# ============================================================
# Fixture: William Pickney Looney (memorial 50923719)
# Captured from a real FaG page (2026-07-16)
# ============================================================
LOONEY_TEXT = """
William Pickney Looney
VETERAN
11 Jul 1838 – 5 May 1909

Burial
Battle Creek Cemetery, Eolian, Stephens County, Texas, USA

Plot: Section 2

Spouse
Fayette J. "Fannie" Rogers Looney
1844–1931 (m. 1870)

Children
Walter W Looney
1874–1953

Laura Anne Looney Cryer
1875–1960

John Pleasant Looney
1877–1964

Flowers • 6
"""


def test_extract_spouse_looney_returns_dict():
    """Spouse extraction returns a dict with raw_name, first, last, years."""
    result = extract_spouse(LOONEY_TEXT)
    assert result is not None
    assert "raw_name" in result
    assert "first_name" in result
    assert "last_name" in result
    assert "birth_year" in result
    assert "death_year" in result


def test_extract_spouse_looney_name_correct():
    """The spouse is Fayette J. 'Fannie' Rogers Looney (real data)."""
    result = extract_spouse(LOONEY_TEXT)
    assert "Fannie" in result["raw_name"]
    assert "Rogers" in result["raw_name"]


def test_extract_spouse_looney_first_name():
    """First name is 'Fayette' (long-form)."""
    result = extract_spouse(LOONEY_TEXT)
    assert result["first_name"] == "Fayette"


def test_extract_spouse_looney_last_name():
    """Last name is 'Looney' (married name)."""
    result = extract_spouse(LOONEY_TEXT)
    assert result["last_name"] == "Looney"


def test_extract_spouse_looney_dates():
    """Birth and death years are 1844 and 1931."""
    result = extract_spouse(LOONEY_TEXT)
    assert result["birth_year"] == "1844"
    assert result["death_year"] == "1931"


def test_extract_children_looney_count():
    """Looney has 3 children (Walter, Laura, John)."""
    children = extract_children(LOONEY_TEXT)
    assert len(children) == 3


def test_extract_children_looney_first():
    """First child is Walter W Looney (1874-1953)."""
    children = extract_children(LOONEY_TEXT)
    assert "Walter" in children[0]["raw_name"]
    assert "Looney" in children[0]["raw_name"]
    assert children[0]["birth_year"] == "1874"
    assert children[0]["death_year"] == "1953"


def test_extract_children_handles_veteran_tag():
    """Some children's names include 'V VETERAN' suffix — strip it."""
    text = """
Spouse
Mary Smith
1840–1920

Children
John W Smith V VETERAN
1870–1950

Jane Smith
1872–1945
"""
    children = extract_children(text)
    assert len(children) == 2
    assert "VETERAN" not in children[0]["raw_name"]
    assert "John" in children[0]["raw_name"]


def test_extract_spouse_returns_none_when_no_section():
    """If page has no 'Spouse' section, return None (not error)."""
    text = """
John Smith
VETERAN
1838–1920

Burial
Some Cemetery
"""
    result = extract_spouse(text)
    assert result is None


def test_extract_children_returns_empty_list_when_no_section():
    """If page has no 'Children' section, return empty list."""
    text = """
John Smith
VETERAN
1838–1920

Burial
Some Cemetery
"""
    children = extract_children(text)
    assert children == []


def test_extract_spouse_stops_at_children_section():
    """Spouse section is bounded; should not include children as spouse."""
    result = extract_spouse(LOONEY_TEXT)
    # Walter W Looney should not be in the spouse name
    assert "Walter" not in result["raw_name"]


def test_extract_children_handles_maiden_name_marker():
    """Some entries include maiden name in parentheses — keep raw."""
    text = """
Children
Mary (Johnson) Smith
1870–1950
"""
    children = extract_children(text)
    assert len(children) == 1
    assert "Mary" in children[0]["raw_name"]
    assert "Smith" in children[0]["raw_name"]


def test_extract_children_handles_jr_sr_suffix():
    """Suffixes like 'Jr', 'Sr', 'III' should be preserved in raw_name."""
    text = """
Children
Newton Rufus Anderson Sr
1882–1942
"""
    children = extract_children(text)
    assert len(children) == 1
    assert "Sr" in children[0]["raw_name"]
    assert "Anderson" in children[0]["last_name"]


# ============================================================
# Fixture: minimal/no spouse case
# ============================================================
def test_extract_spouse_handles_minimal_page():
    """Page with all metadata but no family section."""
    text = """
John Smith
1838–1920

Burial
Some Cemetery
"""
    assert extract_spouse(text) is None
    assert extract_children(text) == []