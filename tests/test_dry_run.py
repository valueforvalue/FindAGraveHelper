"""Tests for the --dry-run reversibility surface (issue #21).

The dry-run branch in run_unified.py must:
  - exercise the non-FaG pipeline (matching, scoring, CGR)
  - NEVER make a FaG network request
  - emit a JSONL diff file showing which records would change

TDD: written red first (this commit), then implementation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.pipeline.dry_run import (
    diff_record,
    write_dry_run_diff,
    predict_outcome_from_state,
)


# ============================================================
# Fixtures
# ============================================================

def _state_record(pid: int, outcome: str = "auto_accept", score: float = 0.9,
                  fag_status: str = "found") -> dict:
    rec = {
        "pensioner_id": pid,
        "pensioner_app_number": f"A{pid}",
        "pensioner_name": f"Smith {pid}",
        "pensioner_first": "John",
        "pensioner_last": "Smith",
        "fag_status": fag_status,
        "best_score": score,
        "best_candidate": {"memorial_id": "12345"},
        "ranked_candidates": [{"memorial_id": "12345", "score": score}],
        "status": outcome,
        "cgr_records": [],
        "cgr_status": "no_match",
        "timestamp": "2026-07-17T00:00:00",
    }
    # Populate fag_records so predict_outcome_from_state has data
    # to derive best_score from. Without this, the prediction would
    # be derived from an empty list, which is the no_results path.
    if fag_status != "no_results":
        rec["fag_records"] = [{"memorial_id": "12345", "score": score}]
    else:
        rec["fag_records"] = []
    return rec


# ============================================================
# diff_record() — pure function, no I/O
# ============================================================

def test_diff_record_marks_no_change_when_identical():
    rec = _state_record(1, outcome="auto_accept", score=0.9)
    diff = diff_record(rec, rec)
    assert diff["pensioner_id"] == 1
    assert diff["would_change"] is False
    assert diff["fields_changed"] == []


def test_diff_record_detects_score_change():
    current = _state_record(1, outcome="auto_accept", score=0.9)
    predicted = _state_record(1, outcome="auto_accept", score=0.91)
    diff = diff_record(current, predicted)
    assert diff["would_change"] is True
    assert "best_score" in diff["fields_changed"]


def test_diff_record_detects_outcome_change():
    current = _state_record(1, outcome="auto_accept")
    predicted = _state_record(1, outcome="too_many")
    diff = diff_record(current, predicted)
    assert diff["would_change"] is True
    assert "status" in diff["fields_changed"]
    assert diff["current_outcome"] == "auto_accept"
    assert diff["predicted_outcome"] == "too_many"


def test_diff_record_detects_fag_status_change():
    current = _state_record(1, fag_status="found")
    predicted = _state_record(1, fag_status="no_results")
    diff = diff_record(current, predicted)
    assert diff["would_change"] is True
    assert "fag_status" in diff["fields_changed"]


def test_diff_record_ignores_unimportant_field_diffs():
    """Timestamp and runtime fields should not count as 'changes'."""
    current = _state_record(1)
    current["timestamp"] = "2026-07-17T00:00:00"
    predicted = _state_record(1)
    predicted["timestamp"] = "2026-07-17T01:00:00"
    diff = diff_record(current, predicted)
    assert diff["would_change"] is False
    # timestamp might still appear in fields_changed for transparency,
    # but it should NOT trigger would_change
    assert diff["would_change"] is False


# ============================================================
# predict_outcome_from_state() — non-FaG outcome derivation
# ============================================================

def test_predict_outcome_from_state_passes_through():
    """When the prediction comes from re-scoring existing FaG results
    (no new FaG request), we reuse fag_records and re-derive the outcome."""
    rec = _state_record(1, outcome="auto_accept", score=0.95)
    predicted = predict_outcome_from_state(rec, low_score_threshold=0.40)
    # No new FaG data, so outcome should be derivable from existing fields
    assert predicted["pensioner_id"] == 1
    assert predicted["best_score"] == 0.95


def test_predict_outcome_from_state_never_returns_fag_query_marker():
    """The prediction must NEVER indicate that a FaG query is needed.
    If the existing state has no fag_records, prediction = 'no_results'."""
    rec = _state_record(1, fag_status="no_results", score=0.0)
    predicted = predict_outcome_from_state(rec, low_score_threshold=0.40)
    assert predicted["fag_status"] == "no_results"
    assert predicted["best_score"] == 0.0


# ============================================================
# write_dry_run_diff() — JSONL file emission
# ============================================================

def test_write_dry_run_diff_creates_jsonl(tmp_path):
    current_path = tmp_path / "state.jsonl"
    current_path.write_text(
        json.dumps(_state_record(1)) + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "dry_run_diff.jsonl"

    n_changed = write_dry_run_diff(
        out_path=out_path,
        current_state_path=current_path,
        predictions=[_state_record(1)],  # identical
    )
    assert n_changed == 0
    lines = out_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    diff = json.loads(lines[0])
    assert diff["would_change"] is False


def test_write_dry_run_diff_counts_changes(tmp_path):
    current_path = tmp_path / "state.jsonl"
    state_records = [
        _state_record(1, score=0.9),
        _state_record(2, score=0.3),
        _state_record(3, score=0.5),
    ]
    current_path.write_text(
        "\n".join(json.dumps(r) for r in state_records) + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "dry_run_diff.jsonl"

    # Predictions: 1 changes score, 2 changes outcome, 3 unchanged
    predictions = [
        _state_record(1, score=0.95),       # change: score
        _state_record(2, outcome="too_many"),  # change: outcome
        _state_record(3, score=0.5),       # no change
    ]
    n_changed = write_dry_run_diff(
        out_path=out_path,
        current_state_path=current_path,
        predictions=predictions,
    )
    assert n_changed == 2  # records 1 and 2

    lines = out_path.read_text(encoding="utf-8").strip().split("\n")
    diffs = [json.loads(line) for line in lines]
    assert len(diffs) == 3
    change_flags = [d["would_change"] for d in diffs]
    assert change_flags == [True, True, False]


def test_write_dry_run_diff_handles_missing_current_state(tmp_path):
    """If current state.jsonl doesn't exist, every prediction is a 'new'."""
    current_path = tmp_path / "does_not_exist.jsonl"
    out_path = tmp_path / "dry_run_diff.jsonl"

    n_changed = write_dry_run_diff(
        out_path=out_path,
        current_state_path=current_path,
        predictions=[_state_record(1)],
    )
    assert n_changed == 1  # all new = changed
    lines = out_path.read_text(encoding="utf-8").strip().split("\n")
    diff = json.loads(lines[0])
    assert diff["would_change"] is True
    assert diff["current_outcome"] is None


def test_write_dry_run_diff_skips_pensioners_without_predictions(tmp_path):
    """If current state has 3 records but predictions has only 2,
    the missing one is reported as 'no prediction available'."""
    current_path = tmp_path / "state.jsonl"
    state_records = [_state_record(1), _state_record(2), _state_record(3)]
    current_path.write_text(
        "\n".join(json.dumps(r) for r in state_records) + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "dry_run_diff.jsonl"

    # Only predictions for 1 and 2
    write_dry_run_diff(
        out_path=out_path,
        current_state_path=current_path,
        predictions=[_state_record(1), _state_record(2)],
    )
    diffs = [
        json.loads(line)
        for line in out_path.read_text(encoding="utf-8").strip().split("\n")
    ]
    by_pid = {d["pensioner_id"]: d for d in diffs}
    assert by_pid[3]["would_change"] is True  # no prediction = changed
    assert "no prediction available" in str(by_pid[3].get("notes", ""))