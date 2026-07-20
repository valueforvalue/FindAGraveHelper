"""Tests for scripts/knowledge/regional_planner.py — Phase 6 Slice 6.1."""

from scripts.blackboard.schema import Kind, Observation, WorkItem
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.knowledge.regional_planner import RegionalPlannerKS


def _pensioner(**kwargs) -> dict:
    d = {
        "first_name": "John",
        "last_name": "Smith",
        "regiment": "",
        "birth_year": "",
        "notes": "",
        "burial_state": "",
    }
    d.update(kwargs)
    return d


def test_planner_always_emits_ok_first():
    """OK plan is always first."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(_pensioner(), 1)
    assert len(plans) >= 2  # OK + US at minimum
    assert plans[0].scope.value == "OK"
    assert plans[0].reason == "Project default: Oklahoma-first search."


def test_planner_us_is_last():
    """US-wide fallback is always last."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(_pensioner(), 1)
    assert plans[-1].scope.value == "US"


def test_planner_regiment_state_added():
    """Regiment origin state appears between OK and US."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(
        _pensioner(regiment="5th Alabama Infantry"), 1
    )
    scopes = [p.scope.value for p in plans]
    assert "OK" == scopes[0]
    assert "RegimentOrigin" in scopes
    assert scopes[-1] == "US"


def test_planner_texas_evidence_adds_texas_scope():
    """Texas migration evidence triggers a Texas plan."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(
        _pensioner(notes="Family migrated to Texas after war"), 1
    )
    scopes = [p.scope.value for p in plans]
    assert "Texas" in scopes


def test_planner_no_last_name_returns_empty():
    """Cannot plan without at least a last name."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(
        _pensioner(last_name=""), 1
    )
    assert len(plans) == 0


def test_planner_does_not_duplicate_ok():
    """If regiment state is OK, don't add a duplicate."""
    ks = RegionalPlannerKS()
    plans = ks.plan_for_pensioner(
        _pensioner(regiment="1st Oklahoma Cavalry"), 1
    )
    # Should not have two OK plans
    ok_count = sum(1 for p in plans if p.scope.value == "OK")
    assert ok_count == 1


def test_invoke_persists_plans_and_enqueues_search_and_score_work(tmp_path):
    """Planner output is durable and drives downstream scheduler stages."""
    store = SqliteBlackboardStore(tmp_path / "blackboard.db")
    store.open()
    store.append_observation(
        Observation(
            observation_id="obs-pensioner",
            pensioner_id=7,
            kind=Kind.PensionerImported,
            source="test",
            source_version="1",
            run_id="test",
            pass_id="1",
            payload=_pensioner(),
        )
    )
    item = WorkItem(
        work_id="work-plan-7",
        pensioner_id=7,
        knowledge_source="RegionalPlannerKS",
    )

    observations = RegionalPlannerKS().invoke(item, store)

    persisted_ids = {
        obs.observation_id for obs in store.read_observations_since(None)
    }
    assert {obs.observation_id for obs in observations} <= persisted_ids
    work = store.con.execute(
        "SELECT knowledge_source, COUNT(*) FROM work_items GROUP BY knowledge_source"
    ).fetchall()
    assert dict(work) == {"FaGScraperKS": 2}
    store.close()


def test_invoke_no_fag_mode_persists_plans_without_orphan_work(tmp_path):
    """No-FaG planner records intent but creates no unserviceable work."""
    store = SqliteBlackboardStore(tmp_path / "blackboard.db")
    store.open()
    store.append_observation(
        Observation(
            observation_id="obs-pensioner",
            pensioner_id=7,
            kind=Kind.PensionerImported,
            source="test",
            source_version="1",
            run_id="test",
            pass_id="1",
            payload=_pensioner(),
        )
    )
    item = WorkItem(
        work_id="work-plan-7",
        pensioner_id=7,
        knowledge_source="RegionalPlannerKS",
    )

    observations = RegionalPlannerKS(enable_search=False).invoke(item, store)

    assert len(observations) == 2
    assert store.con.execute("SELECT COUNT(*) FROM query_plans").fetchone()[0] == 2
    assert store.con.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
    store.close()
