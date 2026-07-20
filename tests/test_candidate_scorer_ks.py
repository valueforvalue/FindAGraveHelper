"""Behavior tests for CandidateScorerKS and DeepRefinerKS."""

import pytest

from scripts.blackboard.schema import Kind, Observation, WorkItem
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.knowledge.candidate_scorer import CandidateScorerKS, DeepRefinerKS


@pytest.fixture
def store(tmp_path):
    blackboard = SqliteBlackboardStore(tmp_path / "blackboard.db")
    blackboard.open()
    yield blackboard
    blackboard.close()


def _append(store, *, oid: str, pid: int, kind: Kind, payload: dict) -> None:
    store.append_observation(
        Observation(
            observation_id=oid,
            pensioner_id=pid,
            kind=kind,
            source="test",
            source_version="1",
            run_id="run-test",
            pass_id="1",
            payload=payload,
        )
    )


def test_candidate_scorer_classifies_persisted_candidates(store):
    _append(
        store,
        oid="obs-pensioner",
        pid=7,
        kind=Kind.PensionerImported,
        payload={"first_name": "William", "last_name": "Looney", "death_year": "1932"},
    )
    _append(
        store,
        oid="obs-candidate",
        pid=7,
        kind=Kind.FaGCandidateFetch,
        payload={
            "memorial_id": "50923719",
            "score": 0.95,
            "details": {"death_year": "1932"},
        },
    )
    item = WorkItem(
        work_id="work-score",
        pensioner_id=7,
        knowledge_source="CandidateScorerKS",
    )

    observations = CandidateScorerKS().invoke(item, store)

    assert len(observations) == 1
    decision = observations[0]
    assert decision.kind == Kind.ScoreObserved
    assert decision.caused_by == "work-score"
    assert decision.payload["status"] == "auto_accept"
    assert decision.payload["top_score"] == pytest.approx(0.95)
    persisted = store.read_observations_since(None)
    assert persisted[-1].observation_id == decision.observation_id
    refinement = store.con.execute(
        "SELECT knowledge_source FROM work_items WHERE work_id = ?",
        ("work-refine-7",),
    ).fetchone()
    assert refinement == ("DeepRefinerKS",)


def test_deep_refiner_enqueues_global_plan_for_ambiguous_score(store):
    _append(
        store,
        oid="obs-pensioner-refine",
        pid=7,
        kind=Kind.PensionerImported,
        payload={"first_name": "William", "last_name": "Looney"},
    )
    _append(
        store,
        oid="obs-score",
        pid=7,
        kind=Kind.ScoreObserved,
        payload={"status": "ambiguous", "top_score": 0.6},
    )
    item = WorkItem(
        work_id="work-refine",
        pensioner_id=7,
        knowledge_source="DeepRefinerKS",
    )

    observations = DeepRefinerKS().invoke(item, store)

    assert len(observations) == 1
    plan = observations[0].payload
    assert observations[0].kind == Kind.FaGSearchPlan
    assert observations[0].caused_by == "work-refine"
    assert plan["strategy"] == "C1-cw-context"
    assert plan["scope"] == "Global"
    assert plan["params"]["last_name"] == "Looney"
    plan_row = store.con.execute(
        "SELECT strategy, scope FROM query_plans WHERE plan_id = ?",
        (plan["plan_id"],),
    ).fetchone()
    assert plan_row == ("C1-cw-context", "Global")
    work_row = store.con.execute(
        "SELECT knowledge_source, plan_id FROM work_items WHERE plan_id = ?",
        (plan["plan_id"],),
    ).fetchone()
    assert work_row == ("FaGScraperKS", plan["plan_id"])
    persisted = store.read_observations_since(None)
    assert persisted[-1].observation_id == observations[0].observation_id


def test_deep_refiner_stops_after_auto_accept(store):
    _append(
        store,
        oid="obs-score",
        pid=7,
        kind=Kind.ScoreObserved,
        payload={"status": "auto_accept", "top_score": 0.95},
    )
    item = WorkItem(
        work_id="work-refine",
        pensioner_id=7,
        knowledge_source="DeepRefinerKS",
    )

    observations = DeepRefinerKS().invoke(item, store)

    assert observations == []
    assert store.con.execute("SELECT COUNT(*) FROM query_plans").fetchone()[0] == 0
