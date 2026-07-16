"""Tests for J8: post-run DD (DixieData) marker.

After the unified run, we want to know which pensioners are
already in the local DixieData database (human-verified).

For each pensioner in state.jsonl, check if local DD CSV has
a corresponding record. Mark the state record with:
  - dd_in_local: True/False
  - dd_memorial_id: the FaG memorial_id (if any) from DD
  - dd_slug: the FaG slug (if any) from DD

The view.html can use `dd_in_local` to filter to "new finds"
(records we found that aren't already in DD).

DD CSV format (dixiedata export) typically has columns:
  application_number, memorial_id, slug, first_name, last_name, ...
"""
import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.dd_marker import (
    load_dd_index,
    DdIndex,
    mark_record,
    mark_state_file,
    matched_by_app_number,
    matched_by_name,
)


# ============================================================
# DdIndex
# ============================================================
def _write_dd_csv(rows):
    """Write a DD CSV to a temp file. Return the path."""
    f = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8",
        newline="",
    )
    if rows:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    f.close()
    return Path(f.name)


def test_load_dd_index_empty():
    """Empty/missing CSV → empty index."""
    index = load_dd_index(Path("/nope/nope.csv"))
    assert isinstance(index, DdIndex)
    assert len(index.by_app_number) == 0
    assert len(index.by_name) == 0


def test_load_dd_index_by_app_number():
    """Index by application_number."""
    csv_path = _write_dd_csv([
        {"application_number": "A4", "memorial_id": "111", "slug": "x-y"},
        {"application_number": "A5", "memorial_id": "222", "slug": "a-b"},
    ])
    try:
        index = load_dd_index(csv_path)
        assert "A4" in index.by_app_number
        assert index.by_app_number["A4"]["memorial_id"] == "111"
    finally:
        csv_path.unlink(missing_ok=True)


def test_load_dd_index_by_name():
    """Index by (last_name, first_name)."""
    csv_path = _write_dd_csv([
        {"first_name": "R.W.", "last_name": "Adair", "memorial_id": "111"},
        {"first_name": "Hugh", "last_name": "Akers", "memorial_id": "222"},
    ])
    try:
        index = load_dd_index(csv_path)
        # Names normalized via _normalize_name_for_match (strip non-alpha)
        # 'R.W.' -> 'rw', 'Adair' -> 'adair'
        adair = index.by_name.get(("adair", "rw"))
        assert adair is not None
        assert adair["memorial_id"] == "111"
    finally:
        csv_path.unlink(missing_ok=True)


# ============================================================
# mark_record
# ============================================================
def test_mark_record_found_by_app_number():
    """App-number match takes precedence."""
    dd_index = DdIndex(
        by_app_number={"A4": {"memorial_id": "111", "slug": "x-y"}},
        by_name={},
    )
    rec = {
        "pensioner_id": 3,
        "pensioner_app_number": "A4",
    }
    marked = mark_record(rec, dd_index)
    assert marked["dd_in_local"] is True
    assert marked["dd_memorial_id"] == "111"
    assert marked["dd_match_method"] == "app_number"


def test_mark_record_fallback_to_name():
    """If app-number doesn't match, try name."""
    dd_index = DdIndex(
        by_app_number={},
        by_name={("adair", "rw"): {"memorial_id": "111"}},
    )
    rec = {
        "pensioner_id": 3,
        "pensioner_app_number": "A99",  # not in DD
        "pensioner_first": "R.W.",
        "pensioner_last": "Adair",
    }
    marked = mark_record(rec, dd_index)
    assert marked["dd_in_local"] is True
    assert marked["dd_memorial_id"] == "111"
    assert marked["dd_match_method"] == "name"


def test_mark_record_not_in_local():
    """Pensioner not in DD = new find."""
    dd_index = DdIndex(by_app_number={}, by_name={})
    rec = {
        "pensioner_id": 99,
        "pensioner_app_number": "A99",
        "pensioner_first": "X",
        "pensioner_last": "Y",
    }
    marked = mark_record(rec, dd_index)
    assert marked["dd_in_local"] is False
    assert marked["dd_memorial_id"] is None


def test_mark_record_handles_empty_first_name():
    """Empty first name → name match skipped, no match."""
    dd_index = DdIndex(
        by_app_number={},
        by_name={},
    )
    rec = {
        "pensioner_id": 1,
        "pensioner_app_number": "A99",
        "pensioner_first": "",
        "pensioner_last": "Smith",
    }
    marked = mark_record(rec, dd_index)
    assert marked["dd_in_local"] is False


import json  # noqa


# ============================================================
# match methods
# ============================================================
def test_matched_by_app_number_present():
    """Match via app number."""
    dd_index = DdIndex(
        by_app_number={"A4": {"memorial_id": "111"}},
        by_name={},
    )
    rec = {"pensioner_app_number": "A4"}
    assert matched_by_app_number(rec, dd_index) is True


def test_matched_by_app_number_absent():
    """Match via app number when key not present."""
    dd_index = DdIndex(
        by_app_number={"A4": {"memorial_id": "111"}},
        by_name={},
    )
    rec = {"pensioner_app_number": "A99"}
    assert matched_by_app_number(rec, dd_index) is False


def test_matched_by_name_present():
    """Match via name when key present."""
    dd_index = DdIndex(
        by_app_number={},
        by_name={("smith", "john"): {"memorial_id": "111"}},
    )
    rec = {"pensioner_last": "Smith", "pensioner_first": "John"}
    assert matched_by_name(rec, dd_index) is True


def test_matched_by_name_absent():
    """Match via name when key not present."""
    dd_index = DdIndex(
        by_app_number={},
        by_name={("smith", "john"): {"memorial_id": "111"}},
    )
    rec = {"pensioner_last": "Doe", "pensioner_first": "Jane"}
    assert matched_by_name(rec, dd_index) is False


# ============================================================
# mark_state_file (batch)
# ============================================================
def test_mark_state_file(tmp_path):
    """Mark all records in a state file using a DD CSV."""
    # Set up state.jsonl
    state_path = tmp_path / "state.jsonl"
    state_path.write_text(
        "\n".join([
            '{"pensioner_id": 3, "pensioner_app_number": "A4", '
            '"pensioner_first": "R.W.", "pensioner_last": "Adair"}',
            '{"pensioner_id": 5, "pensioner_app_number": "A5", '
            '"pensioner_first": "Hugh", "pensioner_last": "Akers"}',
        ]) + "\n",
        encoding="utf-8",
    )
    # Set up DD CSV
    dd_path = tmp_path / "dd.csv"
    dd_path.write_text(
        "application_number,memorial_id,slug\n"
        "A4,111,x-y\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "marked.jsonl"
    n_marked, n_in_dd = mark_state_file(state_path, dd_path, out_path)

    assert n_marked == 2
    assert n_in_dd == 1  # only pensioner #3 (A4) matched
    # Verify output
    records = [json.loads(l) for l in out_path.open(encoding="utf-8")]
    # Pensioner 3 (A4): matched, memorial_id=111
    assert records[0]["dd_in_local"] is True
    assert records[0]["dd_memorial_id"] == "111"
    # Pensioner 5 (A5): not matched
    assert records[1]["dd_in_local"] is False


def test_mark_state_file_appends_dd_fields(tmp_path):
    """Marks are added to existing records without modifying other fields."""
    state_path = tmp_path / "state.jsonl"
    state_path.write_text(
        '{"pensioner_id": 3, "pensioner_app_number": "A4", '
        '"pensioner_first": "R.W.", "pensioner_last": "Adair", '
        '"fag_status": "auto_accept"}\n',
        encoding="utf-8",
    )
    dd_path = tmp_path / "dd.csv"
    dd_path.write_text("application_number\nA4\n", encoding="utf-8")
    out_path = tmp_path / "marked.jsonl"
    n_marked, n_in_dd = mark_state_file(state_path, dd_path, out_path)

    records = [json.loads(l) for l in out_path.open(encoding="utf-8")]
    assert records[0]["fag_status"] == "auto_accept"  # preserved
    assert records[0]["dd_in_local"] is True  # added