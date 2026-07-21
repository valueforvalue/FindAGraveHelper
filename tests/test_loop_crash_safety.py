"""Integration test for crash safety in the main run loop.

We can't easily run the full Playwright loop in a unit test, so
we simulate it by patching search_one_pensioner to raise on a
specific pensioner ID and verify:
  - That pensioner gets an 'error' record in the state file
  - Other pensioners still get processed
  - Checkpoint is written for successful pensioners only
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_loop_continues_after_pensioner_failure(tmp_path, monkeypatch):
    """Simulate: pensioner #2 crashes; #1 and #3 still get processed."""
    # Patch search_one_pensioner: succeed for #1 and #3, fail for #2
    from scripts.fag import search as search_fag

    def fake_search(page, p_data):
        pid = p_data.get("id", -1)
        if pid == 2:
            raise RuntimeError("simulated browser crash")
        return {
            "pensioner_id": pid,
            "pensioner_name": f"Person {pid}",
            "status": "auto_accept",
            "ranked_candidates": [],
            "best_score": 0.5,
            "best_candidate": None,
            "strategies_run": ["B1-exact"],
        }

    monkeypatch.setattr(search_fag, "search_one_pensioner", fake_search)

    state_path = tmp_path / "state.jsonl"
    checkpoint_path = tmp_path / "state.checkpoint.json"

    pensioners = [
        {"id": 1, "first_name": "A", "last_name": "P"},
        {"id": 2, "first_name": "B", "last_name": "P"},
        {"id": 3, "first_name": "C", "last_name": "P"},
    ]

    # Replicate the loop's per-pensioner try/except
    for p_data in pensioners:
        pid = p_data.get("id", -1)
        try:
            record = search_fag.search_one_pensioner(None, p_data)
            search_fag.append_state(state_path, record)
            search_fag.write_checkpoint(
                checkpoint_path, pid, "B1-exact",
                pensioner_name=record.get("pensioner_name", ""),
            )
        except Exception as e:
            search_fag.record_failure(
                state_path, pid, p_data.get("first_name", ""), str(e)
            )

    # Inspect state file
    recs = [json.loads(l) for l in state_path.read_text(encoding="utf-8").strip().split("\n")]
    statuses = [(r["pensioner_id"], r["status"]) for r in recs]
    # All three should be in the state file
    assert len(recs) == 3
    # Pensioner 2 should have status 'error'
    p2 = [r for r in recs if r["pensioner_id"] == 2][0]
    assert p2["status"] == "error"
    assert "simulated browser crash" in p2.get("error", "")
    # Pensioners 1 and 3 should have status 'auto_accept'
    assert (1, "auto_accept") in statuses
    assert (3, "auto_accept") in statuses


def test_checkpoint_records_last_successful(tmp_path, monkeypatch):
    """Checkpoint records the LAST successful pensioner, not the failed one."""
    from scripts.fag import search as search_fag

    def fake_search(page, p_data):
        pid = p_data.get("id", -1)
        if pid == 2:
            raise RuntimeError("boom")
        return {
            "pensioner_id": pid,
            "pensioner_name": f"Person {pid}",
            "status": "auto_accept",
            "strategies_run": ["B1-exact"],
        }

    monkeypatch.setattr(search_fag, "search_one_pensioner", fake_search)

    state_path = tmp_path / "state.jsonl"
    checkpoint_path = tmp_path / "state.checkpoint.json"

    pensioners = [
        {"id": 1, "first_name": "A", "last_name": "P"},
        {"id": 2, "first_name": "B", "last_name": "P"},  # fails
        {"id": 3, "first_name": "C", "last_name": "P"},
    ]
    for p_data in pensioners:
        pid = p_data.get("id", -1)
        try:
            record = search_fag.search_one_pensioner(None, p_data)
            search_fag.append_state(state_path, record)
            search_fag.write_checkpoint(
                checkpoint_path, pid, "B1-exact",
                pensioner_name=record.get("pensioner_name", ""),
            )
        except Exception as e:
            search_fag.record_failure(
                state_path, pid, p_data.get("first_name", ""), str(e)
            )

    # Checkpoint should reflect pid=3 (last success), not pid=2
    cp = search_fag.read_checkpoint(checkpoint_path)
    assert cp["last_processed_id"] == 3
    assert cp["pensioner_name"] == "Person 3"

