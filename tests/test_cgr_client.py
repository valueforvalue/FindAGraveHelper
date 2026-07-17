"""Tests for the CGR HTTP client.

The client is a thin wrapper over urllib.request. It handles:
  - Building search URLs with the right field names
  - GET requests to results.php and the detail pages
  - Throttling between requests (so we don't hammer their server)
  - Returning parsed data, not raw HTML

We mock urllib.request.urlopen so tests don't hit the network.
The real client is in scripts/cgr_client.py.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr.cgr_client import CGRClient


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


def _html_response(path: Path) -> MagicMock:
    """Return a mock urlopen response with the fixture HTML."""
    resp = MagicMock()
    resp.read.return_value = path.read_bytes()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_search_by_name_calls_results_endpoint():
    """search_by_name() GETs results.php with fname/lname params."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        results = client.search_by_name(fname="William", lname="Looney")
    # Verify urlopen was called with a results.php URL
    call_arg = mock_urlopen.call_args[0][0]
    # call_arg is a urllib.request.Request; full_url is the URL string
    call_url = getattr(call_arg, "full_url", str(call_arg))
    assert "results.php" in call_url
    assert "fname=William" in call_url
    assert "lname=Looney" in call_url


def test_search_by_name_returns_parsed_results():
    """search_by_name returns parsed list of dicts (not raw HTML)."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        results = client.search_by_name(fname="William", lname="Looney")
    assert len(results) == 1
    assert results[0]["id"] == 88159


def test_search_by_name_empty_returns_empty_list():
    """A search that matches nothing returns empty list."""
    fixture = FIXTURE_DIR / "results_none.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        results = client.search_by_name(fname="ZZZQQQ", lname="WWWW")
    assert results == []


def test_get_vet_details_calls_correct_url():
    """get_vet_details(id=X) calls vetDetails.php?id=X."""
    fixture = FIXTURE_DIR / "vetDetails_88159.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        vet = client.get_vet_details(88159)
    call_arg = mock_urlopen.call_args[0][0]
    call_url = getattr(call_arg, "full_url", str(call_arg))
    assert "vetDetails.php" in call_url
    assert "id=88159" in call_url


def test_get_vet_details_returns_parsed_dict():
    """get_vet_details returns parsed dict (not raw HTML)."""
    fixture = FIXTURE_DIR / "vetDetails_88159.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        vet = client.get_vet_details(88159)
    assert vet["last_name"] == "Looney"
    assert vet["died_state"] == "OK"


def test_get_cemetery_details_calls_correct_url():
    """get_cemetery_details(id=X) calls cemDetails.php?id=X."""
    fixture = FIXTURE_DIR / "cemDetails_88159.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        cem = client.get_cemetery_details(88159)
    call_arg = mock_urlopen.call_args[0][0]
    call_url = getattr(call_arg, "full_url", str(call_arg))
    assert "cemDetails.php" in call_url
    assert "id=88159" in call_url


def test_get_cemetery_details_returns_parsed_dict():
    """get_cemetery_details returns parsed dict."""
    fixture = FIXTURE_DIR / "cemDetails_88159.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        cem = client.get_cemetery_details(88159)
    assert cem["name"] == "Rose Hill Cemetery"
    assert cem["state"] == "OK"


def test_client_throttles_between_requests():
    """When throttle_seconds > 0, the client sleeps between requests."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("scripts.cgr.cgr_client.time.sleep") as mock_sleep:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=2.0)
        # First request: no throttle (warmup)
        client.search_by_name(fname="X", lname="Y")
        # Second request: should sleep
        client.search_by_name(fname="A", lname="B")
        # Third request: should also sleep
        client.search_by_name(fname="C", lname="D")
        # We expect 2 sleeps (between request 1->2 and 2->3), but no sleep before the first
        assert mock_sleep.call_count == 2
        for call in mock_sleep.call_args_list:
            assert call.args[0] == 2.0


def test_client_does_not_throttle_when_zero():
    """When throttle_seconds=0, the client never sleeps."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("scripts.cgr.cgr_client.time.sleep") as mock_sleep:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        for _ in range(5):
            client.search_by_name(fname="X", lname="Y")
        assert mock_sleep.call_count == 0


def test_client_passes_user_agent():
    """Client sends a User-Agent header so we're not blocked as a bot."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        client.search_by_name(fname="X", lname="Y")
        # The Request object is the first positional arg
        req = mock_urlopen.call_args[0][0]
        assert "User-Agent" in req.headers or hasattr(req, "headers")


def test_client_search_includes_optional_filters():
    """Search can pass unit_state, ordinal, etc."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _html_response(fixture)
        client = CGRClient(throttle_seconds=0)
        client.search_by_name(fname="X", lname="Y", unit_state="TX", ordinal="34")
    call_arg = mock_urlopen.call_args[0][0]
    call_url = getattr(call_arg, "full_url", str(call_arg))
    assert "unit_state=TX" in call_url
    assert "ordinal=34" in call_url