"""Tests for CGR vetDetails page parser.

The CGR vetDetails.php page returns a 2-column HTML table. Each
row is <td>label</td><td>value</td>. Labels repeat (e.g. 'City',
'State' appear twice — once for birth, once for death).

We parse to a dict keyed by both the raw label AND a canonical
key when the label is recognizable. Birth vs death fields get
distinct keys.

We are CONSERVATIVE: we extract every label/value pair the page
shows. We don't infer fields that aren't present.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr.cgr_vet import parse_cgr_vet


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


@pytest.fixture
def parsed_vet() -> dict:
    """Parse recorded vet page once per test that needs full fixture data."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    return parse_cgr_vet(html)


def test_parse_william_looney_vet_returns_dict(parsed_vet):
    """Vet details page parses to a non-empty dict."""
    assert isinstance(parsed_vet, dict)
    assert parsed_vet


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("first_name", "William"),
        ("last_name", "Looney"),
        ("middle_name", "G"),
        ("aka", "Guy"),
        ("enlisted", "1862-03-08"),
        ("rank", "Pvt"),
        ("unit", "34 TX"),
        ("company", "H"),
        ("born", "1840-05-24"),
        ("birth_state", "MN"),
        ("died", "1932-02-28"),
        ("died_state", "OK"),
        ("source", "Okla. SCV Archives"),
    ],
)
def test_parse_william_looney_fields(parsed_vet, field, expected):
    """Recorded fields remain faithful to CGR source page."""
    assert parsed_vet[field] == expected


def test_parse_william_looney_spouse(parsed_vet):
    """Spouse keeps maiden name from source text."""
    assert "Martha Ann (Williams)" in parsed_vet["spouse"]


def test_parse_handles_empty_html():
    """Empty HTML returns empty dict (no crash)."""
    assert parse_cgr_vet("") == {}


def test_parse_handles_page_without_vet_data():
    """A page that's not a vetDetails page returns whatever labels it has."""
    html = "<html><body>Not a vet details page</body></html>"
    assert parse_cgr_vet(html) == {}


def test_parse_distinguishes_birth_and_death_state():
    """'State' appears twice on the page (birth, death) — parser keeps both
    distinct via birth_state / died_state keys, plus a raw `states` list."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    result = parse_cgr_vet(html)
    assert "birth_state" in result
    assert "died_state" in result
    # The raw list preserves order
    assert result["states"] == ["MN", "OK"]


def test_parse_extracts_birth_and_death_city():
    """Same for City — both birth and death cities captured."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    result = parse_cgr_vet(html)
    assert "birth_city" in result
    assert "death_city" in result
    # Both empty in the fixture (William Looney's record has no city)
    assert result["birth_city"] == ""
    assert result["death_city"] == ""


def test_parse_does_not_assume_relationship():
    """The parser records 'spouse' as a string. It does NOT try to
    identify whether the spouse is the widow, current wife, etc."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    result = parse_cgr_vet(html)
    # The spouse value is captured verbatim
    assert "Martha Ann (Williams)" in result["spouse"]


def test_parse_preserves_source_metadata():
    """The 'Source' field is captured (useful for OK records specifically)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    result = parse_cgr_vet(html)
    assert result["source"] == "Okla. SCV Archives"