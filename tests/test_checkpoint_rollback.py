"""Tests for --rollback-to (issue #21).

Automatic checkpoints are written every N records. --rollback-to
restores state.jsonl from a named checkpoint, atomic via os.replace.

TDD: red first (this commit), then implementation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.pipeline.checkpoint import (
    write_checkpoint_snapshot,
    list_checkpoints,
    rollback_to_checkpoint,
    CHECKPOINT_PREFIX,
)


def _state_record(pid: int) -> dict:
    return {
        "pensioner_id": pid,
        "pensioner_app_number": f"A{pid}",
        "pensioner_name": f"Smith {pid}",
        "fag_status": "no_results",
        "best_score": 0.0,
        "status": "no_results",
        "timestamp": "2026-07-17T00:00:00",
    }


def _write_state(path: Path, pids: list[int]) -> None:
    path.write_text(
        "\n".join(json.dumps(_state_record(p)) for p in pids) + "\n",
        encoding="utf-8",
    )


# ============================================================
# write_checkpoint_snapshot()
# ============================================================

def test_write_checkpoint_snapshot_creates_file(tmp_path):
    state = tmp_path / "state.jsonl"
    _write_state(state, [1, 2, 3])

    snap_path = write_checkpoint_snapshot(state, label="before-v2")
    assert snap_path.exists()
    assert "before-v2" in snap_path.name
    # Content is identical to state.jsonl
    assert snap_path.read_text(encoding="utf-8") == state.read_text(encoding="utf-8")


def test_write_checkpoint_snapshot_label_must_be_safe(tmp_path):
    """Labels containing path separators or '..' should be rejected."""
    state = tmp_path / "state.jsonl"
    _write_state(state, [1])
    with pytest.raises(ValueError, match="unsafe checkpoint label"):
        write_checkpoint_snapshot(state, label="../escape")
    with pytest.raises(ValueError, match="unsafe checkpoint label"):
        write_checkpoint_snapshot(state, label="dir/file")


def test_write_checkpoint_snapshot_default_label_includes_count(tmp_path):
    state = tmp_path / "state.jsonl"
    _write_state(state, [1, 2, 3])
    snap = write_checkpoint_snapshot(state)  # auto label
    # Auto label includes 'N-records'
    assert "3-records" in snap.name or "checkpoint" in snap.name


# ============================================================
# list_checkpoints()
# ============================================================

def test_list_checkpoints_returns_all_in_order(tmp_path):
    state = tmp_path / "state.jsonl"
    _write_state(state, [1])
    # Create multiple checkpoints
    write_checkpoint_snapshot(state, label="ckpt-a")
    write_checkpoint_snapshot(state, label="ckpt-b")
    write_checkpoint_snapshot(state, label="ckpt-c")

    snapshots = list_checkpoints(state)
    assert len(snapshots) == 3
    labels = [s.name for s in snapshots]
    assert "ckpt-a" in str(labels)
    assert "ckpt-b" in str(labels)
    assert "ckpt-c" in str(labels)


def test_list_checkpoints_empty_when_none(tmp_path):
    state = tmp_path / "state.jsonl"
    _write_state(state, [1])
    assert list_checkpoints(state) == []


def test_list_checkpoints_ignores_non_checkpoint_files(tmp_path):
    state = tmp_path / "state.jsonl"
    _write_state(state, [1])
    write_checkpoint_snapshot(state, label="real")
    # Create a sibling file that doesn't match the checkpoint pattern
    (state.parent / "results.jsonl").write_text("unrelated", encoding="utf-8")
    (state.parent / "outliers.jsonl").write_text("unrelated", encoding="utf-8")

    snapshots = list_checkpoints(state)
    assert len(snapshots) == 1
    assert "real" in snapshots[0].name


# ============================================================
# rollback_to_checkpoint()
# ============================================================

def test_rollback_to_checkpoint_restores_state(tmp_path):
    state = tmp_path / "state.jsonl"
    _write_state(state, [1, 2, 3])
    snap = write_checkpoint_snapshot(state, label="v1")

    # Mutate state
    _write_state(state, [10, 20, 30])

    # Rollback
    rollback_to_checkpoint(state, label="v1")

    restored = [
        json.loads(line)["pensioner_id"]
        for line in state.read_text(encoding="utf-8").strip().split("\n")
    ]
    assert restored == [1, 2, 3]


def test_rollback_to_checkpoint_missing_label_raises(tmp_path):
    state = tmp_path / "state.jsonl"
    _write_state(state, [1])
    write_checkpoint_snapshot(state, label="v1")

    with pytest.raises(FileNotFoundError, match="v2"):
        rollback_to_checkpoint(state, label="v2")


def test_rollback_to_checkpoint_atomic(tmp_path):
    """If rollback fails midway, state.jsonl must remain intact."""
    state = tmp_path / "state.jsonl"
    _write_state(state, [1, 2, 3])
    snap = write_checkpoint_snapshot(state, label="v1")

    # Save the original content
    original = state.read_text(encoding="utf-8")

    # Simulate a failure during rollback by pointing at a nonexistent label
    try:
        rollback_to_checkpoint(state, label="does-not-exist")
    except FileNotFoundError:
        pass

    # State file should still have the original content
    assert state.read_text(encoding="utf-8") == original


def test_rollback_to_checkpoint_label_wildcard(tmp_path):
    """Operator can pass 'latest' to rollback to the most recent checkpoint."""
    state = tmp_path / "state.jsonl"
    _write_state(state, [1])
    write_checkpoint_snapshot(state, label="first")
    _write_state(state, [2])
    write_checkpoint_snapshot(state, label="second")
    _write_state(state, [99, 100])

    rollback_to_checkpoint(state, label="latest")

    restored = [
        json.loads(line)["pensioner_id"]
        for line in state.read_text(encoding="utf-8").strip().split("\n")
    ]
    # Should match the 'second' checkpoint (pensioner 2)
    assert restored == [2]