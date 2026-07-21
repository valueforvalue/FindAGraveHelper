"""Behavior tests for FaGScraperKS and CGRFetcherKS."""

from contextlib import contextmanager

import pytest

from scripts.blackboard.schema import Kind, PlanScope, QueryPlan, WorkItem
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.knowledge.fag_scraper import CGRFetcherKS, FaGScraperKS


class _RecordingGate:
    def __init__(self) -> None:
        self.kinds: list[str] = []

    @contextmanager
    def acquire(self, kind: str):
        self.kinds.append(kind)
        yield object()


class _RecordingSession:
    """Mock for `BrowserSession` in the engine path (issue #61).

    The Blackboard path routes through `engine.default_search_one`,
    which uses `session.page` for navigation. The mock exposes
    `page` as a sentinel object; the engine constructs URLs from
    ctx but never navigates against the page in tests.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[dict, str | None]] = []
        self.page = object()
        self.auto_relax = False
        self.state_filter = "OK"

    def search(
        self,
        pensioner: dict,
        *,
        state_filter: str | None = None,
        strategy_name: str | None = None,
    ):
        self.calls.append((pensioner, state_filter, strategy_name))
        return [
            {
                "memorial_id": "50923719",
                "slug": "william-looney",
                "name": "William Looney",
                "score": 0.91,
            }
        ], "auto_accept"

    def _try_auto_relax_engine(self, engine, page, ctx, ok_result):
        return ok_result


class _FakeEngine:
    """Mock SearchEngine for the engine path (issue #61).

    The engine flow is wired in scripts/search/engine.py; this
    fake records the SearchContext and returns canned candidates
    so the test asserts behavior without touching the real engine.
    """

    name = "fake"
    base_url = "https://example.com"

    def __init__(self) -> None:
        self.contexts_seen: list = []

    def ordered_ladder(self, ctx):
        return []  # Empty ladder => no strategies fire

    def apply_filters(self, params, ctx):
        return dict(params)

    def build_url(self, params):
        return "https://example.com/?x=1"


@pytest.fixture
def store(tmp_path):
    blackboard = SqliteBlackboardStore(tmp_path / "blackboard.db")
    blackboard.open()
    yield blackboard
    blackboard.close()


def test_fag_scraper_invokes_session_through_gate_and_persists_candidate(store, monkeypatch):
    """Engine path (issue #61): FaGScraperKS routes through the
    SearchEngine's default_search_one with no strategy_name filter.
    Test patches default_search_one to return canned candidates so
    we can assert the persistence + scoping behavior end-to-end.
    """
    plan = QueryPlan(
        plan_id="plan-1",
        pensioner_id=7,
        strategy="B1-exact",
        params={"first_name": "William", "last_name": "Looney"},
        scope=PlanScope.US,
    )
    store.enqueue_plan(plan)
    item = WorkItem(
        work_id="work-1",
        pensioner_id=7,
        knowledge_source="FaGScraperKS",
        plan_id=plan.plan_id,
    )
    gate = _RecordingGate()
    session = _RecordingSession()

    def fake_default_search_one(engine, page, ctx, *, strategy_name=None):
        # Mirrors scripts/search/engine.default_search_one contract.
        return {
            "candidates": [
                {
                    "id": "50923719",
                    "slug": "william-looney",
                    "name": "William Looney",
                    "score": 0.91,
                    "evidence": {},
                    "via_strategy": "B1-exact",
                }
            ],
            "strategies_run": ["B1-exact"],
            "status": "auto_accept",
            "classification": "normal",
            "error": None,
        }

    monkeypatch.setattr(
        "scripts.knowledge.fag_scraper.default_search_one",
        fake_default_search_one,
    )

    observations = FaGScraperKS(
        browser_session=session, gate=gate, engine=_FakeEngine()
    ).invoke(item, store)

    assert gate.kinds == ["search"]
    assert len(observations) == 1
    assert observations[0].kind == Kind.FaGCandidateFetch
    assert observations[0].caused_by == "work-1"
    assert observations[0].payload == {
        "memorial_id": "50923719",
        "id": "50923719",
        "slug": "william-looney",
        "name": "William Looney",
        "score": 0.91,
        "url": "",
        "via_strategy": "B1-exact",
        "via_scope": "US",
        "evidence": {},
    }
    persisted = store.read_observations_since(None)
    assert [obs.observation_id for obs in persisted] == [
        observations[0].observation_id
    ]
    score_work = store.con.execute(
        "SELECT knowledge_source FROM work_items WHERE work_id = ?",
        ("work-score-7-1",),
    ).fetchone()
    assert score_work == ("CandidateScorerKS",)


def test_fag_scraper_persists_empty_search_status(store, monkeypatch):
    """Engine path: empty engine result persists an empty-search
    status observation (issue #61). The payload shape changed
    in the engine path: status is rendered in the empty marker
    observation, and `via_strategy` reflects what the engine
    tried (the plan's strategy as a hint).
    """
    plan = QueryPlan(
        plan_id="plan-empty",
        pensioner_id=7,
        strategy="B1-exact",
        params={"first_name": "Nobody", "last_name": "Missing"},
        scope=PlanScope.OK,
    )
    store.enqueue_plan(plan)
    item = WorkItem(
        work_id="work-empty",
        pensioner_id=7,
        knowledge_source="FaGScraperKS",
        plan_id=plan.plan_id,
    )
    session = _RecordingSession()

    def fake_default_search_one(engine, page, ctx, *, strategy_name=None):
        return {
            "candidates": [],
            "strategies_run": ["B1-exact"],
            "status": "no_results",
            "classification": "normal",
            "error": None,
        }

    monkeypatch.setattr(
        "scripts.knowledge.fag_scraper.default_search_one",
        fake_default_search_one,
    )

    observations = FaGScraperKS(
        browser_session=session, gate=_RecordingGate(), engine=_FakeEngine()
    ).invoke(item, store)

    assert len(observations) == 1
    assert observations[0].payload == {
        "_search_status": "no_results",
        "via_strategy": "B1-exact",
        "via_scope": "OK",
    }


def test_fag_scraper_without_plan_does_not_touch_provider(store):
    item = WorkItem(
        work_id="work-missing-plan",
        pensioner_id=7,
        knowledge_source="FaGScraperKS",
    )
    gate = _RecordingGate()
    session = _RecordingSession()

    observations = FaGScraperKS(browser_session=session, gate=gate).invoke(
        item, store
    )

    assert observations == []
    assert gate.kinds == []
    assert session.calls == []
    assert store.read_observations_since(None) == []


def test_cgr_fetcher_persists_corroboration_observation(store):
    item = WorkItem(
        work_id="work-cgr",
        pensioner_id=7,
        knowledge_source="CGRFetcherKS",
    )

    observations = CGRFetcherKS().invoke(item, store)

    assert len(observations) == 1
    assert observations[0].kind == Kind.CGRCorroboration
    assert observations[0].caused_by == "work-cgr"
    assert observations[0].payload["status"] == "fetched"
    assert len(store.read_observations_since(None)) == 1
