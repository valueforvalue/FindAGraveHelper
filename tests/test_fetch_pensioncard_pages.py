"""Tests for scripts/ingest/fetch_pensioncard_pages.py.

The script pre-fetches digitalprairie pensioncard page IDs and
stores them in a sidecar JSON file. These tests pin the contract
without hitting the network.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ingest import fetch_pensioncard_pages as fpp


# ============================================================
# extract_page_ids (pure function, easy to test)
# ============================================================
def test_extract_page_ids_compound_object():
    """Compound objects (multi-page) return all pageptr values."""
    api = {
        "objectInfo": {
            "page": [
                {"pageptr": "96", "pagefile": "233.jp2", "pagetitle": "Side 1"},
                {"pageptr": "97", "pagefile": "234.jp2", "pagetitle": "Side 2"},
            ]
        }
    }
    assert fpp.extract_page_ids(api) == [96, 97]


def test_extract_page_ids_single_page():
    """Single-page records return a single-element list."""
    api = {"objectInfo": {"page": [{"pageptr": "42", "pagefile": "x.jp2"}]}}
    assert fpp.extract_page_ids(api) == [42]


def test_extract_page_ids_handles_missing_keys():
    """Malformed/missing keys yield empty list, not exception."""
    assert fpp.extract_page_ids(None) == []
    assert fpp.extract_page_ids({}) == []
    assert fpp.extract_page_ids({"objectInfo": {}}) == []
    assert fpp.extract_page_ids({"objectInfo": {"page": []}}) == []


def test_extract_page_ids_skips_invalid_pageptrs():
    """Non-integer pageptr values are skipped silently."""
    api = {"objectInfo": {"page": [
        {"pageptr": "abc"},          # invalid
        {"pageptr": "5"},
        {"pageptr": None},            # missing
        {},                            # empty
    ]}}
    assert fpp.extract_page_ids(api) == [5]


# ============================================================
# Cache load/save
# ============================================================
def test_load_cache_returns_empty_when_missing(tmp_path):
    assert fpp.load_cache(tmp_path / "nope.json") == {}


def test_load_cache_returns_empty_on_corrupt(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text("{not json", encoding="utf-8")
    assert fpp.load_cache(p) == {}


def test_load_cache_returns_data_when_valid(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text(json.dumps({"3": [96, 97], "5": [42]}), encoding="utf-8")
    cache = fpp.load_cache(p)
    assert cache == {"3": [96, 97], "5": [42]}


def test_save_cache_atomic(tmp_path):
    """save_cache writes to .tmp first, then replaces target."""
    p = tmp_path / "cache.json"
    fpp.save_cache(p, {"3": [96]})
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8")) == {"3": [96]}
    # No leftover .tmp
    assert not (tmp_path / "cache.json.tmp").exists()


# ============================================================
# fetch_pensioncard_json (mocked)
# ============================================================
def test_fetch_pensioncard_json_returns_parsed_json():
    fake = {"objectInfo": {"page": [{"pageptr": "96"}]}, "filename": "x.cpd"}
    with patch.object(fpp.urllib.request, "urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = (
            json.dumps(fake).encode("utf-8")
        )
        result = fpp.fetch_pensioncard_json(98)
    assert result == fake


def test_fetch_pensioncard_json_returns_none_on_error():
    with patch.object(fpp.urllib.request, "urlopen",
                      side_effect=Exception("network")):
        assert fpp.fetch_pensioncard_json(98) is None


# ============================================================
# main() orchestration (with mocked network)
# ============================================================
def _make_pensioners(path: Path, n: int = 3) -> None:
    data = [
        {
            "id": i + 1,
            "pensioncard_id": 98 + i,
            "first_name": "Test",
            "last_name": f"P{i+1}",
        }
        for i in range(n)
    ]
    path.write_text(json.dumps(data), encoding="utf-8")


def test_main_fetches_and_writes_cache(tmp_path):
    """End-to-end: load pensioners, fetch each, write cache."""
    pensioners = tmp_path / "ok.json"
    cache = tmp_path / "cache.json"
    _make_pensioners(pensioners, n=3)

    # Mock the network: each pensioncard_id returns 1 page
    def fake_fetch(pcid):
        return {"objectInfo": {"page": [{"pageptr": str(pcid * 10)}]}}

    with patch.object(fpp, "fetch_pensioncard_json",
                      side_effect=fake_fetch):
        rc = fpp.main(["--input", str(pensioners),
                       "--output", str(cache),
                       "--throttle", "0"])

    assert rc == 0
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data == {"1": [980], "2": [990], "3": [1000]}


def test_main_resumes_from_cache(tmp_path):
    """Records already in the cache are skipped (unless --refresh)."""
    pensioners = tmp_path / "ok.json"
    cache = tmp_path / "cache.json"
    _make_pensioners(pensioners, n=3)

    # Pre-populate cache with one entry
    cache.write_text(json.dumps({"1": [960]}), encoding="utf-8")

    fetch_calls = []

    def fake_fetch(pcid):
        fetch_calls.append(pcid)
        return {"objectInfo": {"page": [{"pageptr": "999"}]}}

    with patch.object(fpp, "fetch_pensioncard_json",
                      side_effect=fake_fetch):
        rc = fpp.main(["--input", str(pensioners),
                       "--output", str(cache),
                       "--throttle", "0"])

    assert rc == 0
    # Only records 2 and 3 were fetched (record 1 was cached)
    assert fetch_calls == [99, 100]  # pensioncard_id 99 + 100
    data = json.loads(cache.read_text(encoding="utf-8"))
    # Record 1 preserved from pre-populated cache; 2 and 3 added
    assert data == {"1": [960], "2": [999], "3": [999]}


def test_main_refresh_flag_re_fetches(tmp_path):
    """--refresh re-fetches everything, ignoring the cache."""
    pensioners = tmp_path / "ok.json"
    cache = tmp_path / "cache.json"
    _make_pensioners(pensioners, n=2)
    cache.write_text(json.dumps({"1": [960], "2": [970]}), encoding="utf-8")

    fetch_calls = []

    def fake_fetch(pcid):
        fetch_calls.append(pcid)
        return {"objectInfo": {"page": [{"pageptr": "123"}]}}

    with patch.object(fpp, "fetch_pensioncard_json",
                      side_effect=fake_fetch):
        rc = fpp.main(["--input", str(pensioners),
                       "--output", str(cache),
                       "--refresh", "--throttle", "0"])

    assert rc == 0
    assert fetch_calls == [98, 99]  # both re-fetched
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data == {"1": [123], "2": [123]}  # cache replaced, not merged


def test_main_handles_fetch_failures(tmp_path):
    """Failed fetches don't crash the run; cache just lacks those IDs."""
    pensioners = tmp_path / "ok.json"
    cache = tmp_path / "cache.json"
    _make_pensioners(pensioners, n=2)

    def fake_fetch(pcid):
        return None  # simulate failure

    with patch.object(fpp, "fetch_pensioncard_json",
                      side_effect=fake_fetch):
        rc = fpp.main(["--input", str(pensioners),
                       "--output", str(cache),
                       "--throttle", "0"])

    assert rc == 0
    # Cache is empty (both fetches failed)
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data == {}


def test_main_skips_records_without_pensioncard_id(tmp_path):
    """Records with no pensioncard_id are silently skipped."""
    pensioners = tmp_path / "ok.json"
    cache = tmp_path / "cache.json"
    data = [
        {"id": 1, "pensioncard_id": 98},
        {"id": 2},  # no pensioncard_id
        {"id": 3, "pensioncard_id": 99},
    ]
    pensioners.write_text(json.dumps(data), encoding="utf-8")

    fetch_calls = []

    def fake_fetch(pcid):
        fetch_calls.append(pcid)
        return {"objectInfo": {"page": [{"pageptr": str(pcid)}]}}

    with patch.object(fpp, "fetch_pensioncard_json",
                      side_effect=fake_fetch):
        rc = fpp.main(["--input", str(pensioners),
                       "--output", str(cache),
                       "--throttle", "0"])

    assert rc == 0
    assert fetch_calls == [98, 99]  # record 2 skipped