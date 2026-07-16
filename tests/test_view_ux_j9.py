"""Tests for J9: layout fix + embedded JSONL auto-load.

User feedback: notes input was stretching full screen (layout
bug), and view.html wasn't auto-loading results.jsonl when
opened directly from file:// (fetch() blocked by the browser).

J9 fixes:
1. Actions row is now flex; the per-pensioner notes input has a
   bounded max-width so it doesn't stretch across the page.
2. The runner injects the results.jsonl as a <script
   type="application/json"> block at copy time, so view.html
   works from file:// without needing a server.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VIEW_HTML = (ROOT / "scripts" / "view.html").read_text(encoding="utf-8")


# ============================================================
# Layout fix: notes input should not stretch
# ============================================================
def test_actions_row_is_flex():
    """.actions must be a flex container so the notes input
    has a sensible width."""
    assert re.search(
        r"\.actions\s*\{[^}]*display:\s*flex",
        VIEW_HTML, re.DOTALL,
    ), "expected .actions to be a flex container"


def test_actions_notes_input_has_bounded_width():
    """The per-pensioner notes input inside .actions must have a
    max-width so it doesn't stretch the page."""
    # CSS rule for .actions input[data-action="notes"] with max-width
    assert re.search(
        r'\.actions\s+input\[data-action=["\']notes["\']\][^}]*max-width',
        VIEW_HTML, re.DOTALL,
    ), "expected .actions input[data-action=\"notes\"] to have a max-width"


def test_actions_row_no_inline_flex_stretch():
    """The notes input should NOT have inline style="flex:1;..." —
    that's what caused the stretch-across-page bug. CSS handles it."""
    # Find the per-pensioner notes input template
    m = re.search(
        r'data-action=["\']notes["\']\s*data-pid=',
        VIEW_HTML,
    )
    assert m, "expected to find the per-pensioner notes input"
    # The substring after `data-pid=...` should not contain flex:1 inline
    # Look for the surrounding context
    start = m.start()
    snippet = VIEW_HTML[start:start + 500]
    assert "flex:1" not in snippet, (
        "per-pensioner notes input still has inline style=\"flex:1;...\" "
        "which causes the stretch-across-page bug"
    )


def test_candidate_notes_no_inline_width_stretch():
    """The per-candidate notes input should not have inline
    width:100% style (CSS class handles it)."""
    m = re.search(
        r'data-action=["\']candidate-notes["\']',
        VIEW_HTML,
    )
    assert m, "expected to find the candidate-notes input"
    start = m.start()
    snippet = VIEW_HTML[start - 200:start + 200]
    assert "width:100%" not in snippet, (
        "per-candidate notes input still has inline width:100% — "
        "the CSS class .candidate-notes input handles width now"
    )


# ============================================================
# Auto-load: embedded JSONL + fetch fallback
# ============================================================
def test_view_html_has_embedded_data_placeholder():
    """view.html must have a placeholder that the runner
    replaces with the embedded JSONL block."""
    assert "EMBEDDED_RESULTS_JSONL" in VIEW_HTML, (
        "expected EMBEDDED_RESULTS_JSONL placeholder so the runner "
        "can inject the JSONL into the page"
    )


def test_view_html_tryAutoLoad_reads_embedded_first():
    """tryAutoLoad must check the embedded JSONL block before
    attempting fetch() (which fails under file://)."""
    # Find the tryAutoLoad function — use a manual scan since
    # the function body has nested braces (regex non-greedy stops early)
    start = VIEW_HTML.find("async function tryAutoLoad(")
    assert start >= 0, "expected to find tryAutoLoad function"
    # Scan from `start` for the matching `};` at column 0
    body_start = VIEW_HTML.find("{", start)
    assert body_start >= 0
    depth = 0
    i = body_start
    while i < len(VIEW_HTML):
        ch = VIEW_HTML[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = VIEW_HTML[body_start:i]
    # Embedded check must come BEFORE the fetch() call
    emb_idx = body.find("embedded-results-jsonl")
    fetch_idx = body.find("await fetch(")
    assert emb_idx >= 0, "expected embedded-results-jsonl reference"
    assert fetch_idx >= 0, "expected fetch() fallback"
    assert emb_idx < fetch_idx, (
        "tryAutoLoad checks fetch() before the embedded block; "
        "file:// users will see no auto-load"
    )


def test_view_html_placeholder_in_main_body():
    """The placeholder must be in the document body (not head),
    so the JS can read it at load time."""
    # Find the <main> tag position
    main_idx = VIEW_HTML.find('<main id="results">')
    placeholder_idx = VIEW_HTML.find("EMBEDDED_RESULTS_JSONL")
    assert main_idx >= 0 and placeholder_idx >= 0
    assert placeholder_idx > main_idx, (
        "EMBEDDED_RESULTS_JSONL placeholder must come after <main>"
    )


# ============================================================
# Runner-side: copy_view_html_if_missing embeds the data
# ============================================================
def test_runner_uses_placeholder_constant():
    """The runner must reference the same placeholder constant
    as the view.html uses."""
    from scripts.pipeline import run_unified
    assert hasattr(run_unified, "EMBEDDED_DATA_PLACEHOLDER"), (
        "run_unified.EMBEDDED_DATA_PLACEHOLDER must be defined"
    )
    assert run_unified.EMBEDDED_DATA_PLACEHOLDER == "<!--EMBEDDED_RESULTS_JSONL-->", (
        "placeholder must match the view.html comment"
    )


def test_copy_view_html_embeds_results(tmp_path):
    """copy_view_html_if_missing with results_path injects the
    JSONL as a <script type="application/json"> block."""
    from scripts.pipeline.run_unified import copy_view_html_if_missing
    src = tmp_path / "view.html"
    src.write_text(
        "<html><body><main></main>\n"
        "<!--EMBEDDED_RESULTS_JSONL-->\n"
        "</body></html>",
        encoding="utf-8",
    )
    results = tmp_path / "results.jsonl"
    results.write_text('{"pensioner_id": 1}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    copied = copy_view_html_if_missing(
        src, out_dir, results_path=results,
    )
    assert copied is True
    copied_html = (out_dir / "view.html").read_text(encoding="utf-8")
    assert 'id="embedded-results-jsonl"' in copied_html
    assert '{"pensioner_id": 1}' in copied_html
    # Placeholder removed
    assert "<!--EMBEDDED_RESULTS_JSONL-->" not in copied_html


def test_copy_view_html_without_results_keeps_page_loadable(tmp_path):
    """If results.jsonl doesn't exist yet, the placeholder is
    dropped (no empty script block) but the page still loads."""
    from scripts.pipeline.run_unified import copy_view_html_if_missing
    src = tmp_path / "view.html"
    src.write_text(
        "<html><body><main></main>\n"
        "<!--EMBEDDED_RESULTS_JSONL-->\n"
        "</body></html>",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # results_path that doesn't exist
    results = tmp_path / "missing.jsonl"
    copy_view_html_if_missing(
        src, out_dir, results_path=results,
    )
    copied_html = (out_dir / "view.html").read_text(encoding="utf-8")
    # Placeholder removed but no empty script block added
    assert "<!--EMBEDDED_RESULTS_JSONL-->" not in copied_html
    assert 'id="embedded-results-jsonl"' not in copied_html
    # Page structure intact
    assert "<main></main>" in copied_html