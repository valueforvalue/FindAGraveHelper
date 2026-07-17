"""Tests for retry-errors helper.

After the main run completes, we need to retry pensioners that
errored due to the DOM crash (or any other transient issue).

The retry uses the same pipeline but ONLY touches records with
status='error' in the existing state.jsonl. Any successful retries
update the existing state record in place; any still-erroring
records remain as 'error' status.

Retry is necessary because:
  - some records that errored were due to the parse_results_page
    bug on common names
  - the bug is fixed in the current code
  - re-running just those records lets the report be complete
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline.retry_errors import (
    collect_error_pensioner_ids,
    retry_error_pensioners,
    RetryResult,
)


# ============================================================
# collect_error_pensioner_ids
# ============================================================
def _write_state(path, records):
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_collect_error_pensioner_ids_basic(tmp_path):
    """Collect pensioner IDs from records with status=error."""
    state_path = tmp_path / "state.jsonl"
    _write_state(state_path, [
        {"pensioner_id": 1, "fag_status": "auto_accept"},
        {"pensioner_id": 2, "fag_status": "error"},
        {"pensioner_id": 3, "fag_status": "too_many"},
        {"pensioner_id": 4, "fag_status": "error"},
        {"pensioner_id": 5},  # missing fag_status
    ])
    err_ids = collect_error_pensioner_ids(state_path)
    assert err_ids == {2, 4}


def test_collect_no_errors_returns_empty(tmp_path):
    """No errors → empty set."""
    state_path = tmp_path / "state.jsonl"
    _write_state(state_path, [
        {"pensioner_id": 1, "fag_status": "auto_accept"},
        {"pensioner_id": 2, "fag_status": "ambiguous"},
    ])
    err_ids = collect_error_pensioner_ids(state_path)
    assert err_ids == set()


def test_collect_handles_missing_file():
    """Missing file → empty set."""
    err_ids = collect_error_pensioner_ids(Path("/nope.jsonl"))
    assert err_ids == set()


def test_collect_deduplicates(tmp_path):
    """Same pensioner_id with multiple errors → one entry."""
    state_path = tmp_path / "state.jsonl"
    _write_state(state_path, [
        {"pensioner_id": 5, "fag_status": "error"},
        {"pensioner_id": 5, "fag_status": "error"},  # dup
    ])
    err_ids = collect_error_pensioner_ids(state_path)
    assert err_ids == {5}


def test_collect_skips_records_with_missing_pid(tmp_path):
    """Records without pensioner_id are skipped."""
    state_path = tmp_path / "state.jsonl"
    _write_state(state_path, [
        {"fag_status": "error"},  # no pensioner_id
        {"pensioner_id": 7, "fag_status": "error"},
    ])
    err_ids = collect_error_pensioner_ids(state_path)
    assert err_ids == {7}


# ============================================================
# retry_error_pensioners (orchestration)
# ============================================================
def _sample_pensioner(idx):
    return {
        "id": 1000 + idx,
        "first_name": f"John{idx}",
        "last_name": f"Doe{idx}",
        "regiment": "10 AL",
    }


def test_retry_error_pensioners_returns_retried_count(tmp_path):
    """retry_error_pensioners returns a RetryResult with counts."""
    out_dir = tmp_path / "retry_out"
    out_dir.mkdir()
    state_path = out_dir / "state.jsonl"
    _write_state(state_path, [
        {"pensioner_id": 1001, "fag_status": "error"},
        {"pensioner_id": 1002, "fag_status": "auto_accept"},
    ])

    def fake_fag(p, cfg):
        # Retry returns error again (still failing)
        return [], "error"

    cems = [{"cemetery_id": 1, "veterans": []}]

    result = retry_error_pensioners(
        state_path=state_path,
        cemeteries=cems,
        pensioners_by_id={1001: _sample_pensioner(1)},
        fag_search_fn=fake_fag,
        throttle_seconds=0.0,
    )
    assert isinstance(result, RetryResult)
    # We retried 1 record (1001), it still failed
    assert result.retried == 1
    assert result.still_error == 1
    assert result.recovered == 0


def test_retry_error_pensioners_updates_state_file(tmp_path):
    """Successful retry updates the state record in-place (same line)."""
    out_dir = tmp_path / "retry_out"
    out_dir.mkdir()
    state_path = out_dir / "state.jsonl"
    _write_state(state_path, [
        {"pensioner_id": 1001, "fag_status": "error", "best_score": 0.0},
        {"pensioner_id": 1002, "fag_status": "auto_accept", "best_score": 0.85},
    ])

    def fake_fag(p, cfg):
        # Return a valid candidate this time
        return [
            {"memorial_id": "999", "name": "John Doe",
             "backlink": "https://www.findagrave.com/memorial/999",
             "score": 0.75, "slug": "john-doe"},
        ], "auto_accept"

    cems = [{"cemetery_id": 1, "veterans": []}]

    retry_error_pensioners(
        state_path=state_path,
        cemeteries=cems,
        pensioners_by_id={1001: _sample_pensioner(1)},
        fag_search_fn=fake_fag,
        throttle_seconds=0.0,
    )
    # State file should be rewritten with both records (sorted by pensioner_id),
    # and pensioner 1001 should have best_score 0.75 now
    records = [json.loads(l) for l in state_path.open(encoding="utf-8")]
    rec_1001 = next(r for r in records if r["pensioner_id"] == 1001)
    assert rec_1001["fag_status"] == "auto_accept"
    assert rec_1001["best_score"] == 0.75
    # 1002 still has its original status
    rec_1002 = next(r for r in records if r["pensioner_id"] == 1002)
    assert rec_1002["fag_status"] == "auto_accept"


def test_retry_skips_pensioners_not_in_input(tmp_path):
    """If a pensioner_id is in state but not in pensioners_by_id, skip."""
    out_dir = tmp_path / "retry_out"
    out_dir.mkdir()
    state_path = out_dir / "state.jsonl"
    _write_state(state_path, [
        {"pensioner_id": 1001, "fag_status": "error"},
    ])

    def fake_fag(p, cfg):
        raise AssertionError("Should not be called")

    retry_error_pensioners(
        state_path=state_path,
        cemeteries=[],
        pensioners_by_id={},
        fag_search_fn=fake_fag,
        throttle_seconds=0.0,
    )
    # Empty pensioners_by_id → pensioner 1001 should not be retried
    records = [json.loads(l) for l in state_path.open(encoding="utf-8")]
    rec = records[0]
    assert rec["fag_status"] == "error"  # unchanged
    assert rec.get("retried_at") is None


def test_retry_records_retried_at(tmp_path):
    """After retry, the record has a retried_at timestamp."""
    out_dir = tmp_path / "retry_out"
    out_dir.mkdir()
    state_path = out_dir / "state.jsonl"
    _write_state(state_path, [
        {"pensioner_id": 1001, "fag_status": "error"},
    ])

    def fake_fag(p, cfg):
        # Return no_results but with an error status marker to simulate
        # FaG returning an error response
        return [], "error"

    cems = []
    retry_error_pensioners(
        state_path=state_path,
        cemeteries=cems,
        pensioners_by_id={1001: _sample_pensioner(1)},
        fag_search_fn=fake_fag,
        throttle_seconds=0.0,
    )
    records = [json.loads(l) for l in state_path.open(encoding="utf-8")]
    assert "retried_at" in records[0]
    # Still error, no retry-success
    assert records[0]["fag_status"] == "error"


def test_retry_result_to_dict():
    r = RetryResult(retried=5, recovered=3, still_error=2)
    d = r.to_dict()
    assert d["retried"] == 5
    assert d["recovered"] == 3
    assert d["still_error"] == 2