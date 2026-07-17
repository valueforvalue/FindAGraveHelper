"""J15-S2: scrape spouse from a FaG memorial page + compare.

Two layers:
  1. parse_spouse_from_html(html) - takes a static HTML
     string, returns structured spouse info. Tests use
     recorded/canonical HTML snippets (not live fetch).
  2. compare_spouses(local, captured) - normalizes names,
     decides on match. Tests use small fixtures.

Tests live in three groups (parse only, compare only, end-to-end).
"""
from __future__ import annotations

import re


# ============================================================
# Snapshot of a real Family Members section
# (from memorial 42943226 / margaret-mcclure-slemp). Used as
# the canonical fixture for parse_spouse_from_html.
# ============================================================
SAMPLE_HTML_MARGARET = """\
<!DOCTYPE html><html><body>
<h1>Margaret Slemp</h1>
<h2>Family Members</h2>

<div><b id="parentsLabel" class="label-relation">Parents</b>
<ul class="member-family" aria-labelledby="parentsLabel">
  <li><a href="/memorial/111689751/nathaniel-mcclure">Nathaniel McClure</a> 1811-1885</li>
</ul></div>

<div><b id="spouseLabel" class="label-relation">Spouse</b>
<ul class="member-family" aria-labelledby="spouseLabel">
  <li itemscope itemtype="https://schema.org/Person">
    <a class="d-block text-decoration-none" href="/memorial/42943220/mitchell_ward-slemp" itemprop="url">
      <div class="member-item d-flex mb-2">
        <span itemprop="name">Mitchell Ward Slemp</span>
        <span>1845-1904</span>
      </div>
    </a>
    (m. 1874)
  </li>
</ul></div>

<div><b id="childrenLabel" class="label-relation">Children</b>
<ul class="member-family" aria-labelledby="childrenLabel">
  <li><a href="/memorial/97599308/dora_anna-traub">Dora Anna Slemp Traub</a> 1876-1932</li>
</ul></div>

<h2>Inscription</h2>
</body></html>"""


# ============================================================
# parse_spouse_from_html
# ============================================================
def test_parse_spouse_from_margaret_slemp():
    """Canonical fixture: Margaret McClure Slemp's memorial lists
    spouse as Mitchell Ward Slemp at memorial 42943220."""
    from scripts.fag.spouse_scrape import parse_spouse_from_html
    out = parse_spouse_from_html(SAMPLE_HTML_MARGARET)
    assert out is not None, "expected spouse parsed"
    assert out["first"] == "Mitchell"
    assert out["middle"] == "Ward"
    assert out["last"] == "Slemp"
    assert out["memorial_id"] == "42943220"
    assert out["slug"] == "mitchell_ward-slemp"
    assert "1845" not in out["display"], (
        "years 1845-1904 should be stripped from display"
    )
    # Marriage year extracted from "(m. 1874)"
    assert out["marriage_year"] == "1874"


def test_parse_returns_none_when_no_family_section():
    from scripts.fag.spouse_scrape import parse_spouse_from_html
    html = "<html><body><h2>Other</h2><p>Nothing here.</p></body></html>"
    assert parse_spouse_from_html(html) is None


def test_parse_handles_span_wrapped_name():
    """FaG wraps the name in an inner <span itemprop="name">;
    the parser must strip the tag and still find the right piece.
    """
    from scripts.fag.spouse_scrape import parse_spouse_from_html
    html = """<html><body>
<h2>Family Members</h2>
<b id="spouseLabel">Spouse</b>
<ul class="member-family" aria-labelledby="spouseLabel">
  <li><a href="/memorial/99/jane-doe">
    <span itemprop="name">Jane Mary Doe</span>
    <span>1900-1975</span>
  </a></li>
</ul>
<h2>Bio</h2>
</body></html>"""
    out = parse_spouse_from_html(html)
    assert out is not None
    assert out["first"] == "Jane"
    assert out["middle"] == "Mary"
    assert out["last"] == "Doe"


def test_parse_extracts_year_from_link():
    """Years might appear inside the link text rather than after; the
    parser must still strip them."""
    from scripts.fag.spouse_scrape import parse_spouse_from_html
    html = """<html><body>
<h2>Family Members</h2>
<b id="spouseLabel">Spouse</b>
<ul class="member-family" aria-labelledby="spouseLabel">
<li><a href="/memorial/1234/bob-jones">Bob Allen Jones 1900-1980</a></li>
</ul>
<h2>Flowers</h2>
</body></html>"""
    out = parse_spouse_from_html(html)
    assert out["first"] == "Bob"
    assert out["middle"] == "Allen"
    assert out["last"] == "Jones"


def test_parse_strips_maiden_name_format():
    """FaG often shows maiden name in italics:
    'Affiah _Kelly_ McClure' -> Affiah Kelly McClure."""
    from scripts.fag.spouse_scrape import parse_spouse_from_html
    html = """<html><body>
<h2>Family Members</h2>
<b id="spouseLabel">Spouse</b>
<ul class="member-family" aria-labelledby="spouseLabel">
<li><a href="/memorial/77/x-y">Affiah <i>Kelly</i> McClure 1816-1854</a></li>
</ul>
</body></html>"""
    out = parse_spouse_from_html(html)
    assert out is not None
    assert out["first"] == "Affiah"
    assert out["middle"] == "Kelly"
    assert out["last"] == "McClure"


def test_parse_handles_short_name():
    """Single-token name (no middle)."""
    from scripts.fag.spouse_scrape import parse_spouse_from_html
    html = """<html><body>
<h2>Family Members</h2>
<b id="spouseLabel">Spouse</b>
<ul class="member-family" aria-labelledby="spouseLabel">
<li><a href="/memorial/555/smith">John Smith</a></li>
</ul>
</body></html>"""
    out = parse_spouse_from_html(html)
    assert out["first"] == "John"
    assert out["middle"] == ""
    assert out["last"] == "Smith"


# ============================================================
# _split_name + _norm helpers
# ============================================================
def test_split_name_three_parts():
    from scripts.fag.spouse_scrape import _split_name
    assert _split_name("Mitchell Ward Slemp") == {
        "first": "Mitchell", "middle": "Ward", "last": "Slemp"
    }


def test_split_name_single_token():
    from scripts.fag.spouse_scrape import _split_name
    assert _split_name("Smith") == {"first": "Smith", "middle": "", "last": "Smith"}


def test_split_name_handles_middle_initial():
    from scripts.fag.spouse_scrape import _split_name
    assert _split_name("Mitchell W. Slemp") == {
        "first": "Mitchell", "middle": "W.", "last": "Slemp"
    }


def test_norm_strips_trailing_period():
    from scripts.fag.spouse_scrape import _norm
    assert _norm("  Slemp.  ") == "slemp"


def test_norm_lowercases_and_collapses_ws():
    from scripts.fag.spouse_scrape import _norm
    assert _norm("Mitchell   WARD") == "mitchell ward"


def test_norm_strips_suffixes():
    from scripts.fag.spouse_scrape import _norm
    assert _norm("John Smith Jr") == "john smith"
    assert _norm("William Jones Sr") == "william jones"


# ============================================================
# compare_spouses
# ============================================================
def test_compare_strict_full_match():
    from scripts.fag.spouse_scrape import compare_spouses
    local = {"first": "Mitchell", "middle": "Ward", "last": "Slemp"}
    captured = {
        "first": "Mitchell", "middle": "Ward", "last": "Slemp",
        "display": "Mitchell Ward Slemp",
        "memorial_id": "42943220", "slug": "x",
        "marriage_year": "1874",
    }
    out = compare_spouses(local, captured, tolerance="loose")
    assert out is not None
    assert out["matched"] is True
    assert out["match_strength"] == "strong"
    assert out["matched_via"] == "first_and_last"


def test_compare_loose_last_only():
    """Local 'Mitchel Slemp' (no middle). Captured 'Mitchell Ward
    Slemp'. Last names match exactly, first initial matches. ->
    loose match via 'last_name'.
    """
    from scripts.fag.spouse_scrape import compare_spouses
    local = {"first": "Mitchel", "middle": "", "last": "Slemp"}
    captured = {
        "first": "Mitchell", "middle": "Ward", "last": "Slemp",
        "display": "Mitchell Ward Slemp",
        "memorial_id": "1", "slug": "x",
        "marriage_year": "",
    }
    out = compare_spouses(local, captured, tolerance="loose")
    assert out is not None
    assert out["matched_via"] == "last_name"
    assert out["match_strength"] == "medium"


def test_compare_strict_blocks_partial_match():
    """Strict mode requires both first+last exact. Last-name-only
    match should be REJECTED in strict."""
    from scripts.fag.spouse_scrape import compare_spouses
    local = {"first": "Mitchel", "middle": "", "last": "Slemp"}
    captured = {
        "first": "Mitchell", "middle": "Ward", "last": "Slemp",
        "display": "Mitchell Ward Slemp", "memorial_id": "1",
        "slug": "x", "marriage_year": "",
    }
    assert compare_spouses(local, captured, tolerance="strict") is None


def test_compare_rejects_when_first_and_last_both_differ():
    """'Robert Jones' vs 'John Smith' = no match."""
    from scripts.fag.spouse_scrape import compare_spouses
    local = {"first": "Robert", "middle": "", "last": "Jones"}
    captured = {
        "first": "John", "middle": "Q", "last": "Smith",
        "display": "John Q Smith", "memorial_id": "1",
        "slug": "x", "marriage_year": "",
    }
    assert compare_spouses(local, captured) is None


def test_compare_returns_none_when_local_missing():
    from scripts.fag.spouse_scrape import compare_spouses
    captured = {"first": "Mitchell", "middle": "Ward", "last": "Slemp",
                "display": "Mitchell Ward Slemp",
                "memorial_id": "1", "slug": "x", "marriage_year": ""}
    assert compare_spouses({"first": "", "middle": "", "last": "Slemp"}, captured) is None
    assert compare_spouses({"first": "Mitchel", "middle": "", "last": ""}, captured) is None
    assert compare_spouses({}, captured) is None


def test_compare_returns_none_when_captured_missing():
    from scripts.fag.spouse_scrape import compare_spouses
    local = {"first": "Mitchel", "middle": "", "last": "Slemp"}
    assert compare_spouses(local, None) is None
    assert compare_spouses(local, {}) is None


# ============================================================
# scrape_and_compare integration (uses a fake page)
# ============================================================

class _FakePage:
    """Minimal playwright.page-like stub for unit tests."""
    def __init__(self, html: str, title: str = "M"):
        self._html = html
        self._title = title
        self.visited: list[str] = []

    def goto(self, url, wait_until=None, timeout=None):
        self.visited.append(url)
        return None

    def wait_for_selector(self, sel, timeout=None):
        return None

    def title(self):
        return self._title

    def content(self):
        return self._html


def test_scrape_and_compare_calls_parse_and_compare():
    """End-to-end: scrape_and_compare goes to the right URL,
    parses the HTML, and returns the compare result (or None).
    """
    from scripts.fag.spouse_scrape import scrape_and_compare
    page = _FakePage(SAMPLE_HTML_MARGARET)
    top = {"memorial_id": "42943226", "slug": "margaret-mcclure-slemp"}
    local = {"first": "Mitchel", "middle": "Ward", "last": "Slemp"}
    out = scrape_and_compare(page, top, local)
    assert out is not None
    assert out["matched"] is True
    # Confirm the page was navigated correctly
    assert page.visited[0].endswith("/memorial/42943226/margaret-mcclure-slemp")


def test_scrape_and_compare_returns_none_when_no_spouse():
    from scripts.fag.spouse_scrape import scrape_and_compare
    html = "<html><body><h2>Bio</h2>No family section here.</body></html>"
    page = _FakePage(html)
    out = scrape_and_compare(page, {"memorial_id": "1", "slug": "x"},
                            {"first": "X", "middle": "", "last": "Y"})
    assert out is None


def test_scrape_and_compare_skips_cf_challenge():
    from scripts.fag.spouse_scrape import scrape_and_compare
    page = _FakePage("", title="Just a moment...")
    out = scrape_and_compare(page, {"memorial_id": "1", "slug": "x"},
                            {"first": "X", "middle": "", "last": "Y"})
    assert out is None
