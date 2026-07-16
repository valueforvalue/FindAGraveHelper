"""Tests for J10: rich JSON export.

The CSV export was lossy — it didn't include the full FaG
candidates reviewed, the full pensioner metadata, or the CGR
match summary. Reviewer workflow needs a self-contained export
that can be reopened in a separate session without losing
context.

J10:
- Switch export to JSON (downloads as .json, not .csv)
- Embed per-pensioner: decision + full pensioner record + full
  candidates reviewed + cgr_match_summary
- Top-level metadata: version, exported_at, source_file, stats
- Import accepts the rich JSON shape (back-compat with the
  flat old shape)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VIEW_HTML = (ROOT / "scripts" / "view.html").read_text(encoding="utf-8")


# ============================================================
# Source-level: the export is now JSON
# ============================================================
def test_view_html_export_is_json():
    """The export button must produce a .json file, not .csv."""
    # Find the export click handler block
    m = re.search(
        r"getElementById\(['\"]exportBtn['\"]\)\.addEventListener\(['\"]click['\"],"
        r"\s*\(\)\s*=>\s*\{(.+?)\n\}\);",
        VIEW_HTML, re.DOTALL,
    )
    assert m, "expected to find exportBtn click handler"
    body = m.group(1)
    # Must use JSON.stringify (not CSV join)
    assert "JSON.stringify" in body, (
        "export handler must use JSON.stringify; CSV export was lossy"
    )
    assert "Blob" in body and "application/json" in body, (
        "export must use a JSON Blob (Content-Type: application/json)"
    )
    # And the download filename must end in .json, not .csv
    # Use a non-greedy match that allows date-format chars (+, -)
    assert re.search(
        r"download\s*=\s*['\"].*?\.json['\"]",
        body, re.DOTALL,
    ), "export filename must end in .json"
    # And the OLD CSV path should be gone (no .csv mentions at all)
    assert ".csv" not in body, (
        "export handler still references .csv; the switch to JSON "
        "must remove all CSV path code"
    )


def test_view_html_export_includes_pensioner_metadata():
    """The export must embed the full pensioner record (not just
    the columns the old CSV carried)."""
    # The export builds a decisionsOut map whose value includes
    # the full pensioner object under the 'pensioner' key.
    assert re.search(
        r"pensioner:\s*p\b|pensioner:\s*pensioner",
        VIEW_HTML,
    ), "expected export to embed the full pensioner object"


def test_view_html_export_includes_candidates():
    """The export must embed the full ranked_candidates so the
    reviewer can see what they were looking at."""
    # The export handler should pull ranked_candidates from the
    # pensioner record, not just memorial_id + slug
    assert re.search(
        r"ranked_candidates|c\.ranked_candidates|p\.ranked_candidates",
        VIEW_HTML,
    ), "expected export to include ranked_candidates from the pensioner"


def test_view_html_export_includes_cgr_match():
    """The export must embed cgr_match_summary for follow-up
    candidates so reviewer can see WHY CGR flagged them."""
    assert re.search(
        r"cgr_match_summary",
        VIEW_HTML,
    ), "expected cgr_match_summary in export"


def test_view_html_export_top_level_metadata():
    """The export must include version + exported_at + source_file
    + stats at the top level."""
    # Look for the export payload structure
    assert re.search(
        r"version\s*:\s*1|version:\s*\d+",
        VIEW_HTML,
    ), "expected version field in export"
    assert re.search(
        r"exported_at|new Date\(\)\.toISOString",
        VIEW_HTML,
    ), "expected exported_at timestamp in export"
    assert re.search(
        r"source_file|source_filename|results\.jsonl",
        VIEW_HTML,
    ), "expected source_file in export"


# ============================================================
# Import accepts the rich JSON shape (back-compat with old)
# ============================================================
def test_view_html_import_accepts_rich_json():
    """The import button must accept both:
      - the new rich shape: {decisions: {...}, stats, ...}
      - the old flat shape: {pensioner_id: {memorial_id, ...}}
    The import must merge decisions (not replace the whole dict).
    """
    import_btn = re.search(
        r"getElementById\(['\"]importFile['\"]\)\.addEventListener\(['\"]change['\"],"
        r"\s*async\s*\(e\)\s*=>\s*\{(.+?)\n\}\);",
        VIEW_HTML, re.DOTALL,
    )
    assert import_btn, "expected to find importFile change handler"
    body = import_btn.group(1)
    # Must accept the rich shape
    assert "decisions" in body or ".decisions" in body, (
        "import must check for .decisions (rich shape) OR fall back to "
        "flat shape"
    )
    # And iterate either as data.decisions OR Object.entries(data)
    assert "Object.entries" in body or "data.decisions" in body


# ============================================================
# Button label reflects the new format
# ============================================================
def test_export_button_text():
    """The export button label should still say 'Export decisions'
    (or similar) — not 'Export CSV' (which would confuse the
    reviewer into looking for a CSV file)."""
    m = re.search(
        r"<button[^>]*id=['\"]exportBtn['\"][^>]*>([^<]*)</button>",
        VIEW_HTML,
    )
    assert m
    label = m.group(1).strip()
    assert "csv" not in label.lower(), (
        f"export button label still says CSV: {label!r}"
    )
    assert "export" in label.lower(), f"expected 'export' in label: {label!r}"


# ============================================================
# J10b: view.html can load + view its own export
# ============================================================
def test_view_html_detects_export_format():
    """parseInput must distinguish between results.jsonl (raw
    records) and the fag-decisions export (rich JSON). The
    export has a top-level `version` + `decisions` field."""
    # The parser should branch on the presence of a 'version' key
    # or a 'kind === "export"' discriminator
    has_version_check = re.search(
        r"data\.version|data\[.version.\]|\.version\b|\.decisions\b|kind\s*===\s*.export.|kind:\s*.export.",
        VIEW_HTML,
    )
    assert has_version_check, (
        "expected parseInput / loader to detect the export 'version' field"
    )


def test_view_html_export_metadata_banner():
    """When loading an export, the page must show a banner with
    the export's version + exported_at + stats so the reviewer
    knows what they're looking at."""
    # Look for a banner that surfaces exported_at + version
    assert re.search(
        r"exported_at|exportVersion|exportStats",
        VIEW_HTML,
    ), "expected an export metadata banner showing version + timestamp"


def test_view_html_export_renders_decisions_in_view_mode():
    """When loading an export, the page must reconstruct the
    pensioner records from decisions[pid].pensioner so they
    appear in the same reviewable list."""
    # The load logic should map Object.entries(data.decisions) and
    # use v.pensioner for each entry
    assert re.search(
        r"data\.decisions|\.decisions\)|data\[.decisions.\]",
        VIEW_HTML,
    ), "expected loader to use data.decisions as the source"


def test_view_html_export_hides_irrelevant_controls():
    """When viewing an export (not raw results), the per-pensioner
    actions that would edit decisions (Pick rank 1, View source,
    No match, etc.) are still useful but the FaG search button
    is NOT. The UI should not offer re-search."""
    # The export view should NOT show "Export decisions" again
    # (you can't export an export). It should still show import.
    # For now we just check that the export mode shows a banner
    # indicating readonly vs editable.
    assert re.search(
        r"read-?only|readOnly|isExport|exportMode|viewMode",
        VIEW_HTML,
    ), "expected a readonly/view-mode indicator in the export viewer"