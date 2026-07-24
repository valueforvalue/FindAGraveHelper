"""Tests for cross-run strategy dedup (#77).

When a pensioner has been searched in a prior run, the new run
should skip plans whose (strategy, scope) combo already ran
successfully on that pensioner. The BlackboardStore already
persists work_items + query_plans; the dedup helper just
joins them.

The contract:
  - `plan_already_completed(pid, strategy, scope)` returns True
    when there's a work_item for that pensioner with state in
    {succeeded, blocked, terminal}, tied to a plan with the
    matching (strategy, scope).
  - It returns False when no plan exists, when the work_item
    is still in flight (ready/leased/retryable), or when the
    (strategy, scope) doesn't match.
  - The match is exact: a different strategy on the same
    pensioner does NOT match.
  - A different scope on the same (pensioner, strategy) does
    NOT match.
"""

from __future__ import annotations

import pytest

from scripts.blackboard.schema import (
    Kind,
    Observation,
    PlanScope,
    QueryPlan,
    WorkItem,
    WorkState,
)
from scripts.blackboard.store import SqliteBlackboardStore


@pytest.fixture
def sqlite_store(tmp_path):
    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    yield store
    store.close()


def _enqueue_completed_plan(
    store, *, pid: int, strategy: str, scope: str, work_id_suffix: str
):
    """Helper: enqueue a plan + a completed FaGScraperKS work
    item for that plan, simulating a prior run that already
    ran the strategy+scope combo."""
    plan = QueryPlan(
        plan_id=f"plan-{scope}-{pid}-{work_id_suffix}",
        pensioner_id=pid,
        strategy=strategy,
        scope=PlanScope(scope),
    )
    store.enqueue_plan(plan)
    work = WorkItem(
        work_id=f"work-fag-{plan.plan_id}",
        pensioner_id=pid,
        knowledge_source="FaGScraperKS",
        state=WorkState.SUCCEEDED,
    )
    store.enqueue_work(work)
    # Now mark it completed (the work_items.state row was set
    # to 'succeeded' at enqueue time; that's the contract).
    return plan, work


# ============================================================
# Basic match cases
# ============================================================


def test_plan_already_completed_returns_true_when_match(sqlite_store):
    """A completed plan for (pid, strategy, scope) is detected."""
    _enqueue_completed_plan(
        sqlite_store, pid=327, strategy="B1-exact", scope="OK",
        work_id_suffix="abc",
    )
    assert sqlite_store.plan_already_completed(327, "B1-exact", "OK") is True


def test_plan_already_completed_returns_false_when_no_plan(sqlite_store):
    """Empty store → no plan → no match."""
    assert sqlite_store.plan_already_completed(327, "B1-exact", "OK") is False


def test_plan_already_completed_returns_false_when_different_strategy(
    sqlite_store,
):
    """A completed B1-exact on OK does NOT match a query for B3-fuzzy."""
    _enqueue_completed_plan(
        sqlite_store, pid=327, strategy="B1-exact", scope="OK",
        work_id_suffix="abc",
    )
    assert sqlite_store.plan_already_completed(327, "B3-fuzzy", "OK") is False


def test_plan_already_completed_returns_false_when_different_scope(
    sqlite_store,
):
    """B1-exact on OK does NOT match a query for B1-exact on US."""
    _enqueue_completed_plan(
        sqlite_store, pid=327, strategy="B1-exact", scope="OK",
        work_id_suffix="abc",
    )
    assert sqlite_store.plan_already_completed(327, "B1-exact", "US") is False


def test_plan_already_completed_returns_false_when_different_pensioner(
    sqlite_store,
):
    """B1-exact on OK for pid=327 does NOT match a query for pid=328."""
    _enqueue_completed_plan(
        sqlite_store, pid=327, strategy="B1-exact", scope="OK",
        work_id_suffix="abc",
    )
    assert sqlite_store.plan_already_completed(328, "B1-exact", "OK") is False


# ============================================================
# Work-item state matters
# ============================================================


def test_plan_already_completed_returns_false_when_in_flight(sqlite_store):
    """A plan with a ready/leased work_item is NOT counted as
    completed (the dedup only catches terminal states)."""
    plan = QueryPlan(
        plan_id="plan-OK-327-xyz",
        pensioner_id=327,
        strategy="B1-exact",
        scope=PlanScope.OK,
    )
    sqlite_store.enqueue_plan(plan)
    # Enqueue the work but DON'T mark it completed; the enqueue
    # uses INSERT OR IGNORE so the row exists with default state
    # 'ready'.
    work = WorkItem(
        work_id=f"work-fag-{plan.plan_id}",
        pensioner_id=327,
        knowledge_source="FaGScraperKS",
        state=WorkState.READY,
    )
    sqlite_store.enqueue_work(work)
    assert sqlite_store.plan_already_completed(327, "B1-exact", "OK") is False


def test_plan_already_completed_matches_blocked_state(sqlite_store):
    """A blocked work_item counts as completed (issue #77
    spec: any terminal state)."""
    plan = QueryPlan(
        plan_id="plan-OK-327-blocked",
        pensioner_id=327,
        strategy="B1-exact",
        scope=PlanScope.OK,
    )
    sqlite_store.enqueue_plan(plan)
    work = WorkItem(
        work_id=f"work-fag-{plan.plan_id}",
        pensioner_id=327,
        knowledge_source="FaGScraperKS",
        state=WorkState.BLOCKED,
    )
    sqlite_store.enqueue_work(work)
    assert sqlite_store.plan_already_completed(327, "B1-exact", "OK") is True


def test_plan_already_completed_matches_terminal_state(sqlite_store):
    """A terminal work_item (max_attempts exhausted) also counts."""
    plan = QueryPlan(
        plan_id="plan-OK-327-terminal",
        pensioner_id=327,
        strategy="B1-exact",
        scope=PlanScope.OK,
    )
    sqlite_store.enqueue_plan(plan)
    work = WorkItem(
        work_id=f"work-fag-{plan.plan_id}",
        pensioner_id=327,
        knowledge_source="FaGScraperKS",
        state=WorkState.TERMINAL,
    )
    sqlite_store.enqueue_work(work)
    assert sqlite_store.plan_already_completed(327, "B1-exact", "OK") is True


# ============================================================
# Cross-knowledge-source isolation
# ============================================================


def test_plan_already_completed_ignores_non_fag_work_items(sqlite_store):
    """A completed work_item from a non-FaGScraperKS KS does NOT
    count. The match is scoped to FaGScraperKS only (the
    source that actually issues HTTP requests)."""
    plan = QueryPlan(
        plan_id="plan-OK-327-candidatescorer",
        pensioner_id=327,
        strategy="B1-exact",
        scope=PlanScope.OK,
    )
    sqlite_store.enqueue_plan(plan)
    # Same work_id pattern (work-fag-...) but a different KS.
    # In practice, candidate_scorer uses work-score-... not
    # work-fag-..., so this would never actually match. The
    # test pins the contract: the work_item must be
    # knowledge_source='FaGScraperKS'.
    work = WorkItem(
        work_id=f"work-fag-{plan.plan_id}",  # wrong id pattern for non-FaG
        pensioner_id=327,
        knowledge_source="CandidateScorerKS",
        state=WorkState.SUCCEEDED,
    )
    sqlite_store.enqueue_work(work)
    assert sqlite_store.plan_already_completed(327, "B1-exact", "OK") is False


# ============================================================
# Multiple plans for the same pensioner
# ============================================================


def test_plan_already_completed_with_multiple_plans_per_pensioner(
    sqlite_store,
):
    """A pensioner with multiple completed plans (e.g. B1-exact
    OK + B1-exact US) is correctly distinguished by scope."""
    _enqueue_completed_plan(
        sqlite_store, pid=327, strategy="B1-exact", scope="OK",
        work_id_suffix="a",
    )
    _enqueue_completed_plan(
        sqlite_store, pid=327, strategy="B1-exact", scope="US",
        work_id_suffix="b",
    )

    # B1-exact on OK is complete.
    assert sqlite_store.plan_already_completed(327, "B1-exact", "OK") is True
    # B1-exact on US is also complete.
    assert sqlite_store.plan_already_completed(327, "B1-exact", "US") is True
    # B1-exact on TX (never enqueued) is NOT.
    assert sqlite_store.plan_already_completed(327, "B1-exact", "TX") is False


# ============================================================
# Real G10 verification
# ============================================================


G10_BB_PATH = "data/results/run_2026_07_24_g10_stealth_swap_verification/blackboard.db"


def test_g10_dedup_finds_completed_b1_exact_ok(tmp_path):
    """End-to-end check: against the G10 blackboard.db, the
    B1-exact on OK plans for the 10 G pensioners are all
    marked completed. Re-running the same plans would dedup."""
    import shutil
    from pathlib import Path

    src = Path(G10_BB_PATH)
    if not src.exists():
        import pytest
        pytest.skip("G10 blackboard.db not present")

    # Copy the SQLite store to a tmp dir (read-only access
    # would also work; copy is clearer for tests).
    dst = tmp_path / "bb.db"
    shutil.copy2(src, dst)

    store = SqliteBlackboardStore(dst)
    store.open()
    try:
        # The G10 run did B1-exact on OK for every pensioner.
        # Verify the dedup helper returns True for several.
        for pid in [327, 328, 329, 330, 331, 332, 333, 334, 335, 336]:
            assert store.plan_already_completed(pid, "B1-exact", "OK") is True, (
                f"expected B1-exact OK dedup hit for pensioner {pid}"
            )
    finally:
        store.close()