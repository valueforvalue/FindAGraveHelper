"""Tests for J4: the unified runner CLI.

The runner coordinates CGR blocking + FaG search + state writes.
We test the helper logic in isolation, mocking the actual
Playwright/browser side.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run_unified import (
    ResumeTracker,
    heartbeat_logger,
    write_outliers_line,
    load_existing_ids,
    UnifiedRunnerConfig,
    run_one_pensioner_cgr_only,
)
from scripts.state.repository import JsonlStateRepository


# ============================================================
# ResumeTracker
# ============================================================
def test_resume_tracker_starts_empty(tmp_path):
    state = tmp_path / "state.jsonl"
    rt = ResumeTracker(state_path=state)
    assert rt.completed_ids == set()
    assert rt.count() == 0


def test_resume_tracker_loads_existing(tmp_path):
    state = tmp_path / "state.jsonl"
    state.write_text(
        json.dumps({"pensioner_id": 1}) + "\n" +
        json.dumps({"pensioner_id": 2}) + "\n",
        encoding="utf-8",
    )
    rt = ResumeTracker(state_path=state)
    assert rt.completed_ids == {1, 2}
    assert rt.count() == 2


def test_resume_tracker_ignores_corrupt_lines(tmp_path):
    """Malformed JSON lines should not crash."""
    state = tmp_path / "state.jsonl"
    state.write_text(
        "{not valid json\n" +
        json.dumps({"pensioner_id": 5}) + "\n",
        encoding="utf-8",
    )
    rt = ResumeTracker(state_path=state)
    assert rt.completed_ids == {5}


def test_resume_tracker_handles_missing_file():
    """No file → empty."""
    rt = ResumeTracker(state_path=Path("/nope/state.jsonl"))
    assert rt.completed_ids == set()


def test_resume_tracker_filters_by_id():
    """Records with no pensioner_id are skipped."""
    state = Path("/tmp/state.jsonl")
    state.write_text(
        json.dumps({"no_id": True}) + "\n" +
        json.dumps({"pensioner_id": 5}) + "\n",
        encoding="utf-8",
    )
    rt = ResumeTracker(state_path=state)
    # only the one with pensioner_id=5 counts
    assert 5 in rt.completed_ids


# ============================================================
# load_existing_ids
# ============================================================
def test_load_existing_ids_returns_set():
    path = Path("/tmp/state.jsonl")
    path.write_text(
        json.dumps({"pensioner_id": 1}) + "\n" +
        json.dumps({"pensioner_id": 2}) + "\n",
        encoding="utf-8",
    )
    ids = load_existing_ids(path)
    assert ids == {1, 2}


# ============================================================
# write_unified_line + write_outliers_line
# ============================================================
def test_state_repo_append_persists_records(tmp_path):
    """Issue #22: write_unified_line adapter removed; tests use the
    Repository directly. Each call appends one line and flushes+fsyncs (L3)."""
    state_path = tmp_path / "state.jsonl"
    repo = JsonlStateRepository(state_path)
    repo.append({"pensioner_id": 1})
    repo.append({"pensioner_id": 2})
    lines = state_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["pensioner_id"] == 1
    assert json.loads(lines[1])["pensioner_id"] == 2


def test_write_outliers_line_appends(tmp_path):
    outliers_path = tmp_path / "outliers.jsonl"
    write_outliers_line(outliers_path, {"pensioner_id": 99})
    lines = outliers_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["pensioner_id"] == 99


# ============================================================
# run_one_pensioner_cgr_only (no FaG)
# ============================================================
def test_run_one_pensioner_cgr_only(tmp_path):
    """When FaG is not provided, only CGR runs."""
    cems = [
        {"cemetery_id": 1, "veterans": [
            {"id": 100, "name": "John Smith", "died_state": "OK", "died": "1930"}
        ]},
    ]
    pensioner = {
        "id": 5, "first_name": "John", "last_name": "Smith",
        "regiment": "10 AL", "death_year": "1930",
    }
    cfg = UnifiedRunnerConfig()
    record = run_one_pensioner_cgr_only(pensioner, cems, cfg)
    assert record["pensioner_id"] == 5
    assert record["cgr_records"] is not None
    assert record["fag_status"] == "not_run"


# ============================================================
# UnifiedRunnerConfig
# ============================================================
def test_unified_runner_config_defaults():
    cfg = UnifiedRunnerConfig()
    assert cfg.throttle_seconds == 2.5
    assert cfg.low_score_threshold == 0.40
    assert cfg.out_dir is None  # caller must set


def test_unified_runner_config_customizable():
    cfg = UnifiedRunnerConfig(throttle_seconds=3.0, low_score_threshold=0.50)
    assert cfg.throttle_seconds == 3.0
    assert cfg.low_score_threshold == 0.50


# ============================================================
# heartbeat_logger
# ============================================================
def test_heartbeat_logs_progress():
    """heartbeat produces a one-line summary."""
    import io
    import logging
    log = logging.getLogger("test_hb")
    log.setLevel(logging.INFO)
    sink = io.StringIO()
    handler = logging.StreamHandler(sink)
    log.addHandler(handler)

    state_path = Path("/tmp/state.jsonl")
    heartbeat_logger(
        log,
        state_path=state_path,
        total=100,
        processed=42,
        started_at=1700000000.0,
        now=1700000700.0,  # 700s later
    )
    handler.flush()
    out = sink.getvalue()
    assert "42/100" in out
    assert "eta" in out.lower()