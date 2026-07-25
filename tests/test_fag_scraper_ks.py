"""Behavior tests for FaGScraperKS."""

from contextlib import contextmanager

import pytest

from scripts.blackboard.schema import Kind, PlanScope, QueryPlan, WorkItem
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.knowledge.fag_scraper import FaGScraperKS


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

    def fake_default_search_one(engine, page, ctx, *, strategy_name=None, throttle_fn=None):
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
        # Issue #104: details + name-fallback fields are now in the
        # row payload. Empty when neither the parser nor the name
        # string provided them.
        "attributes": {},
        "details": {},
        "birth_year": None,
        "death_year": None,
        "cemetery_name": None,
        "candidate_state": None,
        "is_veteran": False,
        "backlink": "",
        "iiif_url": "",
        "is_caption_noise": False,
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

    def fake_default_search_one(engine, page, ctx, *, strategy_name=None, throttle_fn=None):
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


# ------------------------------------------------------------
# Issue #104: scraper drops candidate details, capping score
# ------------------------------------------------------------


def _make_engine_returning(candidates: list[dict]):
    """Build a fake default_search_one that returns the given candidates."""

    def fake_default_search_one(engine, page, ctx, *, strategy_name=None, throttle_fn=None):
        return {
            "candidates": candidates,
            "strategies_run": ["B1-exact"],
            "status": "ok",
            "classification": "normal",
            "error": None,
        }

    return fake_default_search_one


def test_fag_scraper_pipes_details_through_to_row(store, monkeypatch):
    """Issue #104: each row payload must carry the engine's `details`
    dict (birth_year, death_year, cemetery_name, state, is_veteran)
    so projection, review UI, and downstream re-scoring can use
    the date/state features the engine already scored against.
    """
    plan = QueryPlan(
        plan_id="plan-details",
        pensioner_id=99,
        strategy="B1-exact",
        params={"first_name": "William", "last_name": "Glover"},
        scope=PlanScope.OK,
    )
    store.enqueue_plan(plan)
    item = WorkItem(
        work_id="work-details",
        pensioner_id=99,
        knowledge_source="FaGScraperKS",
        plan_id=plan.plan_id,
    )

    candidate = {
        "id": "120917435",
        "slug": "william-h-glover",
        "name": "William H Glover 13 Nov 1853 - 20 Sep 1936",
        "score": 0.85,
        "evidence": {"last": 1.0, "first": 1.0, "middle": 0.5, "death": 0.4,
                     "veteran": 0.8, "state": 0.1, "ok_burial": 0.3},
        "via_strategy": "B1-exact",
        "backlink": "https://www.findagrave.com/memorial/120917435/",
        "details": {
            "birth_year": "1853",
            "death_year": "1936",
            "cemetery_name": "IOOF Cemetery",
            "state": "OK",
            "is_veteran": True,
        },
    }
    monkeypatch.setattr(
        "scripts.knowledge.fag_scraper.default_search_one",
        _make_engine_returning([candidate]),
    )

    observations = FaGScraperKS(
        browser_session=_RecordingSession(),
        gate=_RecordingGate(),
        engine=_FakeEngine(),
    ).invoke(item, store)

    assert len(observations) == 1
    payload = observations[0].payload
    assert payload["memorial_id"] == "120917435"
    # Issue #104: details must survive row construction.
    assert payload["details"] == candidate["details"]
    assert payload["birth_year"] == "1853"
    assert payload["death_year"] == "1936"
    assert payload["cemetery_name"] == "IOOF Cemetery"
    assert payload["is_veteran"] is True


def test_fag_scraper_falls_back_to_name_date_extraction(store, monkeypatch):
    """Issue #104: when `details.death_year` is empty but the
    candidate `name` contains a date range (e.g. "1853 - 1936"),
    the row must still expose `death_year` for downstream scoring.
    """
    plan = QueryPlan(
        plan_id="plan-name-fallback",
        pensioner_id=100,
        strategy="B1-exact",
        params={"first_name": "William", "last_name": "Glover"},
        scope=PlanScope.OK,
    )
    store.enqueue_plan(plan)
    item = WorkItem(
        work_id="work-name-fallback",
        pensioner_id=100,
        knowledge_source="FaGScraperKS",
        plan_id=plan.plan_id,
    )

    candidate = {
        "id": "120917436",
        "slug": "william-h-glover-2",
        "name": "William H Glover 13 Nov 1853 - 20 Sep 1936",
        "score": 0.5,
        "evidence": {},
        "via_strategy": "B1-exact",
        "details": {},  # parser missed dates; name has them
    }
    monkeypatch.setattr(
        "scripts.knowledge.fag_scraper.default_search_one",
        _make_engine_returning([candidate]),
    )

    observations = FaGScraperKS(
        browser_session=_RecordingSession(),
        gate=_RecordingGate(),
        engine=_FakeEngine(),
    ).invoke(item, store)

    assert len(observations) == 1
    payload = observations[0].payload
    assert payload["death_year"] == "1936"
    assert payload["birth_year"] == "1853"


def test_fag_scraper_filters_caption_noise_candidates(store, monkeypatch):
    """Issue #104: photo-caption noise ("HONORING ...", "IN MEMORY OF ...")
    should not be persisted as FaGCandidateFetch observations, so they
    cannot rank above real candidates with non-zero score.
    """
    plan = QueryPlan(
        plan_id="plan-noise",
        pensioner_id=101,
        strategy="B1-exact",
        params={"first_name": "William", "last_name": "Glover"},
        scope=PlanScope.OK,
    )
    store.enqueue_plan(plan)
    item = WorkItem(
        work_id="work-noise",
        pensioner_id=101,
        knowledge_source="FaGScraperKS",
        plan_id=plan.plan_id,
    )

    candidates = [
        # caption noise (score 0 from parser; name matches "HONORING")
        {
            "id": "cap1", "name": "HONORING Permelia Malcom BIRTH 1845 DEATH 1935",
            "score": 0.0, "evidence": {}, "via_strategy": "B1-exact",
        },
        # real candidate
        {
            "id": "real1", "name": "William H Glover 1853-1936",
            "score": 0.4, "evidence": {}, "via_strategy": "B1-exact",
        },
        # more caption noise
        {
            "id": "cap2", "name": "IN MEMORY OF Otto Wiese 1902-1997",
            "score": 0.0, "evidence": {}, "via_strategy": "B1-exact",
        },
    ]
    monkeypatch.setattr(
        "scripts.knowledge.fag_scraper.default_search_one",
        _make_engine_returning(candidates),
    )

    observations = FaGScraperKS(
        browser_session=_RecordingSession(),
        gate=_RecordingGate(),
        engine=_FakeEngine(),
    ).invoke(item, store)

    persisted_ids = {obs.payload["memorial_id"] for obs in observations}
    assert "cap1" not in persisted_ids
    assert "cap2" not in persisted_ids
    assert "real1" in persisted_ids
