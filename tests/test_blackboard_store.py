"""Tests for scripts/blackboard/store.py — Phase 2 Slice 2.4."""

import time

import pytest

from scripts.blackboard.schema import (
    Kind,
    Observation,
    WorkItem,
    WorkState,
)
from scripts.blackboard.store import (
    JsonlBlackboardStore,
    SqliteBlackboardStore,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def sqlite_store(tmp_path):
    """Open a SQLite store in a temp directory."""
    store = SqliteBlackboardStore(tmp_path / "blackboard.db")
    store.open()
    yield store
    store.close()


def _obs(oid: str, pid: int = 1, kind: Kind = Kind.FaGCandidateFetch,
         payload: dict | None = None) -> Observation:
    return Observation(
        observation_id=oid,
        pensioner_id=pid,
        kind=kind,
        source="test",
        source_version="1",
        run_id="run-test",
        pass_id="1",
        payload=payload or {},
    )


def _work(wid: str, pid: int = 1, ks: str = "FaGScraper",
          state: WorkState = WorkState.READY) -> WorkItem:
    return WorkItem(
        work_id=wid,
        pensioner_id=pid,
        knowledge_source=ks,
        state=state,
    )


# ============================================================
# SQLite store tests
# ============================================================


def test_append_and_read_observation(sqlite_store):
    """Append an observation, then read it back."""
    obs = _obs("obs-1", pid=42, payload={"memorial_id": "123"})
    sqlite_store.append_observation(obs)

    results = sqlite_store.read_observations_since(None)
    assert len(results) == 1
    assert results[0].observation_id == "obs-1"
    assert results[0].pensioner_id == 42
    assert results[0].payload["memorial_id"] == "123"


def test_read_since_cursor(sqlite_store):
    """read_observations_since filters by recorded_at."""
    obs1 = _obs("obs-1")
    obs1.recorded_at = "2026-01-01T00:00:00Z"
    sqlite_store.append_observation(obs1)

    time.sleep(0.1)
    obs2 = _obs("obs-2")
    sqlite_store.append_observation(obs2)

    results = sqlite_store.read_observations_since("2026-01-01T12:00:00Z")
    assert len(results) == 1
    assert results[0].observation_id == "obs-2"


def test_enqueue_and_claim_work(sqlite_store):
    """Enqueue work, claim it, verify state transitions."""
    item = _work("w1")
    sqlite_store.enqueue_work(item)

    claimed = sqlite_store.claim_work("FaGScraper")
    assert claimed is not None
    assert claimed.work_id == "w1"
    assert claimed.state == WorkState.LEASED
    assert claimed.attempt == 1


def test_claim_work_returns_none_when_none_ready(sqlite_store):
    """claim_work returns None when no ready items exist."""
    claimed = sqlite_store.claim_work("FaGScraper")
    assert claimed is None


def test_claim_work_honors_not_before(sqlite_store):
    """Work items with future not_before are not claimed."""
    future = "2099-01-01T00:00:00Z"
    item = _work("w-future")
    item.not_before = future
    sqlite_store.enqueue_work(item)

    claimed = sqlite_store.claim_work("FaGScraper")
    assert claimed is None


def test_complete_work_marks_terminal(sqlite_store):
    """complete_work transitions state and records completed_at."""
    item = _work("w-done")
    sqlite_store.enqueue_work(item)
    sqlite_store.claim_work("FaGScraper")
    sqlite_store.complete_work("w-done", WorkState.SUCCEEDED)

    # Cannot re-claim completed work
    claimed = sqlite_store.claim_work("FaGScraper")
    assert claimed is None


def test_provider_cooldown(sqlite_store):
    """set_provider_not_before persists and is retrievable."""
    until = "2099-01-01T00:00:00Z"
    sqlite_store.set_provider_not_before("findagrave.com", until)

    result = sqlite_store.get_provider_not_before("findagrave.com")
    assert result == until

    unknown = sqlite_store.get_provider_not_before("other.com")
    assert unknown is None


# ============================================================
# JSONL fallback tests
# ============================================================


def test_jsonl_append_observation(tmp_path):
    """JsonlBlackboardStore appends observation to file."""
    store = JsonlBlackboardStore(tmp_path / "fallback.jsonl")
    obs = _obs("obs-j1", pid=7)
    store.append_observation(obs)

    assert (tmp_path / "fallback.jsonl").exists()
    content = (tmp_path / "fallback.jsonl").read_text()
    assert "obs-j1" in content


def test_jsonl_claim_work_returns_none():
    """JsonlBlackboardStore does not support work claiming."""
    store = JsonlBlackboardStore("/tmp/test.jsonl")
    assert store.claim_work("test") is None
