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

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr_vet import parse_cgr_vet


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


def test_parse_william_looney_vet_returns_dict():
    """Vet details page parses to a non-empty dict."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    result = parse_cgr_vet(html)
    assert isinstance(result, dict)
    assert len(result) > 0


def test_parse_william_looney_first_name():
    """First Name is 'William'."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["first_name"] == "William"


def test_parse_william_looney_last_name():
    """Last Name is 'Looney'."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["last_name"] == "Looney"


def test_parse_william_looney_middle_name():
    """Middle Name is 'G' (single initial)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["middle_name"] == "G"


def test_parse_william_looney_aka():
    """AKA is 'Guy' (the nickname)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["aka"] == "Guy"


def test_parse_william_looney_enlisted_date():
    """Enlisted date is 1862-03-08."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["enlisted"] == "1862-03-08"


def test_parse_william_looney_rank():
    """Rank is 'Pvt'."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["rank"] == "Pvt"


def test_parse_william_looney_unit():
    """Unit is '34 TX' (ordinal + state)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["unit"] == "34 TX"


def test_parse_william_looney_company():
    """Company is 'H'."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["company"] == "H"


def test_parse_william_looney_born():
    """Born is '1840-05-24' (ISO format from CGR)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["born"] == "1840-05-24"


def test_parse_william_looney_birth_state():
    """Birth state is 'MN' (the state they were born in)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["birth_state"] == "MN"


def test_parse_william_looney_died():
    """Died date is '1932-02-28'."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["died"] == "1932-02-28"


def test_parse_william_looney_died_state_is_ok():
    """The KEY field — died state is 'OK' (burial state for our project)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["died_state"] == "OK"


def test_parse_william_looney_spouse():
    """Spouse is 'Martha Ann (Williams)' (with maiden name in parens)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert "Martha Ann" in parse_cgr_vet(html)["spouse"]


def test_parse_william_looney_source():
    """Source is 'Okla. SCV Archives' (shows OK provenance)."""
    html = (FIXTURE_DIR / "vetDetails_88159.html").read_text(encoding="iso-8859-1")
    assert parse_cgr_vet(html)["source"] == "Okla. SCV Archives"


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