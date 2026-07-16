"""Tests for the bulk OK-cemetery browsing methods on CGRClient.

The CGR site lets us:
  1. List all cemeteries in a state (POST state=OK to
     ajax_cemeteryDrop.php)
  2. List all veterans in a cemetery (GET results.php?cemetery_id=X)

These methods let us scrape all OK CW veterans without
needing a name list to start from.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr_client import CGRClient


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "cgr"


def _bytes_response(path: Path) -> MagicMock:
    """Return a mock urlopen response with the fixture HTML as bytes."""
    resp = MagicMock()
    resp.read.return_value = path.read_bytes()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_list_cemeteries_in_state_posts_to_ajax():
    """list_cemeteries_in_state() POSTs state=X to ajax_cemeteryDrop.php."""
    fixture = FIXTURE_DIR / "cemeteries_ok.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        cems = client.list_cemeteries_in_state("OK")
    # Verify it was a POST
    req = mock_urlopen.call_args[0][0]
    assert req.method == "POST"
    # Verify the URL
    assert "ajax_cemeteryDrop.php" in req.full_url


def test_list_cemeteries_in_state_returns_parsed_list():
    """Returns list of dicts, not raw HTML."""
    fixture = FIXTURE_DIR / "cemeteries_ok.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        cems = client.list_cemeteries_in_state("OK")
    assert isinstance(cems, list)
    assert isinstance(cems[0], dict)
    assert "id" in cems[0]
    assert "name" in cems[0]


def test_list_cemeteries_in_state_sends_correct_post_data():
    """The POST body is 'state=OK' (or whatever state code)."""
    fixture = FIXTURE_DIR / "cemeteries_ok.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        client.list_cemeteries_in_state("TX")
    req = mock_urlopen.call_args[0][0]
    # data attribute is the encoded POST body
    assert req.data == b"state=TX"


def test_list_veterans_in_cemetery_calls_results_with_cemetery_id():
    """list_veterans_in_cemetery() GETs results.php?cemetery_id=X."""
    fixture = FIXTURE_DIR / "results_william_looney.html"  # any results page works
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        vets = client.list_veterans_in_cemetery(12754)
    req = mock_urlopen.call_args[0][0]
    assert "results.php" in req.full_url
    assert "cemetery_id=12754" in req.full_url


def test_list_veterans_in_cemetery_returns_parsed_list():
    """Returns list of {id, name, unit, born} dicts."""
    fixture = FIXTURE_DIR / "results_william_looney.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        vets = client.list_veterans_in_cemetery(12754)
    assert isinstance(vets, list)
    assert "id" in vets[0]
    assert "name" in vets[0]
    assert "unit" in vets[0]


def test_bulk_methods_throttle():
    """Bulk methods also throttle between requests."""
    fixture = FIXTURE_DIR / "cemeteries_ok.html"
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("scripts.cgr_client.time.sleep") as mock_sleep:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=2.0)
        # First request: no throttle
        client.list_cemeteries_in_state("OK")
        # Second request: should sleep
        client.list_cemeteries_in_state("TX")
        # Third request: should also sleep
        client.list_veterans_in_cemetery(12754)
        # Expect 2 sleeps (between requests), no sleep before first
        assert mock_sleep.call_count == 2


def test_bulk_method_does_not_throttle_when_zero():
    """No throttling when set to zero."""
    fixture = FIXTURE_DIR / "cemeteries_ok.html"
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("scripts.cgr_client.time.sleep") as mock_sleep:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        for _ in range(3):
            client.list_cemeteries_in_state("OK")
        assert mock_sleep.call_count == 0


def test_client_passes_user_agent_on_bulk_methods():
    """Bulk methods also send User-Agent header."""
    fixture = FIXTURE_DIR / "cemeteries_ok.html"
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _bytes_response(fixture)
        client = CGRClient(throttle_seconds=0)
        client.list_cemeteries_in_state("OK")
        req = mock_urlopen.call_args[0][0]
        # urllib normalizes header names to lowercase
        assert any(k.lower() == "user-agent" for k in req.headers.keys())
        # And our UA string is present
        ua = next(v for k, v in req.headers.items() if k.lower() == "user-agent")
        assert "FindAGraveHelper" in ua