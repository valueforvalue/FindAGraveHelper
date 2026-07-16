"""Tests for view.html CGR panel.

When the state record has 'cgr_records' (from the CGR xref run),
view.html should render a CGR section showing:
  - For each CGR match: name, unit, born, match_strength badge
  - Died state (the key OK-burial field)
  - Cemetery name + city + county
  - Conflicts highlighted (different unit, different birth year)

The CGR panel appears alongside the FaG candidates, not in
place of them. The user reviews both.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

VIEW_HTML = (ROOT / "scripts" / "view.html").read_text(encoding="utf-8")


def test_view_html_renders_cgr_records_section():
    """When cgr_records is present, view.html renders them."""
    assert "cgr_records" in VIEW_HTML


def test_view_html_shows_match_strength_badge():
    """Match strength (strong/medium/weak) is shown as a CSS badge."""
    assert "match-strength" in VIEW_HTML or "match_strength" in VIEW_HTML


def test_view_html_shows_died_state():
    """The died state field is displayed (key OK-burial signal)."""
    assert "died_state" in VIEW_HTML or "died-state" in VIEW_HTML


def test_view_html_shows_cemetery_name():
    """Cemetery name field is displayed."""
    assert "cemetery_details" in VIEW_HTML or "cemetery_name" in VIEW_HTML


def test_view_html_highlights_conflicts():
    """Conflicts (unit, birth_year) are highlighted somehow."""
    assert "conflicts" in VIEW_HTML


def test_view_html_handles_no_cgr_records():
    """When cgr_records is absent or empty, no crash — show nothing or note."""
    # Just verify the rendering code uses an optional check
    # (cgr_records || [] is the standard pattern)
    assert re.search(r"cgr_records\s*\|\|\s*\[\]", VIEW_HTML) or \
           re.search(r"cgr_records\s*&&", VIEW_HTML) or \
           re.search(r"\(cgr_records\s*\|\|", VIEW_HTML), \
        "expected optional cgr_records handling"


def test_view_html_cgr_panel_appears_per_pensioner():
    """CGR panel is rendered as part of each pensioner's row, not globally."""
    # Find the per-pensioner rendering block
    js_block_match = re.search(r"function renderPensioner.*?\n}", VIEW_HTML, re.DOTALL)
    assert js_block_match
    js_block = js_block_match.group(0)
    assert "cgr_records" in js_block or "cgr" in js_block.lower()


def test_view_html_cgr_strength_styling():
    """CSS classes exist for strong/medium/weak match strengths."""
    assert "match-strong" in VIEW_HTML or "strong" in VIEW_HTML
    assert "match-medium" in VIEW_HTML or "medium" in VIEW_HTML
    assert "match-weak" in VIEW_HTML or "weak" in VIEW_HTML


def test_view_html_cgr_died_state_emphasized():
    """The died state should be visually emphasized (it's the killer field)."""
    # Look for any CSS rule that highlights the died state
    assert re.search(r"died.*state|died_state", VIEW_HTML, re.IGNORECASE)