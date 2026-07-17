"""Tests for pagination support in CGR cemetery browsing.

CGR's results.php returns at most 30 vets per page. For larger
cemeteries (e.g. 38 vets), the page includes a "Next" link with
an offset parameter. We need to:

  1. Detect when there are more pages (parse "X records returned"
     and "(A-B of N Records)" lines)
  2. Fetch subsequent pages with offset=N
  3. Aggregate into one list per cemetery

The simplest interface: a new method `list_all_veterans_in_cemetery`
that handles pagination internally and returns ALL vets.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr.cgr_client import CGRClient


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


def _bytes_response(path: Path) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = path.read_bytes()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _make_vet_row(vid):
    return (
        f'<tr><th><input type=radio value=V_{vid}></th>'
        f'<td>{vid}</td><td>Vet {vid}</td><td>5 AL</td><td>1840</td></tr>'
    )


def _make_page(vid_range, total):
    """Build a synthetic results page with given vet ids."""
    return (
        f'<html><body>'
        f'<td class=errortext>{total} records returned</td>'
        f'<tr><th>({vid_range[0]}-{vid_range[-1]} of {total} Records)</th></tr>'
        + ''.join(_make_vet_row(v) for v in vid_range)
        + '</body></html>'
    ).encode()


def _make_response(html_bytes):
    resp = MagicMock()
    resp.read.return_value = html_bytes
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_cgr_results_exposes_total_count():
    """parse_cgr_results can extract the total count from the page."""
    from scripts.cgr.cgr_results import extract_record_count
    html = """
    <html><body>
    <td class=errortext>38 records returned</td>
    <tr><th>(1-30 of 38 Records)</th></tr>
    </body></html>
    """
    assert extract_record_count(html) == 38


def test_cgr_results_exposes_total_count_for_small_results():
    """extract_record_count also works for small results."""
    from scripts.cgr.cgr_results import extract_record_count
    html = """
    <td class=errortext>3 records returned</td>
    <tr><th>(1-3 of 3 Records)</th></tr>
    """
    assert extract_record_count(html) == 3


def test_cgr_results_exposes_total_count_from_of_n_pattern():
    """The 'of N Records' pattern is parsed as fallback."""
    from scripts.cgr.cgr_results import extract_record_count
    html = """
    <tr><th>(1-30 of 47 Records)</th></tr>
    """
    assert extract_record_count(html) == 47


def test_list_all_veterans_in_cemetery_handles_pagination():
    """list_all_veterans_in_cemetery fetches all pages and aggregates."""
    page1 = _make_page(list(range(1, 31)), 38)
    page2 = _make_page(list(range(31, 39)), 38)
    responses = [_make_response(page1), _make_response(page2)]

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = responses
        client = CGRClient(throttle_seconds=0)
        vets = client.list_all_veterans_in_cemetery(12736)
    assert len(vets) == 38


def test_list_all_veterans_handles_single_page():
    """When total <= 30, only one request is made."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        vets = client.list_all_veterans_in_cemetery(12754)
    assert mock_urlopen.call_count == 1
    assert len(vets) == 1


def test_list_all_veterans_stops_at_last_page():
    """Pagination stops when current page count + offset >= total."""
    page1 = _make_page([1, 2, 3], 3)
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _make_response(page1)
        client = CGRClient(throttle_seconds=0)
        vets = client.list_all_veterans_in_cemetery(12345)
    assert mock_urlopen.call_count == 1
    assert len(vets) == 3


def test_list_all_veterans_uses_offset_parameter():
    """The second page request includes offset=30 (or whatever)."""
    page1 = _make_page(list(range(1, 31)), 38)
    page2 = _make_page(list(range(31, 39)), 38)
    responses = [_make_response(page1), _make_response(page2)]

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = responses
        client = CGRClient(throttle_seconds=0)
        client.list_all_veterans_in_cemetery(12736)
    second_call_url = mock_urlopen.call_args_list[1][0][0].full_url
    assert "offset=30" in second_call_url


def test_list_all_veterans_handles_no_total_count_gracefully():
    """If total count can't be parsed, fall back to one-page behavior."""
    # Page with vets but no count header
    page = (
        '<html><body>'
        + _make_vet_row(1) + _make_vet_row(2)
        + '</body></html>'
    ).encode()
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _make_response(page)
        client = CGRClient(throttle_seconds=0)
        vets = client.list_all_veterans_in_cemetery(12345)
    assert mock_urlopen.call_count == 1
    assert len(vets) == 2


def test_list_all_veterans_safety_limit():
    """Safety: stop at MAX_PAGES even if pagination seems endless."""
    # 30 records per page, total=99999 — should bail at max_pages
    page = _make_page(list(range(1, 31)), 99999)
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _make_response(page)
        client = CGRClient(throttle_seconds=0)
        vets = client.list_all_veterans_in_cemetery(12345)
    # max_pages defaults to 200, so 200 calls is the upper bound
    assert mock_urlopen.call_count <= 200


def test_list_all_veterans_throttles_between_pages():
    """Throttling applies between page fetches too."""
    page1 = _make_page(list(range(1, 31)), 38)
    page2 = _make_page(list(range(31, 39)), 38)
    responses = [_make_response(page1), _make_response(page2)]

    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("scripts.cgr.cgr_client.time.sleep") as mock_sleep:
        mock_urlopen.side_effect = responses
        client = CGRClient(throttle_seconds=2.0)
        client.list_all_veterans_in_cemetery(12736)
    assert mock_sleep.call_count == 1
    assert mock_sleep.call_args.args[0] == 2.0


def test_list_all_veterans_returns_list_of_dicts():
    """Final result is a list of {id, name, unit, born} dicts."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        vets = client.list_all_veterans_in_cemetery(12754)
    assert isinstance(vets, list)
    assert all(isinstance(v, dict) for v in vets)
    assert "id" in vets[0]
    assert "name" in vets[0]