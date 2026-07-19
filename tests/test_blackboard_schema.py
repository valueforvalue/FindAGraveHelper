"""Tests for scripts/blackboard/schema.py — Phase 2 envelopes."""

import pytest

from scripts.blackboard.schema import (
    Kind,
    Observation,
    RunManifest,
    schema_version,
)


# ============================================================
# Observation tests
# ============================================================


def test_observation_to_dict_has_all_fields():
    """Observation.to_dict() includes every required field."""
    o = Observation(
        observation_id="obs-1",
        pensioner_id=12345,
        kind=Kind.FaGCandidateFetch,
        source="fag_scraper.py",
        source_version="1.0",
        run_id="run-1",
        pass_id="1",
        caused_by="plan-abc",
        recorded_at="2026-07-19T12:00:00Z",
        payload={"memorial_id": "50923719"},
    )
    d = o.to_dict()
    assert d["schema_version"] == schema_version
    assert d["observation_id"] == "obs-1"
    assert d["pensioner_id"] == 12345
    assert d["kind"] == "FaGCandidateFetch"
    assert d["source"] == "fag_scraper.py"
    assert d["source_version"] == "1.0"
    assert d["run_id"] == "run-1"
    assert d["pass_id"] == "1"
    assert d["caused_by"] == "plan-abc"
    assert d["recorded_at"] == "2026-07-19T12:00:00Z"
    assert d["payload"]["memorial_id"] == "50923719"


def test_observation_roundtrip():
    """Observation survives to_dict() → from_dict()."""
    o = Observation(
        observation_id="obs-2",
        pensioner_id=99,
        kind=Kind.BotWallObserved,
        source="fag_browser.py",
        source_version="1",
        run_id="r",
        pass_id="p",
    )
    d = o.to_dict()
    restored = Observation.from_dict(d)
    assert restored.observation_id == o.observation_id
    assert restored.kind == o.kind
    assert restored.pensioner_id == o.pensioner_id


def test_observation_defaults():
    """Observation has sensible defaults for optional fields."""
    o = Observation(
        observation_id="obs-3",
        pensioner_id=1,
        kind=Kind.ParseError,
        source="parser.py",
        source_version="1",
        run_id="r",
        pass_id="p",
    )
    assert o.caused_by is None
    assert o.recorded_at == ""
    assert o.payload == {}


def test_kind_enum_from_string():
    """Kind can be constructed from a string value."""
    assert Kind("FaGCandidateFetch") == Kind.FaGCandidateFetch
    assert Kind("BotWallObserved") == Kind.BotWallObserved


def test_kind_invalid_raises():
    """Unknown kind string raises ValueError."""
    with pytest.raises(ValueError):
        Kind("NonexistentKind")


# ============================================================
# WorkItem tests
# ============================================================


def test_workitem_roundtrip():
    """WorkItem survives to_dict() → from_dict()."""
    from scripts.blackboard.schema import WorkItem, WorkState
    w = WorkItem(
        work_id="w1",
        pensioner_id=123,
        knowledge_source="FaGScraper",
        plan_id="p1",
        state=WorkState.LEASED,
        attempt=1,
        not_before="2026-07-19T12:00:00Z",
        leased_by="proc1",
    )
    d = w.to_dict()
    restored = WorkItem.from_dict(d)
    assert restored.work_id == "w1"
    assert restored.state == WorkState.LEASED
    assert restored.not_before == "2026-07-19T12:00:00Z"


def test_workitem_state_transitions():
    """WorkState enum covers the lifecycle."""
    from scripts.blackboard.schema import WorkState
    # Terminal states
    assert WorkState("succeeded") == WorkState.SUCCEEDED
    assert WorkState("terminal") == WorkState.TERMINAL
    # Non-terminal
    assert WorkState("ready") == WorkState.READY
    assert WorkState("retryable") == WorkState.RETRYABLE


def test_workitem_default_state_is_ready():
    """New WorkItem starts in READY state."""
    from scripts.blackboard.schema import WorkItem
    w = WorkItem(work_id="w2", pensioner_id=1, knowledge_source="Test")
    assert w.state.value == "ready"
    assert w.attempt == 0
