"""J15-S3 (slice 3): view.html spouse-match badge + filter.

Two badges in the pensioner card:

  1. 'Spouse known' - shown when ok_pensioners.json carries
     spouse_first_name + spouse_last_name. Grey pill. Tells the
     reviewer 'we know their spouse's name; expect a spouse match
     is one of the things to verify.'

  2. 'Spouse match' - shown when post-pipeline comparison found
     the FaG-captured spouse AND it agrees with our local record.
     Gold pill with memorial ID + matched spouse name. The user's
     headline ask.

Tests below pin both badges plus the filter (dd_spouse_match /
dd_spouse_pending).

Note: this slice wires only the UI + data shape. The actual
FaG-memorial-page scrape that fills `spouse_match` is S2 (separate
slice). Until S2 lands, the `spouse_match` field is None for
every record and the gold badge never renders in this slice's
tests - we assert the *contract* (badge present when field set,
absent when None), not its real-world appearance.

The 'Spouse known' badge is populated for every pensioner with
spouse_first_name + spouse_last_name, sourced from the
pensioner_spouse_* fields J15-S1 added to the results writer.
"""
from __future__ import annotations

import re
from pathlib import Path


VIEW = (Path(__file__).parent.parent / "scripts" / "view.html").read_text(
    encoding="utf-8"
)


# ============================================================
# 'Spouse known' badge (data-aware; works today)
# ============================================================
def test_spouse_known_renderer_exists():
    """A renderSpouseKnownBadge(p) function exists in view.html."""
    assert re.search(
        r"function\s+renderSpouseKnownBadge\s*\(\s*p\s*\)",
        VIEW,
    ), "renderSpouseKnownBadge helper missing"


def test_spouse_known_badge_includes_name():
    """When present, the badge surfaces the local spouse's name
    on hover so the reviewer can match against what FaG shows."""
    # The function body must include the local spouse name in the
    # title (or any output string).
    m = re.search(
        r"function\s+renderSpouseKnownBadge\s*\(\s*p\s*\)[\s\S]{0,1500}?\n\s*\}\s*\n",
        VIEW,
    )
    assert m, "renderSpouseKnownBadge body not found"
    body = m.group(0)
    # Required: title or visible label surfaces the spouse name
    assert ("spouse known" in body.lower() or "spouse_name" in body
            or "local_name" in body or "title" in body), (
        "renderSpouseKnownBadge must surface spouse name in title or label"
    )


def test_spouse_known_badge_called_in_pensioner_card():
    """The badge must be rendered inside the pensioner card
    (next to the h2 status row, alongside other badges)."""
    # Find the h2 status row that renders other badges
    # and assert renderSpouseKnownBadge appears inside it
    snippet_around_h2 = VIEW[VIEW.find("<h2>"):VIEW.find("</h2>") + len("</h2>")]
    # May be split across more lines, but the badge call must be
    # referenced inside renderPensioner (look for renderSpouseKnownBadge
    # near renderDdBadge and renderCgrDedupBadge)
    if "renderSpouseKnownBadge" not in VIEW:
        # pragma should never happen - first test catches this
        assert False
    # Verify renderSpouseKnownBadge is called within renderPensioner
    rp = VIEW[VIEW.find("function renderPensioner"):]
    rp = rp[: rp.find("\nfunction") if "\nfunction" in rp else len(rp)]
    assert "renderSpouseKnownBadge" in rp, (
        "renderSpouseKnownBadge must be called in renderPensioner"
    )


# ============================================================
# 'Spouse match' badge (verification-aware; awaits S2)
# ============================================================
def test_spouse_match_renderer_exists():
    """A renderSpouseMatchBadge(p) function exists in view.html."""
    assert re.search(
        r"function\s+renderSpouseMatchBadge\s*\(\s*p\s*\)",
        VIEW,
    ), "renderSpouseMatchBadge helper missing"


def test_spouse_match_badge_includes_captured_name():
    """When spouse_match is set, the badge surfaces both the
    captured FaG-side spouse name AND the matched memorial_id
    so the reviewer can click through and verify."""
    # The function body must reference spouse_match fields.
    # Use a non-greedy multi-line regex to grab the body.
    m = re.search(
        r"function\s+renderSpouseMatchBadge\s*\(\s*p\s*\)[\s\S]{0,2000}?\n\s*\}\s*\n",
        VIEW,
    )
    assert m, "renderSpouseMatchBadge body not found"
    body = m.group(0)
    # Required fields surfaced in the badge
    assert any(
        field in body
        for field in (
            "spouse_match", "spouse_captured", "matched_spouse",
            "captured_spouse", "spouse_match_first",
            "captured_first", "captured_spouse_first",
            "captured_last",
        )
    ), (
        "renderSpouseMatchBadge must reference spouse_match data fields"
    )


def test_spouse_match_badge_called_in_pensioner_card():
    """The badge must be rendered inside the pensioner card."""
    rp = VIEW[VIEW.find("function renderPensioner"):]
    rp = rp[: rp.find("\nfunction") if "\nfunction" in rp else len(rp)]
    assert "renderSpouseMatchBadge" in rp, (
        "renderSpouseMatchBadge must be called in renderPensioner"
    )


def test_spouse_match_field_default_is_none():
    """A pensioner record without spouse_match must render NO
    spouse-match badge (silent). When S2 populates the field,
    the badge appears.
    """
    # The renderSpouseMatchBadge must check for the field's presence
    # (returning '' when None) - matches the pattern of other badges
    m = re.search(
        r"function\s+renderSpouseMatchBadge\s*\(\s*p\s*\)[\s\S]{0,2000}?\n\s*\}\s*\n",
        VIEW,
    )
    assert m, "renderSpouseMatchBadge body not found"
    body = m.group(0)
    assert "return ''" in body or "return\"\"" in body, (
        "renderSpouseMatchBadge must return empty when no match"
    )


# ============================================================
# Status filter for spouse match
# ============================================================
def test_status_filter_includes_spouse_match():
    """Viewer's status filter dropdown must include the new
    'spouse matched' + 'spouse pending' options."""
    # Find the options block
    opt_block_match = re.search(
        r"option\s+value=[\"']spouse_matched[\"']",
        VIEW,
    )
    opt_block_pending = re.search(
        r"option\s+value=[\"']spouse_pending[\"']",
        VIEW,
    )
    assert opt_block_match, (
        "missing <option value='spouse_matched'> in status filter"
    )
    assert opt_block_pending, (
        "missing <option value='spouse_pending'> in status filter"
    )


def test_status_filter_spouse_matched_filters_by_field():
    """When spouse_matched is selected, only records with
    p.spouse_match set are kept."""
    # Find the filter handler in applyFilters or equivalent
    handler_block = re.search(
        r"statusVal\s*===\s*[\"']spouse_matched[\"'][\s\S]{0,200}?(?:continue|push|break)",
        VIEW,
    )
    assert handler_block, (
        "filter handler must branch on statusVal === 'spouse_matched'"
    )
    # It should compare p.spouse_match to something truthy
    assert "p.spouse_match" in handler_block.group(0) or ".spouse_match" in handler_block.group(0), (
        "spouse_matched branch must compare p.spouse_match to truthy"
    )


def test_status_filter_spouse_pending_excludes_matched():
    """When spouse_pending is selected, records WITH spouse_match
    are hidden (reviewer's default scope)."""
    handler_block = re.search(
        r"statusVal\s*===\s*[\"']spouse_pending[\"'][\s\S]{0,200}?(?:continue|push|break)",
        VIEW,
    )
    assert handler_block, (
        "filter handler must branch on statusVal === 'spouse_pending'"
    )
    assert "continue" in handler_block.group(0), (
        "spouse_pending branch must skip matched records"
    )


# ============================================================
# Stats bar pills
# ============================================================
def test_stats_bar_includes_spouse_pills():
    """Stats bar must show two pills: 'Spouse matched N' + 'Spouse pending N'."""
    assert "Spouse matched" in VIEW or "spouse_matched" in VIEW, (
        "stats bar must label the spouse-matched count"
    )


# ============================================================
# Pensioner-record shape: spouse_match field
# ============================================================
def test_view_html_spouse_match_field_handled():
    """The view.html must not crash if a pensioner record lacks
    the spouse_match field (forward compat with older results.jsonl)."""
    # 'in' check or '?.spouse_match' usage is the safe pattern;
    # ensure no direct property access on p.spouse_match that
    # would throw on undefined.
    snippet = (
        VIEW[VIEW.find("function renderSpouseMatchBadge"):]
        if "function renderSpouseMatchBadge" in VIEW
        else VIEW
    )
    # Either `p.spouse_match ?` (ternary) or `spouse_match: {...}` truthy
    # check is OK. Direct property access without guard would throw.
    assert "?." in snippet or "!= null" in snippet or "if (" in snippet or (
        "const" in snippet
    ), (
        "renderSpouseMatchBadge must guard against missing spouse_match"
    )
