"""Tests for J1: state file integrity check.

Before/after each run, we want to verify:
  - All expected pensioner IDs are present (no missing)
  - No duplicate IDs
  - Each record has the expected fields
  - FaG backlinks are well-formed

This is the foundation of "bulletproof" — we can detect
data loss, corruption, or schema drift.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.state.state_check import (
    check_state_file,
    StateCheckResult,
    expected_pensioner_ids,
    record_issues,
)


# ============================================================
# expected_pensioner_ids
# ============================================================
def test_expected_ids_picks_up_field():
    """Pensioner dict has an id field."""
    pensioners = [
        {"id": 1, "first_name": "A"},
        {"id": 2, "first_name": "B"},
    ]
    ids = expected_pensioner_ids(pensioners)
    assert ids == {1, 2}


def test_expected_ids_handles_missing_id():
    """Records without 'id' are skipped (defensive)."""
    pensioners = [
        {"id": 1, "first_name": "A"},
        {"first_name": "no_id"},
        {"id": 2, "first_name": "B"},
    ]
    ids = expected_pensioner_ids(pensioners)
    assert ids == {1, 2}


# ============================================================
# record_issues — per-record
# ============================================================
def test_record_issues_no_problems():
    """Healthy record produces no issues."""
    rec = {
        "pensioner_id": 5,
        "cgr_records": [{"match_strength": "strong", "cgr_id": 99}],
        "fag_records": [{"memorial_id": "12345",
                         "backlink": "https://www.findagrave.com/memorial/12345"}],
    }
    issues = record_issues(rec)
    assert issues == []


def test_record_issues_no_pensioner_id():
    """Missing pensioner_id is an issue."""
    rec = {"cgr_records": [], "fag_records": []}
    issues = record_issues(rec)
    assert any("pensioner_id" in i for i in issues)


def test_record_issues_no_fields_at_all():
    """Empty record → only the missing-pensioner_id issue."""
    rec = {}
    issues = record_issues(rec)
    assert any("pensioner_id" in i for i in issues)


def test_record_issues_invalid_fag_backlink():
    """FaG candidate with malformed backlink is flagged."""
    rec = {
        "pensioner_id": 1,
        "fag_records": [
            {"memorial_id": "12345", "backlink": "not_a_url"},
        ],
    }
    issues = record_issues(rec)
    assert any("backlink" in i for i in issues)


def test_record_issues_valid_fag_backlink():
    """FaG candidate with https://findagrave.com URL is fine."""
    rec = {
        "pensioner_id": 1,
        "fag_records": [
            {"memorial_id": "12345", "backlink": "https://www.findagrave.com/memorial/12345"},
        ],
    }
    issues = record_issues(rec)
    assert not any("backlink" in i for i in issues)


def test_record_issues_invalid_cgr_id():
    """CGR record with non-int id is flagged."""
    rec = {
        "pensioner_id": 1,
        "cgr_records": [{"cgr_id": "not_an_int"}],
    }
    issues = record_issues(rec)
    assert any("cgr_id" in i for i in issues)


# ============================================================
# check_state_file — full file scan
# ============================================================
def _write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_check_state_file_clean(tmp_path):
    """All 5 expected pensioners, no issues."""
    state_path = tmp_path / "state.jsonl"
    records = [
        {"pensioner_id": i, "cgr_records": [], "fag_records": []} for i in [1, 2, 3, 4, 5]
    ]
    _write_jsonl(state_path, records)
    expected_ids = {1, 2, 3, 4, 5}
    result = check_state_file(state_path, expected_ids)
    assert result.missing_ids == set()
    assert result.duplicate_ids == set()
    assert result.issues == []


def test_check_state_file_missing(tmp_path):
    """Pensioner 3 missing from state."""
    state_path = tmp_path / "state.jsonl"
    records = [{"pensioner_id": i, "cgr_records": [], "fag_records": []} for i in [1, 2, 4, 5]]
    _write_jsonl(state_path, records)
    expected_ids = {1, 2, 3, 4, 5}
    result = check_state_file(state_path, expected_ids)
    assert 3 in result.missing_ids


def test_check_state_file_duplicates(tmp_path):
    """Pensioner 2 appears twice."""
    state_path = tmp_path / "state.jsonl"
    records = [
        {"pensioner_id": 1, "cgr_records": [], "fag_records": []},
        {"pensioner_id": 2, "cgr_records": [], "fag_records": []},
        {"pensioner_id": 2, "cgr_records": [], "fag_records": []},
    ]
    _write_jsonl(state_path, records)
    expected_ids = {1, 2}
    result = check_state_file(state_path, expected_ids)
    assert 2 in result.duplicate_ids


def test_check_state_file_per_record_issues(tmp_path):
    """Reports records with schema problems."""
    state_path = tmp_path / "state.jsonl"
    records = [
        {"pensioner_id": 1, "cgr_records": [], "fag_records": []},
        {"cgr_records": [], "fag_records": []},  # no pensioner_id
    ]
    _write_jsonl(state_path, records)
    expected_ids = {1}
    result = check_state_file(state_path, expected_ids)
    assert result.issues != []


def test_state_check_result_to_dict():
    """Result serializes for the report."""
    r = StateCheckResult(
        total_records=100,
        missing_ids={5, 10},
        duplicate_ids={3},
        issues=[],
    )
    d = r.to_dict()
    assert d["total_records"] == 100
    assert "5" in str(d["missing_ids"]) or 5 in d["missing_ids"]


def test_state_check_result_is_clean():
    """is_clean() reflects 'no problems'."""
    r = StateCheckResult(total_records=10)
    assert r.is_clean()
    r.missing_ids = {5}
    assert not r.is_clean()