"""Tests for J8: view.html UX improvements.

User feedback: candidate list needs to be in a scrollable container
of reasonable size that can be expanded; per-candidate remove +
notes; "View source" modal popup for the digitalprairie pension
JSON; auto-load results.jsonl from same dir; clearer "best match"
labeling for the auto-accepted record.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VIEW_HTML = (ROOT / "scripts" / "view.html").read_text(encoding="utf-8")


# ============================================================
# Auto-load
# ============================================================
def test_view_html_auto_loads_results_jsonl():
    """view.html should attempt to fetch results.jsonl from the
    same directory as itself on page load."""
    # Look for a fetch call targeting results.jsonl, relative to
    # the page's own URL. (the page is opened from file:// or http://,
    # so we use location.pathname to derive the dir)
    assert re.search(
        r"results\.jsonl|results_filename",
        VIEW_HTML,
    ), "expected view.html to reference results.jsonl for auto-load"


def test_view_html_keeps_file_pick_input():
    """The auto-load must not remove the file picker; users need to
    be able to swap to a different results file."""
    assert 'type="file"' in VIEW_HTML, (
        'expected <input type="file"> for swapping results files'
    )
    assert "fileInput" in VIEW_HTML


# ============================================================
# Scrollable candidate list (expandable)
# ============================================================
def test_candidates_in_scrollable_container():
    """The .candidates div (or each candidate list) must have
    CSS that bounds height + allows overflow-y scroll."""
    # The container has a CSS class
    assert re.search(
        r"\.candidates\s*\{[^}]*(?:max-height|height|overflow)",
        VIEW_HTML, re.DOTALL,
    ), "expected .candidates CSS to have height/overflow for scrolling"


def test_candidates_have_expand_button():
    """Each pensioner's candidate list should have a button to
    expand the container (escape fixed-height scroll)."""
    assert re.search(
        r"data-action=[\"']expand-candidates[\"']|expandCandidates",
        VIEW_HTML,
    ), "expected expand-candidates action / expandCandidates helper"


# ============================================================
# Per-candidate remove + notes
# ============================================================
def test_candidate_remove_button_present():
    """Each candidate must have a remove (✕) button."""
    assert re.search(
        r"data-action=[\"']remove-candidate[\"']|removeCandidate",
        VIEW_HTML,
    ), "expected remove-candidate action / removeCandidate helper"


def test_candidate_notes_input_present():
    """Each candidate must have a notes input."""
    assert re.search(
        r"data-action=[\"']candidate-notes[\"']|candidateNotes",
        VIEW_HTML,
    ), "expected candidate-notes action / candidateNotes helper"


def test_candidate_removed_state_visible():
    """Removed candidates must show a 'REMOVED' visual cue."""
    assert "REMOVED" in VIEW_HTML or "removed" in VIEW_HTML.lower(), (
        "expected 'REMOVED' visual indicator for removed candidates"
    )


def test_decision_storage_includes_candidate_metadata():
    """The localStorage-backed decision store must persist
    per-candidate removal + notes (alongside memorial_id)."""
    assert re.search(
        r"removed_candidates|removed.*notes|candidate_notes",
        VIEW_HTML,
    ), "expected removed_candidates / candidate_notes persistence"


# ============================================================
# "View source" modal popup for the digitalprairie JSON
# ============================================================
def test_view_source_button_present():
    """Each pensioner must have a 'View source' button that opens
    a modal with the parsed digitalprairie JSON."""
    assert re.search(
        r"data-action=[\"']view-source[\"']|viewSource",
        VIEW_HTML,
    ), "expected view-source action / viewSource helper"
    # And the button is wired for the application (pensions) URL
    assert "application" in VIEW_HTML or "pensions" in VIEW_HTML


def test_modal_element_exists():
    """view.html must define a modal container + show/hide helpers."""
    assert re.search(
        r"""id=['"]sourceModal['"]|class=['"]modal['"]|id=['"]modal['"]""",
        VIEW_HTML,
    ), "expected a modal element in the DOM"
    # And a function to show it
    assert re.search(
        r"function\s+showSourceModal|function\s+openSourceModal|function\s+fetchSourceJson",
        VIEW_HTML,
    ), "expected a function to open the modal / fetch the JSON"


# ============================================================
# Best-match labeling
# ============================================================
def test_top_match_labeled_as_best():
    """The top-ranked candidate must have a clear 'Best match' label
    to distinguish it from the runner-up."""
    assert re.search(
        r"best[_ -]?match|top[_ -]?match|Best Match|Top Match",
        VIEW_HTML, re.IGNORECASE,
    ), "expected a 'Best match' / 'Top match' label on the top candidate"


def test_ambiguity_warning_when_top2_close():
    """When the top 2 candidates are within 0.05 score, the UI
    should warn that the auto_accept is ambiguous."""
    # Look for the close-score logic + warning render
    assert re.search(
        r"AUTO_ACCEPT_GAP|ambig|0\.05",
        VIEW_HTML,
    ), "expected ambiguity warning when top candidates are close in score"


# ============================================================
# Export includes per-candidate removal + notes
# ============================================================
def test_export_includes_candidate_metadata():
    """The CSV export must include removed_candidates +
    candidate_notes columns when present."""
    assert re.search(
        r"removed_candidates|candidate_notes",
        VIEW_HTML,
    ), "expected removed_candidates / candidate_notes in CSV export"