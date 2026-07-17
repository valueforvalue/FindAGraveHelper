"""Tests for checkpoint + crash safety.

The main run loop in search_fag.py processes one pensioner at a
time. If something blows up mid-loop (Playwright dies, network
error, etc.), we want:
  - Other pensioners in the run to keep processing
  - The state file to record what we got (or the error) for the
    failed pensioner
  - A checkpoint file we can read on re-run

These tests cover the checkpoint write/read functions in
isolation. The integration test (full run with a forced crash)
is harder to set up without a real browser; we test the
unit-level helpers instead.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline.checkpoint import (
    write_checkpoint,
    read_checkpoint,
    record_failure,
    is_resumable,
)


def test_write_checkpoint_creates_file(tmp_path):
    """write_checkpoint creates a JSON file at the given path."""
    cp_path = tmp_path / "ckpt.json"
    write_checkpoint(cp_path, last_processed_id=42, last_strategy="B1-exact")
    assert cp_path.exists()


def test_write_checkpoint_roundtrip(tmp_path):
    """A written checkpoint can be read back with same values."""
    cp_path = tmp_path / "ckpt.json"
    write_checkpoint(cp_path, last_processed_id=42, last_strategy="B1-exact",
                     pensioner_name="John Smith")
    cp = read_checkpoint(cp_path)
    assert cp["last_processed_id"] == 42
    assert cp["last_strategy"] == "B1-exact"
    assert cp["pensioner_name"] == "John Smith"


def test_read_checkpoint_returns_none_if_missing(tmp_path):
    """read_checkpoint returns None if the file doesn't exist."""
    cp_path = tmp_path / "missing.json"
    assert read_checkpoint(cp_path) is None


def test_read_checkpoint_returns_none_if_corrupt(tmp_path):
    """read_checkpoint returns None if the file is invalid JSON."""
    cp_path = tmp_path / "ckpt.json"
    cp_path.write_text("not json {", encoding="utf-8")
    assert read_checkpoint(cp_path) is None


def test_record_failure_creates_state_line(tmp_path):
    """record_failure writes a JSONL line for the failed pensioner."""
    state_path = tmp_path / "state.jsonl"
    record_failure(state_path, pensioner_id=99,
                   pensioner_name="Bad Person",
                   error="Browser crashed")
    assert state_path.exists()
    lines = state_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["pensioner_id"] == 99
    assert rec["status"] == "error"
    assert "Browser crashed" in rec.get("error", "")


def test_record_failure_appends_not_overwrites(tmp_path):
    """Multiple record_failure calls append; don't overwrite."""
    state_path = tmp_path / "state.jsonl"
    record_failure(state_path, 1, "Person A", "err A")
    record_failure(state_path, 2, "Person B", "err B")
    lines = state_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    ids = [json.loads(l)["pensioner_id"] for l in lines]
    assert ids == [1, 2]


def test_record_failure_includes_timestamp(tmp_path):
    """Failure record has an ISO timestamp."""
    state_path = tmp_path / "state.jsonl"
    record_failure(state_path, 1, "X", "boom")
    rec = json.loads(state_path.read_text(encoding="utf-8").strip())
    assert "timestamp" in rec


def test_is_resumable_returns_true_when_checkpoint_exists(tmp_path):
    """If a checkpoint file exists, the run is resumable."""
    cp_path = tmp_path / "ckpt.json"
    write_checkpoint(cp_path, 42, "B1-exact")
    assert is_resumable(cp_path) is True


def test_is_resumable_returns_false_when_missing(tmp_path):
    """No checkpoint file = not resumable."""
    cp_path = tmp_path / "missing.json"
    assert is_resumable(cp_path) is False


def test_is_resumable_returns_false_when_corrupt(tmp_path):
    """Corrupt checkpoint file = treat as non-resumable (don't crash)."""
    cp_path = tmp_path / "ckpt.json"
    cp_path.write_text("{invalid json", encoding="utf-8")
    assert is_resumable(cp_path) is False


def test_checkpoint_includes_run_metadata(tmp_path):
    """Checkpoint carries run-level metadata so re-runs can detect mismatches."""
    cp_path = tmp_path / "ckpt.json"
    write_checkpoint(
        cp_path,
        last_processed_id=42,
        last_strategy="B1-exact",
        run_id="run-2026-07-16",
        input_hash="abc123",
        state_file="state.jsonl",
    )
    cp = read_checkpoint(cp_path)
    assert cp["run_id"] == "run-2026-07-16"
    assert cp["input_hash"] == "abc123"
    assert cp["state_file"] == "state.jsonl"