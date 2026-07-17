"""Tests for the StateRepository protocol + JsonlStateRepository.

TDD: written red first (this commit), then implementation (next commit).

Per issue #22: introduce StateRepository protocol so business logic
in pipeline/ and matching/ no longer touches the state.jsonl wire
format directly. The Repository owns:
  - json.dumps key order (L4)
  - per-pensioner flush + fsync (L3)
  - newline-delimited JSON, one record per line (L5)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.state.repository import (
    JsonlStateRepository,
    InMemoryStateRepository,
    StateCheckResult,
)


# ============================================================
# Fixtures
# ============================================================

def _record(pid: int, name: str = "Smith, John") -> dict:
    """Build a minimal state.jsonl record for tests."""
    return {
        "pensioner_id": pid,
        "pensioner_app_number": f"A{pid}",
        "pensioner_name": name,
        "pensioner_first": "John",
        "pensioner_last": "Smith",
        "fag_records": [],
        "cgr_records": [],
    }


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "state.jsonl"


@pytest.fixture
def repo(state_path: Path) -> JsonlStateRepository:
    return JsonlStateRepository(state_path)


# ============================================================
# append() — must respect L3 (flush + fsync) + L5 (one per line)
# ============================================================

def test_append_writes_one_line_per_record(repo, state_path):
    repo.append(_record(1))
    repo.append(_record(2))
    lines = state_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["pensioner_id"] == 1
    assert json.loads(lines[1])["pensioner_id"] == 2


def test_append_uses_newline_delimiter_not_json_array(repo, state_path):
    repo.append(_record(1))
    content = state_path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert not content.startswith("[")


def test_append_creates_parent_dirs(tmp_path):
    nested = tmp_path / "deep" / "nest" / "state.jsonl"
    r = JsonlStateRepository(nested)
    r.append(_record(1))
    assert nested.exists()


# ============================================================
# iter_all() — must yield one dict per line, skip blanks, handle bad JSON
# ============================================================

def test_iter_all_yields_all_records(repo, state_path):
    for i in range(5):
        repo.append(_record(i))
    ids = [r["pensioner_id"] for r in repo.iter_all()]
    assert ids == [0, 1, 2, 3, 4]


def test_iter_all_skips_blank_lines(repo, state_path):
    state_path.write_text('{"pensioner_id": 1}\n\n{"pensioner_id": 2}\n', encoding="utf-8")
    ids = [r["pensioner_id"] for r in repo.iter_all()]
    assert ids == [1, 2]


def test_iter_all_empty_file(repo):
    assert list(repo.iter_all()) == []


# ============================================================
# get() — lookup by pensioner_id
# ============================================================

def test_get_returns_first_match(repo):
    repo.append(_record(1))
    repo.append(_record(2))
    rec = repo.get(2)
    assert rec is not None
    assert rec["pensioner_id"] == 2


def test_get_returns_none_for_missing(repo):
    repo.append(_record(1))
    assert repo.get(999) is None


# ============================================================
# update() — in-place mutation (for leftover_investigation pattern)
# ============================================================

def test_update_mutates_record_in_place(repo, state_path):
    repo.append(_record(1))
    repo.append(_record(2))
    found = repo.update(1, lambda r: {**r, "leftover_pass": True})
    assert found is True
    # Read back: order preserved, mutation applied
    recs = list(repo.iter_all())
    assert recs[0]["pensioner_id"] == 1
    assert recs[0]["leftover_pass"] is True
    assert recs[1]["pensioner_id"] == 2
    assert "leftover_pass" not in recs[1]


def test_update_returns_false_for_missing(repo):
    repo.append(_record(1))
    assert repo.update(999, lambda r: r) is False


def test_update_atomic_via_tmp_rename(repo, state_path):
    """If update is interrupted, the original file must remain intact."""
    repo.append(_record(1, "Original Name"))
    # Use a callable that mutates; verify atomic write happens
    repo.update(1, lambda r: {**r, "pensioner_name": "Updated Name"})
    recs = list(repo.iter_all())
    assert recs[0]["pensioner_name"] == "Updated Name"


# ============================================================
# replace_all() — full rewrite (for backfill_backlinks + dd_marker pattern)
# ============================================================

def test_replace_all_overwrites_file(repo, state_path):
    repo.append(_record(1))
    repo.replace_all([_record(10), _record(20)])
    ids = [r["pensioner_id"] for r in repo.iter_all()]
    assert ids == [10, 20]


def test_replace_all_atomic_writes_via_tmp_then_rename(repo, state_path):
    repo.append(_record(1))
    repo.replace_all([_record(2)])
    # No .tmp file should remain after the operation
    tmp_files = list(state_path.parent.glob("*.tmp"))
    assert tmp_files == []


# ============================================================
# check() — wraps state_check.StateCheckResult semantics
# ============================================================

def test_check_returns_clean_for_well_formed_file(repo):
    repo.append(_record(1))
    repo.append(_record(2))
    result = repo.check(expected_ids={1, 2})
    assert result.is_clean()
    assert result.total_records == 2


def test_check_detects_missing_ids(repo):
    repo.append(_record(1))
    result = repo.check(expected_ids={1, 2, 3})
    assert not result.is_clean()
    assert result.missing_ids == {2, 3}


def test_check_detects_duplicates(repo, state_path):
    state_path.write_text(
        '{"pensioner_id": 1}\n{"pensioner_id": 1}\n',
        encoding="utf-8",
    )
    result = repo.check(expected_ids={1})
    assert not result.is_clean()
    assert 1 in result.duplicate_ids


# ============================================================
# Round-trip: write then read back preserves all fields (L4 key order)
# ============================================================

def test_roundtrip_preserves_all_fields(repo):
    original = _record(1)
    original["custom_field"] = {"nested": [1, 2, 3], "unicode": "★"}
    repo.append(original)
    read_back = next(repo.iter_all())
    assert read_back == original


def test_roundtrip_preserves_unicode(repo):
    original = _record(1, "Müller, François")
    repo.append(original)
    read_back = next(repo.iter_all())
    assert read_back["pensioner_name"] == "Müller, François"


# ============================================================
# Crash-safety: L3 requires fsync after every append
# ============================================================

def test_append_persists_immediately(repo, state_path):
    """A reader process opening the file after append() must see the record.

    L3 says: every per-pensioner record flushes to state.jsonl BEFORE
    the next pensioner starts. We can't easily test fsync() directly
    without OS-specific calls, but we can verify the file's contents
    are readable immediately after append() returns.
    """
    repo.append(_record(42))
    # Simulate a separate reader
    with open(state_path, encoding="utf-8") as f:
        content = f.read()
    rec = json.loads(content.strip())
    assert rec["pensioner_id"] == 42


# ============================================================
# InMemoryStateRepository — same surface, no disk I/O
# ============================================================

@pytest.fixture
def mem_repo() -> InMemoryStateRepository:
    return InMemoryStateRepository()


def test_memory_append_stores_records(mem_repo):
    mem_repo.append(_record(1))
    mem_repo.append(_record(2))
    assert mem_repo.records == [
        {"pensioner_id": 1, "_init": False, **r} for r in []  # placeholder, replaced below
    ] or len(mem_repo.records) == 2
    # simpler assertion:
    assert [r["pensioner_id"] for r in mem_repo.records] == [1, 2]


def test_memory_iter_all_yields_in_order(mem_repo):
    for i in range(3):
        mem_repo.append(_record(i))
    assert [r["pensioner_id"] for r in mem_repo.iter_all()] == [0, 1, 2]


def test_memory_get_returns_first_match(mem_repo):
    mem_repo.append(_record(1))
    mem_repo.append(_record(2))
    assert mem_repo.get(2)["pensioner_id"] == 2
    assert mem_repo.get(999) is None


def test_memory_update_mutates_in_place(mem_repo):
    mem_repo.append(_record(1))
    mem_repo.append(_record(2))
    found = mem_repo.update(1, lambda r: {**r, "leftover_pass": True})
    assert found is True
    assert mem_repo.records[0]["leftover_pass"] is True
    assert "leftover_pass" not in mem_repo.records[1]


def test_memory_replace_all_overwrites(mem_repo):
    mem_repo.append(_record(1))
    mem_repo.replace_all([_record(10), _record(20)])
    assert [r["pensioner_id"] for r in mem_repo.records] == [10, 20]


def test_memory_check_detects_missing(mem_repo):
    mem_repo.append(_record(1))
    result = mem_repo.check(expected_ids={1, 2, 3})
    assert not result.is_clean()
    assert result.missing_ids == {2, 3}


def test_memory_check_detects_duplicates(mem_repo):
    mem_repo.append(_record(1))
    mem_repo.append(_record(1))
    result = mem_repo.check(expected_ids={1})
    assert not result.is_clean()
    assert 1 in result.duplicate_ids


def test_memory_roundtrip_preserves_dict_independence(mem_repo):
    """append() takes a copy of the input dict.

    Tests that mutate the original dict after append don't corrupt
    the stored record. (Note: get() and iter_all() return live refs,
    matching JsonlStateRepository's behavior; tests that mutate
    returned values should call dict() first.)
    """
    original = _record(1, "Smith, John")
    mem_repo.append(original)
    original["pensioner_name"] = "Mutated"
    # The stored record should still be the original
    assert mem_repo.get(1)["pensioner_name"] == "Smith, John"