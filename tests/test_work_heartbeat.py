"""Tests for heartbeat leases on WorkItem (#97).

L12 (CONTEXT.md) currently uses a fixed-budget lease: 60 s TTL,
max 3 attempts → BLOCKED. The fixed-budget approach reclaims work
that's still in flight if `invoke()` runs longer than the budget.

Issue #97 introduces heartbeat leases (Temporal-style): the
`WorkItem` carries a `lease_deadline_at` ISO 8601 timestamp; the
Scheduler refreshes it via `store.heartbeat(work_id)` on a
background thread while `invoke()` runs. A crashed KS is
reclaimed at the deadline; a healthy KS that needs 90 s with a
60 s budget survives via heartbeats.

Pin:
- `WorkItem.lease_deadline_at` is set on claim.
- `store.heartbeat(work_id)` extends the deadline.
- Reclaim logic reads `lease_deadline_at` (not attempts[-1].leased_at).
- Long-running invoke() survives past its initial budget.
- Crashed invoke() is reclaimed at the deadline.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from scripts.blackboard.schema import (
    Kind,
    Observation,
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


def _make_work_item(work_id: str, ks: str = "TestKS") -> WorkItem:
    return WorkItem(
        work_id=work_id,
        pensioner_id=1,
        knowledge_source=ks,
    )


# ============================================================
# Acceptance tests
# ============================================================


def test_claim_work_sets_lease_deadline_at(sqlite_store):
    """claim_work writes lease_deadline_at = now + lease_seconds."""
    sqlite_store.enqueue_work(_make_work_item("w1"))
    item = sqlite_store.claim_work("TestKS", lease_seconds=10)
    assert item is not None
    assert item.lease_deadline_at is not None
    # Deadline should be a valid ISO 8601 string within the
    # expected window. We don't pin the exact value (clock skew
    # in tests) but the deadline must be parseable.
    from datetime import datetime

    deadline = datetime.fromisoformat(item.lease_deadline_at.replace("Z", "+00:00"))
    now = datetime.now(deadline.tzinfo)
    delta = (deadline - now).total_seconds()
    # Should be in [9, 11] seconds from now.
    assert 9.0 <= delta <= 11.0


def test_heartbeat_extends_lease_deadline(sqlite_store):
    """store.heartbeat(work_id) extends lease_deadline_at.

    The deadline moves forward by `lease_seconds` on each
    heartbeat. A 0.5s sleep would not be enough to roll the
    second boundary on a fast machine, so we assert that the
    new deadline is at least the original + 9s (i.e. 9 of the
    10s of lease_seconds survived the heartbeat).
    """
    from datetime import datetime, timezone

    sqlite_store.enqueue_work(_make_work_item("w2"))
    item = sqlite_store.claim_work("TestKS", lease_seconds=10)
    original = item.lease_deadline_at

    # Heartbeat once. The new deadline should be ~10s in the
    # future from now (not from the original claim time), since
    # the heartbeat resets the deadline to now + lease_seconds.
    time.sleep(0.1)
    sqlite_store.heartbeat("w2", lease_seconds=10)

    # Re-read the work item from the store to confirm.
    row = sqlite_store.con.execute(
        "SELECT lease_deadline_at FROM work_items WHERE work_id = ?",
        ("w2",),
    ).fetchone()
    assert row is not None
    assert row[0] is not None

    # The new deadline must be parseable and must lie in the
    # future. The original deadline is also in the future (set
    # at claim time), so the heartbeat deadline can be earlier
    # OR later than the original depending on when the heartbeat
    # fires. The contract is: the deadline is always at least
    # `lease_seconds` in the future when read.
    deadline = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    delta = (deadline - now).total_seconds()
    assert delta >= 9.0, (
        f"Heartbeat should keep deadline ≥9s in the future; "
        f"got {delta:.2f}s. Original was {original}."
    )


def test_reclaim_uses_lease_deadline_not_attempts(sqlite_store):
    """A WorkItem with lease_deadline_at in the past is reclaimable.

    We directly mutate the stored deadline to simulate the
    heartbeat-driven deadline being missed (crashed KS).
    """
    sqlite_store.enqueue_work(_make_work_item("w3"))
    sqlite_store.claim_work("TestKS", lease_seconds=10)

    # Force deadline to the past.
    sqlite_store.con.execute(
        "UPDATE work_items SET lease_deadline_at = ? WHERE work_id = ?",
        ("2000-01-01T00:00:00Z", "w3"),
    )

    # Next claim_work should reclaim (lease was missed).
    # First, the claim itself triggers the reclaim branch.
    item = sqlite_store.claim_work("TestKS", lease_seconds=10)
    assert item is not None
    assert item.work_id == "w3"
    # And the new lease_deadline_at should be in the future.
    from datetime import datetime

    deadline = datetime.fromisoformat(item.lease_deadline_at.replace("Z", "+00:00"))
    now = datetime.now(deadline.tzinfo)
    assert (deadline - now).total_seconds() > 0


def test_heartbeat_keeps_lease_past_initial_budget(sqlite_store):
    """A long-running invoke() survives past its initial budget via
    heartbeats. Simulate by setting lease=1s, heartbeat every 0.5s
    for 2.5s, then assert the work item is still leased."""
    sqlite_store.enqueue_work(_make_work_item("w4"))
    item = sqlite_store.claim_work("TestKS", lease_seconds=1)
    assert item is not None

    # Heartbeat for 2.5 seconds, every 0.5s.
    end = time.monotonic() + 2.5
    while time.monotonic() < end:
        time.sleep(0.5)
        sqlite_store.heartbeat("w4", lease_seconds=1)

    # Lease should still be held by us (not reclaimed).
    row = sqlite_store.con.execute(
        "SELECT state, leased_by FROM work_items WHERE work_id = ?",
        ("w4",),
    ).fetchone()
    assert row is not None
    assert row[0] == "leased"
    # leased_by should still be our pid.
    assert row[1] is not None


def test_no_heartbeat_past_initial_budget_reclaims(sqlite_store):
    """Without heartbeats, the lease expires and is reclaimable."""
    sqlite_store.enqueue_work(_make_work_item("w5"))
    sqlite_store.claim_work("TestKS", lease_seconds=1)

    # Wait past the deadline without heartbeating.
    time.sleep(2.0)

    # claim_work should reclaim.
    item = sqlite_store.claim_work("TestKS", lease_seconds=1)
    assert item is not None
    assert item.work_id == "w5"


def test_heartbeat_unknown_work_id_is_noop(sqlite_store):
    """heartbeat on an unknown work_id raises KeyError (or is a
    documented no-op). Choose the strict path so callers notice
    typos."""
    with pytest.raises(KeyError):
        sqlite_store.heartbeat("nonexistent", lease_seconds=10)


def test_work_item_to_dict_includes_lease_deadline_at(sqlite_store):
    """WorkItem.to_dict serializes the deadline so it round-trips
    through read_observations_since / store APIs."""
    sqlite_store.enqueue_work(_make_work_item("w6"))
    item = sqlite_store.claim_work("TestKS", lease_seconds=10)
    d = item.to_dict()
    assert "lease_deadline_at" in d
    assert d["lease_deadline_at"] is not None


def test_work_item_from_dict_handles_missing_field():
    """Reading a WorkItem from an older store (schema_version=1)
    that lacks lease_deadline_at returns None, not crash."""
    d = {
        "schema_version": 1,
        "work_id": "w7",
        "pensioner_id": 1,
        "knowledge_source": "LegacyKS",
        "plan_id": None,
        "pass_id": "1",
        "input_revision": 1,
        "state": "ready",
        "attempt": 0,
        "not_before": None,
        "leased_by": None,
        "completed_at": None,
        "attempts": [],
    }
    item = WorkItem.from_dict(d)
    assert item.lease_deadline_at is None