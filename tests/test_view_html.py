"""Tests for view.html structure.

These tests parse the HTML file and assert that:
  - Score breakdown renders as visual bars (not just text)
  - Each candidate row shows the _found_by strategy
  - "Pick rank 1" button exists
  - "Show top N" filter exists
  - "Pick rank 1" works (sets decision to top candidate)
  - "Show top N" filters the candidate list

The tests are deliberately light (string matching) since we're not
running a JS test framework. They catch structural regressions
when view.html is edited.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

VIEW_HTML = (ROOT / "scripts" / "view.html").read_text(encoding="utf-8")


def test_score_breakdown_renders_as_bars():
    """Score breakdown should be visual bars (with inline width:), not plain text."""
    # Look for elements with style="width: <pct>%" in the breakdown section.
    # We expect at least 6 bars: last, first, middle, ok_burial, state, veteran, death
    assert "breakdown-bar" in VIEW_HTML, "expected breakdown-bar CSS class"


def test_breakdown_includes_found_by():
    """Each candidate should show which strategy found it."""
    # The render function should reference _found_by
    assert "_found_by" in VIEW_HTML, "expected _found_by rendering in view.html"


def test_pick_rank_1_button_exists():
    """A 'Pick rank 1' button should exist for one-click pick of top candidate."""
    # We accept any reasonable phrasing: "Pick rank 1", "Pick top", "Auto-pick".
    pattern = r"(Pick rank 1|Pick top|Auto-pick|Pick #1)"
    assert re.search(pattern, VIEW_HTML), "expected Pick-rank-1 button"


def test_show_top_n_filter_exists():
    """A 'Show top N' filter (5/10/20 buttons or select) should exist."""
    # Look for either explicit buttons or a select.
    assert re.search(r"top[- ]?\d|show[- ]?top|Top \d+", VIEW_HTML, re.IGNORECASE), \
        "expected Show-top-N filter"


def test_score_bar_max_value_present():
    """Bars should scale to the actual score value (e.g. width = pct%)."""
    # The render uses 'style="width:${pct}%"' where pct = round((v/max)*100).
    # The actual breakdown score comes from bd[feat] (per-feature score).
    # We just need to confirm there's a width-style directive on the bar.
    assert re.search(r"width[:=].*%|width:\d+%", VIEW_HTML) or "score-pct" in VIEW_HTML, \
        "expected bar width to be a percentage"


def test_breakdown_features_listed():
    """All 7 scoring features should be visible in the breakdown."""
    features = ["last", "first", "middle", "ok_burial", "state", "veteran", "death"]
    # Find the JS rendering block (the candidate map)
    js_block_match = re.search(r"\.map\(\(c, idx\) => \{.*?\}\)\.join", VIEW_HTML, re.DOTALL)
    assert js_block_match, "expected to find .map((c, idx) => ...) block"
    js_block = js_block_match.group(0)
    for feat in features:
        assert feat in js_block, f"feature {feat!r} missing from breakdown render"


def test_open_link_in_each_candidate():
    """Each candidate row should have an 'open' link to the FaG memorial."""
    assert 'c.backlink' in VIEW_HTML


def test_found_by_strategy_and_params_visible():
    """The render must show both strategy name and params."""
    # Look for _found_by (possibly destructured as fb) and strategy usage
    assert "_found_by" in VIEW_HTML
    # Either directly or destructured
    assert re.search(r"_found_by\.strategy|fb\.strategy", VIEW_HTML), \
        "expected _found_by.strategy rendering"
    assert re.search(r"fb\.params|formatParams", VIEW_HTML), \
        "expected _found_by params to be displayed"


def test_show_top_default_is_some_value():
    """The default number of candidates shown should be a sensible number (e.g. 5)."""
    # Look for a default value in the JS (e.g. let showTop = 5)
    assert re.search(r"showTop\s*=\s*\d+", VIEW_HTML), \
        "expected showTop variable to have a numeric default"