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


def test_source_card_link_present():
    """The pension card link (source card) renders when backlink present."""
    assert 'source card' in VIEW_HTML, "expected 'source card' label"


def test_application_action_present():
    """Pension application opens through view-source action."""
    pattern = (
        r'p\.backlink\s*\?\s*`<button[^`]*data-action="view-source"'
        r'[^`]*data-url="\$\{escapeHtml\(fixDigitalPrairieUrl\(p\.backlink\)\)\}"'
        r'[^`]*>application</button>`'
    )
    assert re.search(pattern, VIEW_HTML, re.DOTALL), (
        "expected application view-source button wired to backlink"
    )


def test_backlink_field_consumed_in_normalize():
    """normalize_state_record in view.html reads p.backlink."""
    # Both the legacy and unified branches must read it.
    assert re.search(r"backlink\s*:\s*rec\.backlink", VIEW_HTML), \
        "expected backlink read from rec in normalize"


def test_backlink_in_search_haystack():
    """The search filter should include backlink so users can search by app URL."""
    # The haystack array near filter logic should contain pensioncard_backlink's
    # companion: backlink.
    assert re.search(r"haystack.*pensioncard_backlink.*backlink|backlink.*pensioncard_backlink",
                     VIEW_HTML, re.DOTALL), \
        "expected backlink in search haystack"


def test_digital_prairie_backlink_rewrite_helper():
    """The digitalprairie.ok.gov URL migration (post-2026-07) left
    /digital/singleitem/... URLs returning soft-404 pages. The
    /digital/api/singleitem/... URLs still work (they return JSON,
    not a browsable page, but at least not a 404).

    view.html MUST rewrite pensioncard_backlink and backlink URLs
    from /digital/singleitem/ → /digital/api/singleitem/ at render
    time so the link isn't broken. See issue #13.
    """
    # A helper function or inline rewrite must exist
    assert re.search(
        r"/digital/singleitem/.*?/digital/api/singleitem/",
        VIEW_HTML, re.DOTALL,
    ) or "fixDigitalPrairieUrl" in VIEW_HTML or "rewriteDigitalPrairie" in VIEW_HTML, \
        "expected a URL rewrite from /digital/singleitem/ to /digital/api/singleitem/"


def test_iiif_thumbnail_helper_present():
    """view.html must embed IIIF pension card thumbnails directly
    (the digitalprairie human-facing page URLs all 404). The
    IIIF image endpoint works: /iiif/2/pensioncard:{page_id}/full/300,/0/default.jpg.
    """
    # buildIiifThumbnailUrl helper exists
    assert "buildIiifThumbnailUrl" in VIEW_HTML, \
        "expected buildIiifThumbnailUrl helper for IIIF image embedding"
    # Pattern uses the pensioncard: collection + page_id
    assert re.search(
        r"iiif/2/pensioncard:\$\{[^}]+\}|iiif/2/pensioncard:.*page_id",
        VIEW_HTML,
    ), "expected IIIF URL pattern with pensioncard: prefix and page_id"


def test_pensioncard_image_renderer():
    """renderPensionerCardImage builds <img> tags from pensioncard_pages."""
    assert "renderPensionerCardImage" in VIEW_HTML, \
        "expected renderPensionerCardImage function"
    # It must read pensioncard_pages from the record
    assert re.search(r"pensioncard_pages", VIEW_HTML), \
        "expected pensioncard_pages field to be read in view.html"
    # It must produce <img> tags
    assert re.search(r"<img\s+src=", VIEW_HTML), \
        "expected <img src=...> rendering"
    assert "buildIiifThumbnailUrl" in VIEW_HTML, \
        "IIIF URL builder must be wired into the renderer"


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

def test_dd_in_local_badge_present():
    """view.html shows a badge for dd_in_local status."""
    assert "dd-badge" in VIEW_HTML, "expected dd-badge class in view.html"
    assert "in DD" in VIEW_HTML or "✓ in DD" in VIEW_HTML, \
        "expected in-DD label"


def test_dd_new_find_badge_present():
    """view.html shows a NEW FIND badge for new finds (not in DD)."""
    assert "NEW FIND" in VIEW_HTML, "expected 'NEW FIND' label"
    assert "dd-badge.new" in VIEW_HTML, "expected dd-badge.new style"


def test_dd_field_in_js():
    """JS reads p.dd_in_local to render the badge."""
    assert re.search(r"p\.dd_in_local", VIEW_HTML) or re.search(r"dd_in_local", VIEW_HTML), \
        "expected dd_in_local referenced in view.html"


# ============================================================
# Schema drift guard (issue #9)
# ============================================================
# scripts/view.html's JS normalizer must read every field that
# scripts/state/schema.py::PensionerRecord (plus the derived
# fields from state_normalize.py) carries. Drift here means a
# JSONL field changes on the Python side and the UI silently
# misses it.
def _view_html_field_set() -> set:
    """Extract the set of rec.X field references from the JS
    normalizer in view.html."""
    m = re.search(
        r"function normalizeStateRecord\(rec\) \{(.*?)^}",
        VIEW_HTML,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "normalizeStateRecord function not found in view.html"
    return set(re.findall(r"rec\.([a-z_][a-z_0-9]*)", m.group(1)))


def _python_field_set() -> set:
    """Set of field names in scripts/state/schema.PensionerRecord
    (typed front) plus the derived fields from state_normalize."""
    from scripts.state.schema import PensionerRecord
    from dataclasses import fields
    typed = {f.name for f in fields(PensionerRecord())}
    # Derived fields — produced by state_normalize.normalize_state_record
    derived = {
        "status", "ranked_candidates", "best_score",
        "best_candidate", "strategies_run",
    }
    return typed | derived


def test_view_html_field_set_matches_schema():
    """JS normalizer must read every Python-typed PensionerRecord field.

    Failure indicates a drift between scripts/state/schema.py and
    scripts/view.html — the Python side added a field but the JS
    side never picked it up, so the UI silently misses it.

    The reverse direction (JS reads more fields than Python types)
    is allowed: those are typically aliases or fallbacks the JS
    normalizer tolerates from legacy state.jsonl files.
    """
    py_set = _python_field_set()
    js_set = _view_html_field_set()
    missing_in_js = py_set - js_set
    assert not missing_in_js, (
        f"view.html JS normalizer does not read these "
        f"PensionerRecord fields: {sorted(missing_in_js)}. "
        f"Either add the read in normalizeStateRecord, or remove "
        f"the field from scripts/state/schema.py."
    )
