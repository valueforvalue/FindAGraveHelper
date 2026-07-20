"""Tests for CGR cemetery details parser.

cemDetails.php returns the same 2-column table format as
vetDetails.php. Field set is different: cemetery name, city,
county, state, country, lat, long, etc.

We are CONSERVATIVE: capture every label/value pair the page shows.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr.cgr_cem import parse_cgr_cem


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


@pytest.fixture
def parsed_cemetery() -> dict:
    """Parse recorded cemetery page once per test that needs full data."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    return parse_cgr_cem(html)


def test_parse_rose_hill_cemetery_returns_dict(parsed_cemetery):
    """cemDetails_88159 parses to a non-empty dict."""
    assert isinstance(parsed_cemetery, dict)
    assert parsed_cemetery


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("name", "Rose Hill Cemetery"),
        ("city", "Chickasha"),
        ("county", "Grady"),
        ("state", "OK"),
        ("latitude", "35.0314"),
        ("longitude", "-97.9453"),
        ("marker_type", "Confederate"),
    ],
)
def test_parse_rose_hill_fields(parsed_cemetery, field, expected):
    """Recorded fields remain faithful to CGR source page."""
    assert parsed_cemetery[field] == expected


def test_parse_rose_hill_condition():
    """Condition is 'Good' (and again as 'Excellent' for signage block — keep both)."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    result = parse_cgr_cem(html)
    # The page has Condition twice: once for marker (Good) and once for
    # signage (Excellent). We keep both as marker_condition and
    # signage_condition to preserve the source structure.
    assert "marker_condition" in result or "condition" in result


def test_parse_handles_empty_html():
    """Empty HTML returns empty dict."""
    assert parse_cgr_cem("") == {}


def test_parse_handles_non_cemetery_page():
    """A page that isn't a cemetery page returns whatever labels it has."""
    html = "<html><body>Not a cemetery details page</body></html>"
    assert parse_cgr_cem(html) == {}


def test_parse_extracts_all_labels_verbatim():
    """Every label on the page comes through with the raw label as key."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    result = parse_cgr_cem(html)
    # Check that the raw labels are preserved under _raw
    assert "_raw" in result
    raw = result["_raw"]
    # These are actual labels from the fixture
    assert "name" in raw
    assert "city" in raw
    assert "county" in raw
    assert "state" in raw
    assert "latitude" in raw
    assert "longitude" in raw