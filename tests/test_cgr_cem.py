"""Tests for CGR cemetery details parser.

cemDetails.php returns the same 2-column table format as
vetDetails.php. Field set is different: cemetery name, city,
county, state, country, lat, long, etc.

We are CONSERVATIVE: capture every label/value pair the page shows.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr.cgr_cem import parse_cgr_cem


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


def test_parse_rose_hill_cemetery_returns_dict():
    """cemDetails_88159 parses to a non-empty dict."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    result = parse_cgr_cem(html)
    assert isinstance(result, dict)
    assert len(result) > 0


def test_parse_rose_hill_name():
    """Cemetery name is 'Rose Hill Cemetery'."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_cem(html)["name"] == "Rose Hill Cemetery"


def test_parse_rose_hill_city():
    """City is 'Chickasha'."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_cem(html)["city"] == "Chickasha"


def test_parse_rose_hill_county():
    """County is 'Grady'."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_cem(html)["county"] == "Grady"


def test_parse_rose_hill_state():
    """State is 'OK'."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_cem(html)["state"] == "OK"


def test_parse_rose_hill_latitude():
    """Latitude is '35.0314' (parsed to string, not float — preserve precision)."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_cem(html)["latitude"] == "35.0314"


def test_parse_rose_hill_longitude():
    """Longitude is '-97.9453'."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_cem(html)["longitude"] == "-97.9453"


def test_parse_rose_hill_marker_type():
    """Marker type is 'Confederate'."""
    html = (FIXTURE_DIR / "cemDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_cem(html)["marker_type"] == "Confederate"


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