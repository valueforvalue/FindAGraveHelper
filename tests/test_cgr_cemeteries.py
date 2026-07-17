"""Tests for CGR cemetery-list parser.

The ajax_cemeteryDrop.php endpoint returns a list of cemeteries
in a state. The HTML looks like:

    cemeteryDiv|<select name="cemetery_id">
    <option value=></option>
    <option value="13211">Adair Co.: Baptist Mission Cemetery</option>
    <option value="14481">Adair Co.: Chalk Bluff Cemetery</option>
    ...
    </select>

Each option's value is the cemetery id; the text is "County: Name".
We parse to list of {id, name, county, raw_label}.

Note: same cemetery name can have multiple ids (different
locations or duplicate entries). We keep all of them.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr.cgr_cemeteries import parse_cemeteries_html


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


def test_parse_ok_cemetery_list_returns_list():
    """OK cemetery fixture returns a list (not None/dict)."""
    html = (FIXTURE_DIR / "cemeteries_ok.html").read_text(encoding="iso-8859-1")
    cemeteries = parse_cemeteries_html(html)
    assert isinstance(cemeteries, list)


def test_parse_ok_cemetery_list_has_many():
    """OK cemetery fixture has 700+ entries (we counted 769 unique options)."""
    html = (FIXTURE_DIR / "cemeteries_ok.html").read_text(encoding="iso-8859-1")
    cemeteries = parse_cemeteries_html(html)
    # 769 non-empty options, after dropping the empty placeholder
    assert len(cemeteries) > 700


def test_parse_first_cemetery_has_id_and_county():
    """First cemetery in OK list: Adair Co., Baptist Mission Cemetery."""
    html = (FIXTURE_DIR / "cemeteries_ok.html").read_text(encoding="iso-8859-1")
    cemeteries = parse_cemeteries_html(html)
    # The very first non-empty option
    first = cemeteries[0]
    assert first["id"] == 13211
    assert "Adair" in first["county"]


def test_parse_cemetery_name_extracted():
    """Cemetery name extracted separately from county."""
    html = (FIXTURE_DIR / "cemeteries_ok.html").read_text(encoding="iso-8859-1")
    cemeteries = parse_cemeteries_html(html)
    first = cemeteries[0]
    assert "Baptist Mission" in first["name"]


def test_parse_preserves_raw_label():
    """Raw label is preserved for diagnostics."""
    html = (FIXTURE_DIR / "cemeteries_ok.html").read_text(encoding="iso-8859-1")
    cemeteries = parse_cemeteries_html(html)
    first = cemeteries[0]
    assert "raw_label" in first
    assert "Adair Co." in first["raw_label"]


def test_parse_skips_empty_options():
    """Empty value options (placeholder) are skipped."""
    html = (FIXTURE_DIR / "cemeteries_ok.html").read_text(encoding="iso-8859-1")
    cemeteries = parse_cemeteries_html(html)
    for c in cemeteries:
        assert c["id"] != "" and c["id"] is not None


def test_parse_handles_no_county_format():
    """Some entries have no 'Co.:' separator (just a name)."""
    synthetic = """
    cemeteryDiv|<select name="cemetery_id">
    <option value=></option>
    <option value="13170">Name Unknown Cemetery</option>
    </select>
    """
    cemeteries = parse_cemeteries_html(synthetic)
    assert len(cemeteries) == 1
    assert cemeteries[0]["name"] == "Name Unknown Cemetery"
    assert cemeteries[0]["county"] == ""


def test_parse_handles_aka_in_name():
    """Names with 'AKA:' keep the AKA in the name (conservative: don't strip).

    We deliberately do NOT strip the AKA — that's a human decision
    about whether two records are the same cemetery. The parser
    just records what the page says."""
    synthetic = """
    cemeteryDiv|<select name="cemetery_id">
    <option value=></option>
    <option value="12345">Tulsa Co.: Clinton Oaks Cemetery (AKA: Red Fork Cemetery)</option>
    </select>
    """
    cemeteries = parse_cemeteries_html(synthetic)
    # Whole label kept verbatim — including AKA
    assert "Clinton Oaks Cemetery" in cemeteries[0]["name"]
    assert "AKA" in cemeteries[0]["raw_label"]
    assert "Red Fork" in cemeteries[0]["raw_label"]


def test_parse_handles_duplicate_names():
    """Same cemetery name with different ids should both be preserved."""
    synthetic = """
    cemeteryDiv|<select name="cemetery_id">
    <option value=></option>
    <option value="14845">Adair Co.: Piney Cemetery</option>
    <option value="17918">Adair Co.: Piney Cemetery</option>
    </select>
    """
    cemeteries = parse_cemeteries_html(synthetic)
    assert len(cemeteries) == 2
    assert cemeteries[0]["name"] == cemeteries[1]["name"] == "Piney Cemetery"
    assert cemeteries[0]["id"] != cemeteries[1]["id"]


def test_parse_handles_empty_html():
    """Empty HTML returns empty list, no crash."""
    assert parse_cemeteries_html("") == []


def test_parse_handles_malformed_option():
    """Option with no value attribute is skipped."""
    synthetic = """
    cemeteryDiv|<select name="cemetery_id">
    <option>broken</option>
    <option value="123">Tulsa Co.: Test Cemetery</option>
    </select>
    """
    cemeteries = parse_cemeteries_html(synthetic)
    assert len(cemeteries) == 1
    assert cemeteries[0]["id"] == 123


def test_parse_unicode_in_county_name():
    """Unicode (accented) characters in county names work."""
    synthetic = """
    cemeteryDiv|<select name="cemetery_id">
    <option value=></option>
    <option value="99">Adair Co.: Cité Cemetery</option>
    </select>
    """
    cemeteries = parse_cemeteries_html(synthetic)
    assert cemeteries[0]["name"] == "Cité Cemetery"


def test_parse_id_is_integer():
    """Cemetery ids are integers, not strings (for clean JSON output)."""
    html = (FIXTURE_DIR / "cemeteries_ok.html").read_text(encoding="iso-8859-1")
    cemeteries = parse_cemeteries_html(html)
    for c in cemeteries[:10]:
        assert isinstance(c["id"], int), f"expected int, got {type(c['id'])}"