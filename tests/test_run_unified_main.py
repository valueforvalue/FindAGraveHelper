"""Tests for the unified runner main() orchestration logic.

We test the orchestration without the actual browser
(Playwright is heavy; tests use a fake fag_search_fn).
"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run_unified import (
    UnifiedRunnerConfig,
    ResumeTracker,
    write_unified_line,
    write_outliers_line,
    run_batch,
    BatchResult,
)


def _sample_pensioners(n=5):
    return [
        {
            "id": i + 1,
            "first_name": "John",
            "last_name": f"Smith{i}",
            "middle_name": "",
            "regiment": "10 AL",
            "death_year": "1930" if i % 2 == 0 else "",
            "application_number": f"A{i+1}",
            "pensioncard_backlink": "",
        }
        for i in range(n)
    ]


def _sample_cems():
    return [
        {"cemetery_id": 1, "veterans": []},
    ]


def test_run_batch_processes_all(tmp_path):
    """Batch processes each pensioner once."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    state = out_dir / "state.jsonl"
    outliers = out_dir / "outliers.jsonl"

    def fake_fag(pensioner, cfg):
        # Some get high scores, some low
        if pensioner["id"] % 2 == 0:
            return [
                {"memorial_id": str(pensioner["id"]), "score": 0.85,
                 "backlink": f"https://www.findagrave.com/memorial/{pensioner['id']}",
                 "name": "John Smith", "slug": "john-smith",
                 "details": {"death_year": pensioner.get("death_year", "1930")}},
            ], "auto_accept"
        else:
            return [], "no_results"

    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=fake_fag,
    )
    result = run_batch(
        pensioners=_sample_pensioners(5),
        cemeteries=_sample_cems(),
        config=cfg,
    )
    assert isinstance(result, BatchResult)
    assert result.processed == 5
    assert result.outliers_count > 0  # the odd ones had no_results
    assert state.exists()
    lines = state.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5


def test_run_batch_skips_completed(tmp_path):
    """Resume: pensioners already in state are skipped."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    state = out_dir / "state.jsonl"
    # Pre-populate with pensioner 1
    write_unified_line(state, {"pensioner_id": 1, "fag_status": "no_results"})

    fag_called = []
    def fake_fag(p, c):
        fag_called.append(p["id"])
        return [], "no_results"

    cfg = UnifiedRunnerConfig(out_dir=out_dir, fag_search_fn=fake_fag)
    result = run_batch(pensioners=_sample_pensioners(3), cemeteries=_sample_cems(), config=cfg)
    # Only pensioners 2 and 3 processed (1 was already done)
    assert 1 not in fag_called
    assert 2 in fag_called
    assert 3 in fag_called


def test_run_batch_writes_outliers(tmp_path):
    """outliers.jsonl gets only the outliers."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outliers = out_dir / "outliers.jsonl"

    def fake_fag(pensioner, cfg):
        if pensioner["id"] <= 2:
            return [
                {"memorial_id": "x", "score": 0.85,
                 "backlink": f"https://www.findagrave.com/memorial/x",
                 "name": "John Smith", "slug": "j"}
            ], "auto_accept"
        else:
            return [], "no_results"

    cfg = UnifiedRunnerConfig(out_dir=out_dir, fag_search_fn=fake_fag)
    result = run_batch(pensioners=_sample_pensioners(5), cemeteries=_sample_cems(), config=cfg)
    # Pensioners 3,4,5 are outliers
    assert outliers.exists()
    lines = outliers.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3
    ids = [json.loads(l)["pensioner_id"] for l in lines]
    assert ids == [3, 4, 5]


def test_run_batch_limit(tmp_path):
    """Limit caps the number of pensioners processed."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    state = out_dir / "state.jsonl"

    def fake_fag(p, c):
        return [], "no_results"

    cfg = UnifiedRunnerConfig(out_dir=out_dir, fag_search_fn=fake_fag, limit=3)
    result = run_batch(pensioners=_sample_pensioners(10), cemeteries=_sample_cems(), config=cfg)
    # Only 3 pensioners processed
    lines = state.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3


def test_run_batch_handles_pensioner_exception(tmp_path):
    """A pensioner that raises doesn't crash the whole batch."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    state = out_dir / "state.jsonl"

    def fake_fag(pensioner, cfg):
        if pensioner["id"] == 2:
            raise RuntimeError("boom")
        return [], "no_results"

    cfg = UnifiedRunnerConfig(out_dir=out_dir, fag_search_fn=fake_fag)
    # Should not raise; should write a record with status=error for pensioner 2
    result = run_batch(pensioners=_sample_pensioners(3), cemeteries=_sample_cems(), config=cfg)
    # Process should complete
    assert result.processed == 3
    # Pensioner 2 should have an error marker in the state
    lines = state.read_text(encoding="utf-8").strip().split("\n")
    records = [json.loads(l) for l in lines]
    err_rec = next((r for r in records if r["pensioner_id"] == 2), None)
    assert err_rec is not None
    assert err_rec.get("error") or err_rec.get("fag_status") == "error"


def test_run_batch_generates_report(tmp_path):
    """At completion, report.md + report.json are written."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=lambda p, c: ([], "no_results"),
    )
    run_batch(pensioners=_sample_pensioners(3), cemeteries=_sample_cems(), config=cfg)
    # report.md and report.json should exist
    md_files = list(out_dir.glob("report*.md"))
    json_files = list(out_dir.glob("report*.json"))
    assert len(md_files) >= 1
    assert len(json_files) >= 1
    # Read the markdown, see it has headline
    md_content = md_files[0].read_text(encoding="utf-8")
    assert "Find a Grave Helper" in md_content


def test_run_batch_records_count_in_both_files(tmp_path):
    """state.jsonl and outliers.jsonl counts add to total processed."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    state = out_dir / "state.jsonl"
    outliers = out_dir / "outliers.jsonl"

    def fake_fag(p, c):
        if p["id"] <= 2:
            return [
                {"memorial_id": str(p["id"]), "score": 0.85,
                 "backlink": f"https://www.findagrave.com/memorial/{p['id']}"},
            ], "auto_accept"
        return [], "no_results"

    cfg = UnifiedRunnerConfig(out_dir=out_dir, fag_search_fn=fake_fag)
    run_batch(pensioners=_sample_pensioners(5), cemeteries=_sample_cems(), config=cfg)
    state_lines = state.read_text(encoding="utf-8").strip().split("\n")
    outliers_lines = outliers.read_text(encoding="utf-8").strip().split("\n")
    assert len(state_lines) == 5
    assert len(outliers_lines) == 3  # pensioners 3,4,5


def test_batch_result_to_dict():
    """BatchResult serializes for reports."""
    r = BatchResult(
        total=10, processed=10, outliers_count=3, errors=1,
        started_at=1.0, finished_at=11.0,
    )
    d = r.to_dict()
    assert d["total"] == 10
    assert d["processed"] == 10
    assert d["elapsed_seconds"] == 10.0