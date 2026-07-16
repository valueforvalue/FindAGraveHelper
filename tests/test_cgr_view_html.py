"""Tests for view.html CGR dedup badge (J7).

The CGR panel was removed (CGR is now a post-run dedup signal,
not a side display). Each results.jsonl record carries a
`cgr_dedup_status` field set by scripts/cgr/cgr_fag_dedup.py;
view.html renders it as a small badge beside the fag_status pill
and as a filter in the status dropdown.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VIEW_HTML = (ROOT / "scripts" / "view.html").read_text(encoding="utf-8")


# ============================================================
# Badge rendering
# ============================================================
def test_view_html_renders_cgr_dedup_badge():
    """The render path must call a cgr-dedup badge helper."""
    assert "renderCgrDedupBadge" in VIEW_HTML, (
        "expected renderCgrDedupBadge helper in view.html"
    )
    # The helper must read cgr_dedup_status from the record
    assert re.search(r"p\.cgr_dedup_status", VIEW_HTML), (
        "expected cgr_dedup_status to be read from the pensioner record"
    )


def test_view_html_badge_classes_for_all_statuses():
    """CSS must include styling for all four dedup statuses."""
    for status in ("duplicate", "follow_up_candidate", "clear", "no_fag_match"):
        assert f".cgr-dedup-badge.{status}" in VIEW_HTML, (
            f"expected CSS class for cgr-dedup-badge.{status}"
        )


# ============================================================
# Filter integration
# ============================================================
def test_view_html_status_filter_includes_cgr_options():
    """The status filter dropdown must include CGR dedup options."""
    assert 'value="cgr_duplicate"' in VIEW_HTML, (
        'expected <option value="cgr_duplicate"> in the status filter'
    )
    assert 'value="cgr_follow_up"' in VIEW_HTML
    assert 'value="cgr_clear"' in VIEW_HTML
    assert 'value="cgr_no_match"' in VIEW_HTML


def test_view_html_filter_logic_handles_cgr_statuses():
    """The applyFilter function must filter by cgr_dedup_status."""
    # Look for the four `if` checks we added
    assert re.search(
        r"statusVal\s*===\s*['\"]cgr_duplicate['\"].*?cgr_dedup_status\s*!==\s*['\"]duplicate['\"]",
        VIEW_HTML, re.DOTALL,
    ), "expected filter check for cgr_duplicate"
    assert re.search(
        r"statusVal\s*===\s*['\"]cgr_follow_up['\"].*?cgr_dedup_status\s*!==\s*['\"]follow_up_candidate['\"]",
        VIEW_HTML, re.DOTALL,
    )
    assert re.search(
        r"statusVal\s*===\s*['\"]cgr_clear['\"].*?cgr_dedup_status\s*!==\s*['\"]clear['\"]",
        VIEW_HTML, re.DOTALL,
    )
    assert re.search(
        r"statusVal\s*===\s*['\"]cgr_no_match['\"].*?cgr_dedup_status\s*!==\s*['\"]no_fag_match['\"]",
        VIEW_HTML, re.DOTALL,
    )


# ============================================================
# CGR panel REMOVAL
# ============================================================
def test_view_html_no_cgr_panel_render():
    """The CGR side panel (renderCgrPanel) must be gone."""
    assert "renderCgrPanel" not in VIEW_HTML, (
        "renderCgrPanel must be removed (CGR is now a dedup signal, "
        "not a side panel)"
    )
    assert "renderCgrConflicts" not in VIEW_HTML
    # And the old CSS classes
    assert ".cgr-panel {" not in VIEW_HTML
    assert ".cgr-conflict {" not in VIEW_HTML
    assert ".match-badge.strong" not in VIEW_HTML
    assert ".cgr-died-state" not in VIEW_HTML


def test_view_html_stats_bar_includes_cgr_pills():
    """The stats bar should show CGR dedup counts."""
    # Just check the structural presence of all four label strings
    for label in ("CGR dup", "CGR follow-up", "CGR clear", "CGR+FaG miss"):
        assert label in VIEW_HTML, f"expected stats pill: {label}"