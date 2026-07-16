"""Tests for J11: fix candidate-row layout (notes squashing info column).

User reported that the per-candidate notes input was smashing the
.info column to 0 width (causing the name to wrap character-by-
character). Root cause: .candidate is a flex row; .info had
`flex: 1; min-width: 0`; .score and .pick had intrinsic widths
that consumed all the space; .info shrank to 0.

Fix:
- .candidate .info: `min-width: 280px` (was 0)
- .candidate .rank: `flex-shrink: 0` (was 1)
- .candidate .candidate-notes: `order: 99; flex: 1 0 100%`
  so it forces onto a NEW row regardless of intrinsic widths
- .candidate .slug: `word-break: break-all` (so monospace slugs
  don't overflow)
- Removed the old `.candidate-notes` / `.candidate-notes input`
  rules that conflicted
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VIEW_HTML = (ROOT / "scripts" / "view.html").read_text(encoding="utf-8")


def test_info_column_has_min_width():
    """`.candidate .info` must have min-width: 280px so it never
    shrinks to 0 and forces the name text to wrap per character."""
    assert re.search(
        r"\.candidate\s+\.info\s*\{[^}]*min-width:\s*280px",
        VIEW_HTML, re.DOTALL,
    ), "expected .candidate .info to have min-width: 280px"


def test_candidate_notes_forces_new_row():
    """`.candidate .candidate-notes` must use `order: 99` (or
    similar) so it wraps onto a new row regardless of intrinsic
    widths of .score / .pick."""
    # The CSS class must have an `order` property
    assert re.search(
        r"\.candidate\s+\.candidate-notes\s*\{[^}]*order:\s*99",
        VIEW_HTML, re.DOTALL,
    ), "expected .candidate .candidate-notes to use order: 99 to force new row"


def test_rank_does_not_shrink():
    """`.candidate .rank` must have `flex-shrink: 0` so the
    "#1" label doesn't get compressed."""
    assert re.search(
        r"\.candidate\s+\.rank\s*\{[^}]*flex-shrink:\s*0",
        VIEW_HTML, re.DOTALL,
    ), "expected .candidate .rank to have flex-shrink: 0"


def test_slug_breaks_long_words():
    """`.candidate .slug` must `word-break: break-all` so
    monospace slugs like 'robert-william-adair' don't overflow
    the narrow info column."""
    assert re.search(
        r"\.candidate\s+\.slug\s*\{[^}]*word-break:\s*break-all",
        VIEW_HTML, re.DOTALL,
    ), "expected .candidate .slug to have word-break: break-all"


def test_old_orphan_candidate_notes_rules_removed():
    """The old `.candidate-notes` (without leading `.candidate`)
    rules must be removed — they conflict with the new
    `.candidate .candidate-notes` rules above and could re-shrink
    the notes input."""
    # The old rules had `flex-basis: 100%` without the parent
    # selector. After the J11 fix, they should be gone.
    assert not re.search(
        r"^\s*\.candidate-notes\s*\{[^}]*flex-basis:\s*100%",
        VIEW_HTML, re.MULTILINE,
    ), (
        "old .candidate-notes { flex-basis: 100% } rule still present; "
        "remove it (J11 uses .candidate .candidate-notes with order:99)"
    )


def test_actions_input_max_width_still_there():
    """J9 fix for the per-pensioner notes input (max-width: 480px)
    must still be in place — J11 only touches per-candidate layout."""
    assert re.search(
        r"\.actions\s+input\[data-action=.notes.\][^}]*max-width:\s*480px",
        VIEW_HTML, re.DOTALL,
    ), "expected .actions input[data-action=\"notes\"] to still have max-width: 480px"