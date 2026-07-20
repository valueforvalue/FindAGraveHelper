"""Tests for scripts/blackboard/scheduler.py — Phase 5 Slice 5.1."""

import json
import uuid

from scripts.blackboard.schema import (
    Kind,
    Observation,
    WorkItem,
    WorkState,
)
from scripts.blackboard.scheduler import BlackboardScheduler, KnowledgeSource
from scripts.blackboard.store import SqliteBlackboardStore


# ============================================================
# Sample Knowledge Source for testing
# ============================================================


class _EchoKS:
    """Test KS that echoes the work_id as an observation."""

    name = "EchoKS"

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "EchoKS"

    def invoke(self, item: WorkItem, store) -> list[Observation]:
        obs = Observation(
            observation_id=f"obs-echo-{uuid.uuid4().hex[:8]}",
            pensioner_id=item.pensioner_id,
            kind=Kind.PensionerImported,
            source="echo",
            source_version="1",
            run_id="test",
            pass_id="1",
            caused_by=item.work_id,
            payload={"echo": item.work_id},
        )
        store.append_observation(obs)
        return [obs]

    def estimated_cost(self, item: WorkItem) -> int:
        return 1


class _FailingKS:
    """Test KS that always raises."""

    name = "FailingKS"

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "FailingKS"

    def invoke(self, item: WorkItem, store) -> list[Observation]:
        raise RuntimeError("simulated failure")

    def estimated_cost(self, item: WorkItem) -> int:
        return 1


class _FailOnceKS(_EchoKS):
    """Fail first attempt, then succeed on scheduler retry."""

    name = "FailOnceKS"

    def __init__(self) -> None:
        self.calls = 0

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == self.name

    def invoke(self, item: WorkItem, store) -> list[Observation]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient failure")
        return super().invoke(item, store)


class _IneligibleKS:
    """Test KS that never claims work."""

    name = "IneligibleKS"

    def eligible(self, item: WorkItem) -> bool:
        return False

    def invoke(self, item: WorkItem, store) -> list[Observation]:
        return []

    def estimated_cost(self, item: WorkItem) -> int:
        return 0


# ============================================================
# Fixtures
# ============================================================


def _store(tmp_path):
    """Create an opened SQLite store."""
    s = SqliteBlackboardStore(tmp_path / "test.db")
    s.open()
    return s


def _work(wid: str, ks: str, pid: int = 1) -> WorkItem:
    return WorkItem(
        work_id=wid,
        pensioner_id=pid,
        knowledge_source=ks,
    )


# ============================================================
# Tests
# ============================================================


def _work_state(store, work_id: str) -> WorkState:
    value = store.con.execute(
        "SELECT state FROM work_items WHERE work_id = ?", (work_id,)
    ).fetchone()[0]
    return WorkState(value)


def test_scheduler_registers_and_runs(tmp_path):
    """Scheduler registers a KS and processes one work item."""
    store = _store(tmp_path)
    scheduler = BlackboardScheduler(store)
    scheduler.register(_EchoKS())

    store.enqueue_work(_work("w1", "EchoKS"))
    processed = scheduler.run(max_iterations=1)

    assert processed == 1
    # Observation should be persisted
    obs_list = store.read_observations_since(None)
    assert len(obs_list) == 1
    assert obs_list[0].payload["echo"] == "w1"

    store.close()


def test_scheduler_no_work_returns_zero(tmp_path):
    """Scheduler returns 0 when no work items exist."""
    store = _store(tmp_path)
    scheduler = BlackboardScheduler(store)
    scheduler.register(_EchoKS())

    processed = scheduler.run()
    assert processed == 0
    store.close()


def test_scheduler_ineligible_marks_blocked(tmp_path):
    """Ineligible KS marks work as blocked."""
    store = _store(tmp_path)
    scheduler = BlackboardScheduler(store)
    scheduler.register(_IneligibleKS())

    store.enqueue_work(_work("w-blocked", "IneligibleKS"))
    scheduler.run(max_iterations=1)

    assert _work_state(store, "w-blocked") == WorkState.BLOCKED
    store.close()


def test_scheduler_failing_defers_retry(tmp_path):
    """Failing KS returns work to READY with retry deadline."""
    store = _store(tmp_path)
    scheduler = BlackboardScheduler(store, max_attempts=2)
    scheduler.register(_FailingKS())

    store.enqueue_work(_work("w-fail", "FailingKS"))
    processed = scheduler.run(max_iterations=1)

    assert processed == 1
    assert _work_state(store, "w-fail") == WorkState.READY
    not_before = store.con.execute(
        "SELECT not_before FROM work_items WHERE work_id = ?", ("w-fail",)
    ).fetchone()[0]
    assert not_before is not None
    store.close()


def test_scheduler_retries_retryable_work(tmp_path):
    """Transient failure returns to READY and succeeds next iteration."""
    store = _store(tmp_path)
    scheduler = BlackboardScheduler(store)
    ks = _FailOnceKS()
    scheduler.register(ks)
    store.enqueue_work(_work("w-retry", ks.name))

    processed = scheduler.run(max_iterations=1)
    store.con.execute(
        "UPDATE work_items SET not_before = NULL WHERE work_id = ?",
        ("w-retry",),
    )
    processed += scheduler.run(max_iterations=1)

    assert processed == 2
    assert ks.calls == 2
    assert _work_state(store, "w-retry") == WorkState.SUCCEEDED
    assert len(store.read_observations_since(None)) == 1
    store.close()


def test_scheduler_stops_retrying_at_attempt_budget(tmp_path):
    """Persistent failure becomes TERMINAL instead of spinning forever."""
    store = _store(tmp_path)
    scheduler = BlackboardScheduler(store, max_attempts=2)
    scheduler.register(_FailingKS())
    store.enqueue_work(_work("w-terminal", "FailingKS"))

    processed = 0
    for _ in range(2):
        processed += scheduler.run(max_iterations=1)
        store.con.execute(
            "UPDATE work_items SET not_before = NULL WHERE work_id = ?",
            ("w-terminal",),
        )

    assert processed == 2
    assert _work_state(store, "w-terminal") == WorkState.TERMINAL
    store.close()


def test_scheduler_multiple_ks_order(tmp_path):
    """Scheduler tries KS in registration order."""
    store = _store(tmp_path)
    scheduler = BlackboardScheduler(store)

    echo = _EchoKS()
    scheduler.register(echo)
    scheduler.register(_FailingKS())

    store.enqueue_work(_work("w-echo", "EchoKS"))
    store.enqueue_work(_work("w-fail", "FailingKS"))

    processed = scheduler.run(max_iterations=2)
    assert processed == 2
    obs_list = store.read_observations_since(None)
    # Echo should have produced one observation
    assert any(o.caused_by == "w-echo" for o in obs_list)
    store.close()
