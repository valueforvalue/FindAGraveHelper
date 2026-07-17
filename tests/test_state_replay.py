"""Tests for --state-replay (issue #21).

state-replay reads an OLD state.jsonl and applies the non-FaG
pipeline stages (matching, scoring, BOTH MATCH) to produce a
NEW state file. Useful for A/B testing strategy changes
against historical state without re-running FaG.

TDD: red first (this commit), then implementation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.pipeline.state_replay import (
    replay_state,
    list_replay_changes,
)


def _state_record(pid: int, *, outcome: str = "auto_accept",
                  score: float = 0.9, fag_status: str = "found") -> dict:
    rec = {
        "pensioner_id": pid,
        "pensioner_app_number": f"A{pid}",
        "pensioner_name": f"Smith {pid}",
        "pensioner_first": "John",
        "pensioner_last": "Smith",
        "fag_status": fag_status,
        "best_score": score,
        "best_candidate": {"memorial_id": "12345"},
        "ranked_candidates": [],
        "status": outcome,
        "cgr_records": [],
        "cgr_status": "no_match",
        "timestamp": "2026-07-01T00:00:00",
    }
    if fag_status != "no_results":
        rec["fag_records"] = [{"memorial_id": "12345", "score": score}]
    else:
        rec["fag_records"] = []
    return rec


# ============================================================
# replay_state() — read OLD state, apply new pipeline, write NEW
# ============================================================

def test_replay_state_copies_records_with_new_metadata(tmp_path):
    """A replay should produce a new state.jsonl with the same
    records, recomputed non-FaG fields, and a replayed_at timestamp."""
    old_state = tmp_path / "old.jsonl"
    old_state.write_text(
        json.dumps(_state_record(1)) + "\n"
        + json.dumps(_state_record(2, score=0.3, outcome="low_score")) + "\n",
        encoding="utf-8",
    )
    new_state = tmp_path / "new.jsonl"

    n_records = replay_state(
        old_state_path=old_state,
        new_state_path=new_state,
        low_score_threshold=0.40,
    )
    assert n_records == 2

    new_records = [
        json.loads(line)
        for line in new_state.read_text(encoding="utf-8").strip().split("\n")
    ]
    assert len(new_records) == 2
    # Records are preserved
    assert [r["pensioner_id"] for r in new_records] == [1, 2]
    # Replay adds a timestamp marker
    assert all("replayed_at" in r for r in new_records)
    assert all("replayed_from" in r for r in new_records)


def test_replay_state_recomputes_outcome_with_new_threshold(tmp_path):
    """If the operator bumped low_score_threshold from 0.40 to 0.50,
    replaying with the new threshold should change status for
    records that previously fell in the gap."""
    old_state = tmp_path / "old.jsonl"
    old_state.write_text(
        json.dumps(_state_record(1, score=0.45, outcome="needs_review")) + "\n",
        encoding="utf-8",
    )
    new_state = tmp_path / "new.jsonl"

    replay_state(
        old_state_path=old_state,
        new_state_path=new_state,
        low_score_threshold=0.50,  # was 0.40 — 0.45 now falls below
    )

    rec = json.loads(new_state.read_text(encoding="utf-8").strip())
    # Old status: needs_review (0.45 >= 0.40)
    # New status: low_score (0.45 < 0.50)
    assert rec["status"] == "low_score"


def test_replay_state_preserves_fag_results_unchanged(tmp_path):
    """Replay must NOT recompute fag_records or best_score from FaG.
    Those are the historical artifact being preserved."""
    old_state = tmp_path / "old.jsonl"
    original = _state_record(1, score=0.87)
    old_state.write_text(json.dumps(original) + "\n", encoding="utf-8")
    new_state = tmp_path / "new.jsonl"

    replay_state(
        old_state_path=old_state,
        new_state_path=new_state,
        low_score_threshold=0.40,
    )

    rec = json.loads(new_state.read_text(encoding="utf-8").strip())
    assert rec["fag_records"] == original["fag_records"]
    assert rec["best_score"] == original["best_score"]


def test_replay_state_writes_atomically(tmp_path):
    old_state = tmp_path / "old.jsonl"
    old_state.write_text(json.dumps(_state_record(1)) + "\n", encoding="utf-8")
    new_state = tmp_path / "new.jsonl"

    # Pre-create stale file at new_state to verify it's replaced
    new_state.write_text("STALE", encoding="utf-8")

    replay_state(
        old_state_path=old_state,
        new_state_path=new_state,
        low_score_threshold=0.40,
    )
    content = new_state.read_text(encoding="utf-8")
    assert not content.startswith("STALE")
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_replay_state_handles_missing_old_state(tmp_path):
    """If old_state doesn't exist, return 0 (nothing to replay)."""
    missing = tmp_path / "does_not_exist.jsonl"
    new_state = tmp_path / "new.jsonl"

    n = replay_state(
        old_state_path=missing,
        new_state_path=new_state,
        low_score_threshold=0.40,
    )
    assert n == 0
    assert not new_state.exists()


# ============================================================
# list_replay_changes() — summary statistics
# ============================================================

def test_list_replay_changes_counts_status_changes(tmp_path):
    """Compute how many records' status changed between two replays."""
    old_state = tmp_path / "old.jsonl"
    new_state = tmp_path / "new.jsonl"
    # Build old: 3 records, status = [auto_accept, needs_review, low_score]
    old_state.write_text(
        "\n".join(json.dumps(r) for r in [
            _state_record(1, score=0.95, outcome="auto_accept"),
            _state_record(2, score=0.45, outcome="needs_review"),
            _state_record(3, score=0.30, outcome="low_score"),
        ]) + "\n",
        encoding="utf-8",
    )
    # Build new: same records, but record 2's outcome changed
    replay_state(
        old_state_path=old_state,
        new_state_path=new_state,
        low_score_threshold=0.50,  # 0.45 now falls below -> low_score
    )

    summary = list_replay_changes(old_state, new_state)
    assert summary["total"] == 3
    assert summary["status_changed"] == 1
    assert summary["unchanged"] == 2


def test_list_replay_changes_handles_missing_files(tmp_path):
    """If either file missing, return zeros rather than crash."""
    summary = list_replay_changes(
        tmp_path / "missing_old.jsonl",
        tmp_path / "missing_new.jsonl",
    )
    assert summary == {"total": 0, "status_changed": 0, "unchanged": 0}