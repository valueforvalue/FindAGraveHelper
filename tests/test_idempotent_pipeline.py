"""Tests for idempotent pipeline runs (issue #83).

The pipeline already supports idempotent re-runs:
- `state_repo.iter_all()` reads existing pensioner_ids.
- `run_unified.py` builds `completed_ids` and filters out
  pensioners already in the state file.
- `JsonlStateRepository.append()` opens the file in append
  mode (with flush + fsync per L3) so new rows are appended,
  not truncated.
- The post-passes (view_copy, state_schema, etc.) regenerate
  from the current state.

These tests pin the contract so a future refactor doesn't
break the idempotency guarantee.

The contract:
  - A JsonlStateRepository with 3 existing records, plus 2
    new appends, has 5 records (not 3, not 2).
  - The existing records are preserved verbatim (append
    mode).
  - `iter_all` yields all 5 in file order.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.state.repository import JsonlStateRepository


def _row(pid: int, name: str = "Doe, John") -> dict:
    return {
        "pensioner_id": pid,
        "pensioner_name": name,
        "status": "needs_review",
        "best_score": 0.5,
    }


def test_jsonl_repository_append_is_append_mode(tmp_path: Path):
    """Append adds to the file; does NOT truncate."""
    path = tmp_path / "state.jsonl"
    repo = JsonlStateRepository(path)
    repo.append(_row(1))
    repo.append(_row(2))
    repo.append(_row(3))
    # Re-open and append — file should grow, not reset.
    repo2 = JsonlStateRepository(path)
    repo2.append(_row(4))
    repo2.append(_row(5))
    lines = [
        l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    assert len(lines) == 5
    pids = [json.loads(l)["pensioner_id"] for l in lines]
    assert pids == [1, 2, 3, 4, 5]


def test_jsonl_repository_preserves_existing_records(tmp_path: Path):
    """Existing records survive a re-open + append cycle."""
    path = tmp_path / "state.jsonl"
    repo = JsonlStateRepository(path)
    original = [
        _row(1, "Alice"),
        _row(2, "Bob"),
    ]
    for r in original:
        repo.append(r)

    # Re-open and append a new record.
    repo2 = JsonlStateRepository(path)
    repo2.append(_row(3, "Carol"))

    all_rows = list(JsonlStateRepository(path).iter_all())
    assert len(all_rows) == 3
    assert [r["pensioner_id"] for r in all_rows] == [1, 2, 3]
    # The original two records are preserved byte-for-byte.
    assert all_rows[0]["pensioner_name"] == "Alice"
    assert all_rows[1]["pensioner_name"] == "Bob"


def test_iter_all_yields_records_in_file_order(tmp_path: Path):
    """Records are yielded in append order, regardless of
    re-openings."""
    path = tmp_path / "state.jsonl"
    repo = JsonlStateRepository(path)
    for i in [1, 2, 3]:
        repo.append(_row(i, f"name-{i}"))
    # Re-open and append more.
    repo2 = JsonlStateRepository(path)
    for i in [4, 5]:
        repo2.append(_row(i, f"name-{i}"))
    rows = list(JsonlStateRepository(path).iter_all())
    assert [r["pensioner_name"] for r in rows] == [
        "name-1", "name-2", "name-3", "name-4", "name-5",
    ]


def test_iter_all_skips_blank_lines(tmp_path: Path):
    """Blank lines (e.g. from a partial write) are skipped, not
    raised. Robust to file corruption from interrupted runs."""
    path = tmp_path / "state.jsonl"
    path.write_text(
        json.dumps(_row(1)) + "\n"
        + "\n"  # blank line
        + json.dumps(_row(2)) + "\n"
        + "   \n"  # whitespace-only line
        + json.dumps(_row(3)) + "\n",
        encoding="utf-8",
    )
    rows = list(JsonlStateRepository(path).iter_all())
    assert [r["pensioner_id"] for r in rows] == [1, 2, 3]


def test_completed_ids_extraction_from_state_file(tmp_path: Path):
    """The run_unified.py startup logic that builds `completed_ids`
    from `state_repo.iter_all()` produces the expected set. This
    is the key step for idempotency: pensioners already in
    results.jsonl are skipped on re-run."""
    path = tmp_path / "state.jsonl"
    repo = JsonlStateRepository(path)
    for pid in [10, 20, 30, 40]:
        repo.append(_row(pid))

    # Re-open and read the completed_ids the way run_unified does.
    completed_ids = {
        int(record["pensioner_id"])
        for record in JsonlStateRepository(path).iter_all(strict=True)
        if record.get("pensioner_id") is not None
    }
    assert completed_ids == {10, 20, 30, 40}


def test_idempotent_full_cycle_append_then_iter(tmp_path: Path):
    """Full cycle: write, re-open, append, iter. Proves the
    pattern run_unified uses for idempotent re-runs works."""
    path = tmp_path / "state.jsonl"
    repo = JsonlStateRepository(path)
    repo.append(_row(1))
    repo.append(_row(2))

    # Simulate the second run: read completed, append a new row.
    completed = {
        int(r["pensioner_id"])
        for r in JsonlStateRepository(path).iter_all(strict=True)
    }
    assert 1 in completed and 2 in completed
    assert 3 not in completed  # not yet processed

    # Re-open and append the new row.
    repo2 = JsonlStateRepository(path)
    repo2.append(_row(3))

    # Final state has all three.
    final = list(JsonlStateRepository(path).iter_all())
    assert [r["pensioner_id"] for r in final] == [1, 2, 3]