"""Tests for the CGR cross-reference script logic.

The cross-ref script:
  1. Loads ok_pensioners.json (or similar input)
  2. For each pensioner, searches CGR by (first_name, last_name)
  3. For each CGR match, fetches vet details (and optionally cemetery)
  4. Annotates with match_strength + conflicts
  5. Writes a JSONL state file with one record per pensioner

Tests focus on the orchestrator logic with mocked CGR client.
We never hit the network in unit tests.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cgr_xref import xref_one_pensioner, XrefConfig


def _mock_cgr_client():
    """Build a mock CGRClient with canned responses."""
    client = MagicMock()
    client.search_by_name.return_value = [
        {"id": 88159, "name": "William G (Guy) Looney", "unit": "34 TX", "born": "May 24 1840"},
    ]
    client.get_vet_details.return_value = {
        "first_name": "William", "middle_name": "G", "last_name": "Looney",
        "aka": "Guy", "enlisted": "1862-03-08", "rank": "Pvt",
        "unit": "34 TX", "company": "H", "born": "1840-05-24",
        "birth_state": "MN", "died": "1932-02-28", "died_state": "OK",
        "spouse": "Martha Ann (Williams)", "source": "Okla. SCV Archives",
    }
    client.get_cemetery_details.return_value = {
        "name": "Rose Hill Cemetery", "city": "Chickasha", "county": "Grady",
        "state": "OK", "latitude": "35.0314", "longitude": "-97.9453",
    }
    return client


def test_xref_one_pensioner_returns_state_record():
    """xref_one_pensioner returns a state record (one JSON-serializable dict)."""
    client = _mock_cgr_client()
    pensioner = {
        "id": 7666, "first_name": "William", "last_name": "Looney",
        "middle_name": "G", "regiment": "34 TX",
    }
    record = xref_one_pensioner(client, pensioner)
    assert isinstance(record, dict)


def test_xref_calls_search_by_name():
    """xref calls client.search_by_name with the pensioner's name."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    xref_one_pensioner(client, pensioner)
    client.search_by_name.assert_called_once()
    call_kwargs = client.search_by_name.call_args.kwargs
    assert call_kwargs.get("fname") == "William"
    assert call_kwargs.get("lname") == "Looney"


def test_xref_calls_get_vet_details_for_each_cgr_match():
    """For each CGR match, xref calls get_vet_details."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    xref_one_pensioner(client, pensioner)
    client.get_vet_details.assert_called_once_with(88159)


def test_xref_includes_cgr_records_with_details():
    """State record includes a 'cgr_records' field with each match's full details."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    record = xref_one_pensioner(client, pensioner)
    assert "cgr_records" in record
    assert len(record["cgr_records"]) == 1


def test_xref_includes_match_strength_per_cgr_record():
    """Each CGR record in the state has a match_strength annotation."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    record = xref_one_pensioner(client, pensioner)
    assert record["cgr_records"][0]["match_strength"] in ("strong", "medium", "weak", "none")


def test_xref_includes_vet_details_per_cgr_record():
    """Each CGR record includes the full vet details (died_state, etc.)."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    record = xref_one_pensioner(client, pensioner)
    vet_details = record["cgr_records"][0].get("vet_details", {})
    assert vet_details.get("died_state") == "OK"


def test_xref_includes_cemetery_details_per_cgr_record():
    """Each CGR record includes cemetery details (when requested)."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    config = XrefConfig(include_cemetery=True)
    record = xref_one_pensioner(client, pensioner, config)
    cem = record["cgr_records"][0].get("cemetery_details", {})
    assert cem.get("name") == "Rose Hill Cemetery"


def test_xref_skips_cemetery_when_disabled():
    """Cemetery fetch is skipped when config.include_cemetery=False."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    config = XrefConfig(include_cemetery=False)
    record = xref_one_pensioner(client, pensioner, config)
    client.get_cemetery_details.assert_not_called()
    # cemetery_details is None when disabled
    assert record["cgr_records"][0].get("cemetery_details") is None


def test_xref_handles_no_cgr_results():
    """When CGR returns no matches, record has empty cgr_records."""
    client = _mock_cgr_client()
    client.search_by_name.return_value = []
    pensioner = {"id": 1, "first_name": "John", "last_name": "Nobody"}
    record = xref_one_pensioner(client, pensioner)
    assert record["cgr_records"] == []
    # Should still not have called vet details
    client.get_vet_details.assert_not_called()


def test_xref_handles_multiple_cgr_matches():
    """When CGR returns multiple matches, all are included."""
    client = _mock_cgr_client()
    client.search_by_name.return_value = [
        {"id": 1, "name": "William Looney", "unit": "34 TX", "born": "1840"},
        {"id": 2, "name": "W. Looney", "unit": "5 AL", "born": "1842"},
    ]
    client.get_vet_details.side_effect = [
        {"first_name": "William", "last_name": "Looney", "died_state": "OK"},
        {"first_name": "W.", "last_name": "Looney", "died_state": "TX"},
    ]
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    record = xref_one_pensioner(client, pensioner)
    assert len(record["cgr_records"]) == 2


def test_xref_includes_pensioner_id_in_record():
    """The state record has the pensioner_id for tracking."""
    client = _mock_cgr_client()
    pensioner = {"id": 7666, "first_name": "William", "last_name": "Looney"}
    record = xref_one_pensioner(client, pensioner)
    assert record["pensioner_id"] == 7666


def test_xref_state_record_is_json_serializable():
    """The state record can be written to JSONL (no datetime/objects)."""
    import json
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    record = xref_one_pensioner(client, pensioner)
    # Should round-trip without TypeError
    line = json.dumps(record)
    parsed = json.loads(line)
    assert parsed["pensioner_id"] == 1


def test_xref_status_field_reflects_outcome():
    """Record has a 'status' field indicating cgr_found / no_match / error."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    record = xref_one_pensioner(client, pensioner)
    assert "status" in record
    assert record["status"] in ("cgr_found", "no_match", "error")


def test_xref_status_no_match_when_empty():
    """When CGR has no matches, status is 'no_match'."""
    client = _mock_cgr_client()
    client.search_by_name.return_value = []
    pensioner = {"id": 1, "first_name": "John", "last_name": "Nobody"}
    record = xref_one_pensioner(client, pensioner)
    assert record["status"] == "no_match"


def test_xref_status_cgr_found_when_matches():
    """When CGR has matches, status is 'cgr_found'."""
    client = _mock_cgr_client()
    pensioner = {"id": 1, "first_name": "William", "last_name": "Looney"}
    record = xref_one_pensioner(client, pensioner)
    assert record["status"] == "cgr_found"


def test_xref_handles_pensioner_missing_fields():
    """A pensioner with missing fields doesn't crash xref."""
    client = _mock_cgr_client()
    pensioner = {"id": 99}  # no name fields
    record = xref_one_pensioner(client, pensioner)
    assert isinstance(record, dict)
    # Empty first/last should be passed as empty strings
    call_kwargs = client.search_by_name.call_args.kwargs
    assert call_kwargs.get("fname") == ""
    assert call_kwargs.get("lname") == ""


def test_xref_handles_exception_from_client():
    """If the client raises, xref records the error and continues."""
    client = MagicMock()
    client.search_by_name.side_effect = RuntimeError("network error")
    pensioner = {"id": 1, "first_name": "X", "last_name": "Y"}
    record = xref_one_pensioner(client, pensioner)
    assert record["status"] == "error"
    assert "network error" in record.get("error", "")


def test_xref_default_config_has_cemetery_enabled():
    """Default config fetches cemetery details (useful info)."""
    client = _mock_cgr_client()
    config = XrefConfig()
    assert config.include_cemetery is True