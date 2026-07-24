"""Tests for cross-run strategy stats analytics (issue #79).

strategy_stats.py was added to derive per-strategy success
metrics from the audit log. The contract: for each strategy
in the ladder, count fires / skipped / errors, sum
candidates, compute avg candidates, and compute the
success_rate (fraction of pensioners touched by this
strategy that ended auto_accept).

These tests pin the contract on a small synthetic audit log
plus a real-data check against the G10 verification run.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.analysis.strategy_stats import (
    aggregate_across_runs,
    collect_audit_files,
    parse_audit,
)


# ============================================================
# Helpers
# ============================================================


def _write_audit(
    out_dir: Path,
    events: list[dict],
) -> Path:
    """Write a synthetic run_audit.jsonl inside out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run_audit.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return path


def _strategy_ran(pid: str, strategy: str, candidates: int) -> dict:
    return {
        "ts": 1.0,
        "event": "strategy_ran",
        "pensioner_id": pid,
        "strategy": strategy,
        "candidates": candidates,
    }


def _strategy_skipped(pid: str, strategy: str) -> dict:
    return {
        "ts": 1.0,
        "event": "strategy_skipped",
        "pensioner_id": pid,
        "strategy": strategy,
    }


def _pensioner_end(pid: str, status: str) -> dict:
    return {
        "ts": 1.0,
        "event": "pensioner_end",
        "pensioner_id": pid,
        "status": status,
        "total_candidates": 10,
    }


# ============================================================
# collect_audit_files
# ============================================================


def test_collect_audit_files_finds_all_runs(tmp_path: Path):
    """Discovers all run_audit.jsonl files under the root."""
    _write_audit(tmp_path / "run_a", [_strategy_ran("1", "B1-exact", 5)])
    _write_audit(tmp_path / "run_b", [_strategy_ran("2", "B1-exact", 7)])
    _write_audit(tmp_path / "run_c", [])  # empty audit (zero-event run)
    files = collect_audit_files(tmp_path)
    names = sorted(f.parent.name for f in files)
    assert names == ["run_a", "run_b", "run_c"]


def test_collect_audit_files_empty_root(tmp_path: Path):
    """A non-existent root returns an empty list (no crash)."""
    assert collect_audit_files(tmp_path / "nonexistent") == []


# ============================================================
# parse_audit
# ============================================================


def test_parse_audit_basic_counts(tmp_path: Path):
    """Per-strategy counts: fires + skipped + total_candidates."""
    events = [
        _strategy_ran("1", "B1-exact", 5),
        _strategy_ran("1", "B1-exact", 3),
        _strategy_ran("1", "B3-fuzzy", 8),
        _strategy_skipped("1", "B2-middle"),
        _pensioner_end("1", "auto_accept"),
    ]
    path = _write_audit(tmp_path, events)
    stats = parse_audit(path)

    assert stats["B1-exact"]["fires"] == 2
    assert stats["B1-exact"]["skipped"] == 0
    assert stats["B1-exact"]["total_candidates"] == 8
    assert stats["B1-exact"]["avg_candidates"] == 4.0
    assert stats["B3-fuzzy"]["fires"] == 1
    assert stats["B3-fuzzy"]["total_candidates"] == 8
    assert stats["B2-middle"]["skipped"] == 1
    assert stats["B2-middle"]["fires"] == 0


def test_parse_audit_success_rate(tmp_path: Path):
    """success_rate = fraction of pensioners touched that ended auto_accept."""
    events = [
        # Pensioner 1: B1-exact fires, status auto_accept → success
        _strategy_ran("1", "B1-exact", 5),
        _pensioner_end("1", "auto_accept"),
        # Pensioner 2: B1-exact fires, status needs_review → not success
        _strategy_ran("2", "B1-exact", 3),
        _pensioner_end("2", "needs_review"),
        # Pensioner 3: only B3-fuzzy fires (not B1-exact)
        _strategy_ran("3", "B3-fuzzy", 8),
        _pensioner_end("3", "auto_accept"),
    ]
    path = _write_audit(tmp_path, events)
    stats = parse_audit(path)
    # B1-exact touched pensioners 1 and 2; only 1 ended auto_accept.
    # → success_rate = 1/2 = 0.5
    assert stats["B1-exact"]["pensioners_touched"] == 2
    assert stats["B1-exact"]["pensioners_accepted"] == 1
    assert stats["B1-exact"]["success_rate"] == 0.5
    # B3-fuzzy touched only pensioner 3, who auto_accept'd.
    assert stats["B3-fuzzy"]["success_rate"] == 1.0


def test_parse_audit_strategy_error_counted(tmp_path: Path):
    """strategy_error events bump the strategy's error count."""
    events = [
        {"ts": 1.0, "event": "strategy_error", "pensioner_id": "1",
         "strategy": "B1-exact", "error": "nav_timeout"},
        {"ts": 1.0, "event": "strategy_error", "pensioner_id": "2",
         "strategy": "B1-exact", "error": "nav_timeout"},
    ]
    path = _write_audit(tmp_path, events)
    stats = parse_audit(path)
    assert stats["B1-exact"]["errors"] == 2


def test_parse_audit_handles_blank_and_corrupt_lines(tmp_path: Path):
    """Robust to blank lines and corrupt JSON (the file gets
    written across many concurrent threads; partial writes
    happen during crashes)."""
    path = tmp_path / "run_audit.jsonl"
    path.write_text(
        "\n"  # blank
        + json.dumps(_strategy_ran("1", "B1-exact", 5)) + "\n"
        + "{not valid json\n"  # corrupt
        + json.dumps(_strategy_ran("2", "B3-fuzzy", 3)) + "\n",
        encoding="utf-8",
    )
    stats = parse_audit(path)
    # The two valid events are parsed; corrupt line is skipped
    # silently (no crash).
    assert stats["B1-exact"]["fires"] == 1
    assert stats["B3-fuzzy"]["fires"] == 1


# ============================================================
# aggregate_across_runs
# ============================================================


def test_aggregate_across_runs_sums_per_run(tmp_path: Path):
    """Per-strategy counts aggregate across multiple runs."""
    _write_audit(
        tmp_path / "run1",
        [
            _strategy_ran("1", "B1-exact", 5),
            _pensioner_end("1", "auto_accept"),
        ],
    )
    _write_audit(
        tmp_path / "run2",
        [
            _strategy_ran("2", "B1-exact", 7),
            _pensioner_end("2", "needs_review"),
        ],
    )
    report = aggregate_across_runs(tmp_path)
    assert report["runs_analyzed"] == 2
    assert report["strategies"]["B1-exact"]["fires"] == 2
    assert report["strategies"]["B1-exact"]["total_candidates"] == 12
    assert report["strategies"]["B1-exact"]["avg_candidates"] == 6.0
    # success_rate is averaged across runs: (1.0 + 0.0) / 2 = 0.5
    assert report["strategies"]["B1-exact"]["avg_success_rate"] == 0.5


def test_aggregate_across_runs_handles_no_runs(tmp_path: Path):
    """An empty root produces a degenerate report (zero runs, no
    strategies), not a crash."""
    report = aggregate_across_runs(tmp_path)
    assert report["runs_analyzed"] == 0
    assert report["runs"] == []
    assert report["strategies"] == {}


def test_aggregate_across_runs_run_summaries_listed(tmp_path: Path):
    """The per-run summary block lists every analyzed run with
    strategy count + total fires."""
    _write_audit(
        tmp_path / "alpha",
        [
            _strategy_ran("1", "B1-exact", 5),
            _strategy_ran("1", "B3-fuzzy", 3),
            _pensioner_end("1", "needs_review"),
        ],
    )
    _write_audit(
        tmp_path / "beta",
        [
            _strategy_ran("2", "B1-exact", 7),
            _pensioner_end("2", "auto_accept"),
        ],
    )
    report = aggregate_across_runs(tmp_path)
    assert report["runs_analyzed"] == 2
    by_name = {r["run"]: r for r in report["runs"]}
    assert by_name["alpha"]["strategies"] == 2
    assert by_name["alpha"]["total_fires"] == 2
    assert by_name["beta"]["strategies"] == 1
    assert by_name["beta"]["total_fires"] == 1


# ============================================================
# Real G10 verification (issue #94)
# ============================================================


G10_AUDIT_PATH = Path(
    "data/results/run_2026_07_24_g10_stealth_swap_verification/run_audit.jsonl"
)


@pytest.mark.skipif(
    not G10_AUDIT_PATH.exists(),
    reason="G10 verification run dir not present",
)
def test_g10_strategy_stats_aggregates_correctly(tmp_path: Path):
    """End-to-end check: aggregate the G10 audit log into a
    structure with the expected shape. Doesn't pin exact numbers
    (the G10 run is real FaG data, counts can vary) but does pin
    the structure: 1+ strategy, 1+ fires, success_rate in [0, 1]."""
    report = aggregate_across_runs(tmp_path)

    # Move the G10 audit log into a temp dir under tmp_path so
    # collect_audit_files finds it.
    run_dir = tmp_path / "g10"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_audit.jsonl").write_text(
        G10_AUDIT_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    report = aggregate_across_runs(tmp_path)
    assert report["runs_analyzed"] >= 1
    assert any(
        r["run"] == "g10" and r["total_fires"] > 0 for r in report["runs"]
    )

    # Pick a known strategy (B1-exact is in every FaG run) and
    # verify the structure.
    assert "B1-exact" in report["strategies"]
    s = report["strategies"]["B1-exact"]
    assert s["fires"] > 0
    assert 0.0 <= s["avg_success_rate"] <= 1.0
    assert s["avg_candidates"] > 0
    assert s["runs_with_data"] >= 1