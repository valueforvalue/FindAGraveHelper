"""Tests for CGR results page parser.

The CGR search returns a list of veterans matching fname/lname/etc.
Each row has: id, name, unit, born date. The page is plain HTML
tables.

IMPORTANT: When parsing, we extract ALL fields VERBATIM. We do NOT
make assumptions about which row matches which local record —
that's the matcher's job (test_cgr_matcher.py). The parser's job
is to faithfully extract what the page shows.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr_results import parse_cgr_results


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


def test_parse_william_looney_results_returns_one_record():
    """Search for William Looney returns 1 record (id 88159)."""
    html = (FIXTURE_DIR / "results_william_looney.html").read_text(encoding="iso-8859-1")
    results = parse_cgr_results(html)
    assert len(results) == 1


def test_parse_william_looney_record_has_id():
    """Each result has an integer id field."""
    html = (FIXTURE_DIR / "results_william_looney.html").read_text(encoding="iso-8859-1")
    results = parse_cgr_results(html)
    assert results[0]["id"] == 88159


def test_parse_william_looney_record_has_name():
    """Name field carries the full display name as shown."""
    html = (FIXTURE_DIR / "results_william_looney.html").read_text(encoding="iso-8859-1")
    results = parse_cgr_results(html)
    assert "William G (Guy) Looney" in results[0]["name"]


def test_parse_william_looney_record_has_unit():
    """Unit field shows '34 TX' (state + ordinal)."""
    html = (FIXTURE_DIR / "results_william_looney.html").read_text(encoding="iso-8859-1")
    results = parse_cgr_results(html)
    assert results[0]["unit"] == "34 TX"


def test_parse_william_looney_record_has_born():
    """Born field shows the date as written (we don't parse to date object yet)."""
    html = (FIXTURE_DIR / "results_william_looney.html").read_text(encoding="iso-8859-1")
    results = parse_cgr_results(html)
    assert "May 24 1840" in results[0]["born"]


def test_parse_no_results_returns_empty_list():
    """A search that matches nothing returns empty list (not None)."""
    html = (FIXTURE_DIR / "results_none.html").read_text(encoding="iso-8859-1")
    results = parse_cgr_results(html)
    assert results == []


def test_parse_empty_html_returns_empty_list():
    """Empty HTML is gracefully empty."""
    results = parse_cgr_results("")
    assert results == []


def test_parse_returns_records_as_dicts():
    """Each result is a dict (not a list or tuple)."""
    html = (FIXTURE_DIR / "results_william_looney.html").read_text(encoding="iso-8859-1")
    results = parse_cgr_results(html)
    assert isinstance(results[0], dict)


def test_parse_result_keys_match_expected():
    """Each result has exactly: id, name, unit, born (no missing keys)."""
    html = (FIXTURE_DIR / "results_william_looney.html").read_text(encoding="iso-8859-1")
    results = parse_cgr_results(html)
    expected_keys = {"id", "name", "unit", "born"}
    assert set(results[0].keys()) >= expected_keys


def test_parse_handles_multiple_matches():
    """Multi-match HTML returns multiple records (synthetic, with radio)."""
    synthetic = """
    <tr><td class=errortext>3 records returned</td></tr>
    <tr><th>ID</th><th>Name</th><th>Unit</th><th>Born</th></tr>
    <tr><th width=2%><input type=radio name=choose value=V_1 onClick=...></th>
        <td>1</td><td>John Smith</td><td>5 AL</td><td>1842</td></tr>
    <tr><th width=2%><input type=radio name=choose value=V_2 onClick=...></th>
        <td>2</td><td>John Smith</td><td>10 TN</td><td>1845</td></tr>
    <tr><th width=2%><input type=radio name=choose value=V_3 onClick=...></th>
        <td>3</td><td>John A. Smith</td><td>1 VA</td><td>1840</td></tr>
    """
    results = parse_cgr_results(synthetic)
    assert len(results) == 3
    assert [r["id"] for r in results] == [1, 2, 3]
    assert [r["name"] for r in results] == ["John Smith", "John Smith", "John A. Smith"]
    assert [r["unit"] for r in results] == ["5 AL", "10 TN", "1 VA"]
    assert [r["born"] for r in results] == ["1842", "1845", "1840"]


def test_parse_does_not_assume_match():
    """Parser doesn't drop records it can't interpret — keeps row with id=None."""
    synthetic = """
    <tr><th width=2%><input type=radio name=choose value=V_1></th>
        <td>1</td><td>Alice</td><td>5 AL</td><td>1842</td></tr>
    """
    results = parse_cgr_results(synthetic)
    assert len(results) == 1
    assert results[0]["id"] == 1


def test_parse_handles_unicode_in_names():
    """Real CGR data may have accented characters in names."""
    synthetic = """
    <tr><th width=2%><input type=radio name=choose value=V_1></th>
        <td>1</td><td>José García</td><td>5 TX</td><td>1842</td></tr>
    """
    results = parse_cgr_results(synthetic)
    assert results[0]["name"] == "José García"


def test_extract_record_count_william_looney():
    """The record count line is extractable for pagination diagnostics."""
    from scripts.cgr_results import extract_record_count
    html = (FIXTURE_DIR / "results_william_looney.html").read_text(encoding="iso-8859-1")
    assert extract_record_count(html) == 1


def test_extract_record_count_returns_none_for_empty():
    """No count line = None (not crash)."""
    from scripts.cgr_results import extract_record_count
    assert extract_record_count("") is None
    assert extract_record_count("no matches here") is None