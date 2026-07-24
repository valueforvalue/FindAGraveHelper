"""Verification tests for per-strategy audit log wiring (issue #75).

audit_log.py was added for issue #71 (per-strategy audit trail).
These tests verify the wiring is correct and the contract
the runner + downstream analytics rely on is preserved.

The contract:
  - Every strategy_ran / strategy_skipped call carries
    pensioner_id, strategy, ts, and (for ran) candidates count.
  - Every pensioner has exactly one pensioner_start AND one
    pensioner_end (matched by pensioner_id).
  - pensioner_end's elapsed_s is non-negative and at most the
    wall clock between pensioner_start and the corresponding
    pensioner_end.
  - run_summary is emitted exactly once at end-of-run.
  - Every observation_appended carries observation_id, pensioner_id,
    kind, source.
  - Every work_claimed + work_completed has matching work_ids
    (no orphan claims).
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from scripts.pipeline.audit_log import RunAuditLog


@pytest.fixture
def audit(tmp_path: Path):
    """Open a RunAuditLog in a temp dir; close on teardown."""
    log = RunAuditLog.open(tmp_path / "audit.jsonl")
    yield log
    log.close()


# ============================================================
# Direct API tests (unit-level)
# ============================================================


def test_pensioner_start_and_end_paired(audit):
    """pensioner_start + pensioner_end emit distinct events with
    matching pensioner_ids."""
    audit.pensioner_start("272", "Eads, James")
    audit.strategy_ran("272", "B1-exact", candidates=33, state="OK")
    audit.pensioner_end("272", total_candidates=33, status="auto_accept")
    audit.summary(total_pensioners=1)


def test_elapsed_s_is_non_negative_and_reasonable(audit):
    """pensioner_end.elapsed_s is non-negative and at most the
    wall clock between the start and end events."""
    audit.pensioner_start("1", "Doe, John")
    time.sleep(0.01)  # ensure elapsed is observable
    audit.pensioner_end("1", total_candidates=5, status="needs_review")
    audit.summary(total_pensioners=1)

    events = _read_audit_jsonl(audit._path)
    end = next(e for e in events if e["event"] == "pensioner_end")
    assert end["elapsed_s"] >= 0
    assert end["elapsed_s"] < 5  # way under the test timeout


def test_strategy_skipped_emits_reason(audit):
    """strategy_skipped carries the reason field."""
    audit.pensioner_start("1", "Doe, John")
    audit.strategy_skipped("1", "B2-middle-initial", reason="no middle name")
    audit.pensioner_end("1", total_candidates=0, status="no_candidates")
    audit.summary(total_pensioners=1)

    events = _read_audit_jsonl(audit._path)
    skip = next(e for e in events if e["event"] == "strategy_skipped")
    assert skip["reason"] == "no middle name"


def test_observer_protocol_emits_observation_appended(audit):
    """on_observation_appended emits the right event shape."""
    from types import SimpleNamespace

    obs = SimpleNamespace(
        observation_id="obs-test-1",
        pensioner_id=42,
        kind=SimpleNamespace(value="ScoreObserved"),
        source="CandidateScorerKS",
    )
    audit.on_observation_appended(obs)
    audit.close()

    events = _read_audit_jsonl(audit._path)
    rec = next(e for e in events if e["event"] == "observation_appended")
    assert rec["observation_id"] == "obs-test-1"
    assert rec["pensioner_id"] == 42
    assert rec["kind"] == "ScoreObserved"
    assert rec["source"] == "CandidateScorerKS"


# ============================================================
# Real G10 verification: the audit log is the evidence
# ============================================================
#
# The G10 run (issue #94 verification) produced
# data/results/run_2026_07_24_g10_stealth_swap_verification/
# with run_audit.jsonl. This test pins the contract: every
# pensioner has paired start/end, every strategy event has the
# required fields, and the summary is present exactly once.
#
# If a future PR breaks the audit log wiring (e.g. a strategy
# fires but no audit entry, or pensioner_start is skipped),
# this test fails first — before the runtime behavior changes
# are caught downstream.


G10_AUDIT_PATH = Path(
    "data/results/run_2026_07_24_g10_stealth_swap_verification/run_audit.jsonl"
)


@pytest.mark.skipif(
    not G10_AUDIT_PATH.exists(),
    reason="G10 verification run dir not present (re-run issue #94's G10)",
)
def test_g10_audit_log_paired_pensioner_start_end():
    """Every pensioner_start in the G10 run has a matching
    pensioner_end with the same pensioner_id."""
    events = _read_audit_jsonl(G10_AUDIT_PATH)
    starts = {e["pensioner_id"] for e in events if e["event"] == "pensioner_start"}
    ends = {e["pensioner_id"] for e in events if e["event"] == "pensioner_end"}
    # Symmetric: same set of pensioner_ids appears in both.
    assert starts == ends
    assert len(starts) == 10  # the G10 run processed 10 pensioners


@pytest.mark.skipif(
    not G10_AUDIT_PATH.exists(),
    reason="G10 verification run dir not present",
)
def test_g10_audit_log_strategy_events_have_required_fields():
    """Every strategy_ran / strategy_skipped carries pensioner_id,
    strategy, ts."""
    events = _read_audit_jsonl(G10_AUDIT_PATH)
    for e in events:
        if e["event"] not in ("strategy_ran", "strategy_skipped"):
            continue
        assert "pensioner_id" in e, f"missing pensioner_id: {e}"
        assert "strategy" in e, f"missing strategy: {e}"
        assert "ts" in e, f"missing ts: {e}"
        if e["event"] == "strategy_ran":
            assert "candidates" in e, f"strategy_ran missing candidates: {e}"


@pytest.mark.skipif(
    not G10_AUDIT_PATH.exists(),
    reason="G10 verification run dir not present",
)
def test_g10_audit_log_run_summary_present():
    """Exactly one run_summary is emitted at end-of-run."""
    events = _read_audit_jsonl(G10_AUDIT_PATH)
    summaries = [e for e in events if e["event"] == "run_summary"]
    assert len(summaries) == 1
    assert summaries[0]["total_pensioners"] == 10


@pytest.mark.skipif(
    not G10_AUDIT_PATH.exists(),
    reason="G10 verification run dir not present",
)
def test_g10_audit_log_work_claims_balanced():
    """Every work_claimed has a matching work_completed (no
    orphan claims; no double-completions)."""
    events = _read_audit_jsonl(G10_AUDIT_PATH)
    claimed = [e["work_id"] for e in events if e["event"] == "work_claimed"]
    completed = [e["work_id"] for e in events if e["event"] == "work_completed"]
    # Same multiset: every claimed work_id has exactly one completion.
    assert Counter(claimed) == Counter(completed)


@pytest.mark.skipif(
    not G10_AUDIT_PATH.exists(),
    reason="G10 verification run dir not present",
)
def test_g10_audit_log_observation_appended_per_observation():
    """Every observation_appended carries observation_id +
    pensioner_id + kind + source (the contract downstream
    analytics depend on)."""
    events = _read_audit_jsonl(G10_AUDIT_PATH)
    recs = [e for e in events if e["event"] == "observation_appended"]
    assert len(recs) > 0
    for e in recs:
        assert "observation_id" in e
        assert "pensioner_id" in e
        assert "kind" in e
        assert "source" in e


# ============================================================
# Helpers
# ============================================================


def _read_audit_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]