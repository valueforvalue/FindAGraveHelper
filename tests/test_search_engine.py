"""Tests for the SearchEngine Protocol (issue #33).

The Protocol is the seam between the unified pipeline and
the engine-specific code (FaG, future Ancestry, etc.). This
test suite pins:

  - The SearchEngine Protocol is structurally satisfiable
    (a FakeSearchEngine with the right methods conforms).
  - engine_supports() returns True for conformant engines.
  - The default search_one flow (in default_search_one)
    iterates the ladder, builds URLs, parses, scores, merges.
  - A FakeSearchEngine can be plugged into the default flow
    end-to-end. The fake records every call so the test
    can assert the protocol surface was used correctly.
  - The runner's blocking classification is respected
    (block → skip subsequent strategies in the run).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search.context import SearchContext
from scripts.search.strategy import FunctionStrategy, as_strategy
from scripts.search.engine import (
    SearchEngine,
    Classification,
    default_search_one,
    engine_supports,
)


# ============================================================
# FakeSearchEngine: a minimal conformant engine
# ============================================================


class FakeSearchEngine:
    """An engine that records every method call and returns
    canned responses. Used to test that callers (the default
    search_one flow, future pipeline code) interact with
    the engine through the right method surface.

    Records:
      - goto_calls: list of (url, kwargs)
      - build_url_calls: list of params
      - parse_calls: list of (url,)
      - score_calls: list of (ctx, candidate)
      - classify_calls: list of ()
      - apply_filters_calls: list of (params, ctx)
      - throttle_calls: list of ()
    """

    name = "fake"
    base_url = "https://fake.example.com/search"

    def __init__(self, ladder=None, *,
                 candidates=None, score=0.5, classification=None,
                 build_url_exc=None, parse_exc=None, score_exc=None):
        # Default ladder: one strategy that always fires
        self.ladder = ladder or [as_strategy(
            "F1", lambda ctx: {"q": ctx.first or ""},
        )]
        # What parse_results_page returns
        self._candidates = candidates or [
            {"id": "1", "name": "Alice", "slug": "alice"},
            {"id": "2", "name": "Bob", "slug": "bob"},
        ]
        self._score = score
        # Optional exceptions for negative tests
        self._build_url_exc = build_url_exc
        self._parse_exc = parse_exc
        self._score_exc = score_exc
        # Default classification: normal
        self._classification = classification or _NormalClassification()
        # Recorded calls
        self.goto_calls = []
        self.build_url_calls = []
        self.parse_calls = []
        self.score_calls = []
        self.classify_calls = []
        self.apply_filters_calls = []
        self.throttle_calls = []

    def build_url(self, params: dict) -> str:
        self.build_url_calls.append(params)
        if self._build_url_exc:
            raise self._build_url_exc
        q = params.get("q", "")
        return f"{self.base_url}?q={q}"

    def parse_results_page(self, page, url: str) -> list[dict]:
        self.parse_calls.append(url)
        if self._parse_exc:
            raise self._parse_exc
        return list(self._candidates)

    def score(self, ctx: SearchContext, candidate: dict) -> tuple[float, dict]:
        self.score_calls.append((ctx, candidate))
        if self._score_exc:
            raise self._score_exc
        return (self._score, {"matched_via": "fake"})

    def classify_response(self, page) -> Classification:
        self.classify_calls.append(page)
        return self._classification

    def apply_filters(self, params: dict, ctx: SearchContext) -> dict:
        self.apply_filters_calls.append((dict(params), ctx))
        return dict(params)

    def throttle_seconds(self) -> float:
        self.throttle_calls.append(())
        return 0.0


class _NormalClassification(Classification):
    @property
    def is_blocking(self) -> bool:
        return False
    @property
    def is_normal(self) -> bool:
        return True
    @property
    def value(self) -> str:
        return "normal"


class _BlockingClassification(Classification):
    @property
    def is_blocking(self) -> bool:
        return True
    @property
    def is_normal(self) -> bool:
        return False
    @property
    def value(self) -> str:
        return "challenge"


class _StubPage:
    """A fake Playwright page. Records goto() calls."""

    def __init__(self, raises_on_goto=None):
        self.goto_calls: list[str] = []
        self.title = "fake page"
        self._raises = raises_on_goto

    def goto(self, url: str, **kwargs):
        self.goto_calls.append(url)
        if self._raises:
            raise self._raises


# ============================================================
# Protocol conformance
# ============================================================
class TestProtocolConformance:
    def test_fake_engine_conforms(self):
        e = FakeSearchEngine()
        assert engine_supports(e)

    def test_partial_engine_does_not_conform(self):
        # An object missing some methods is not a SearchEngine.
        class Partial:
            name = "p"
            base_url = "x"

            def build_url(self, params):
                return "x"
        # Missing: parse_results_page, score, etc. The runtime
        # check via runtime_checkable DOES enforce all the
        # protocol's methods, so this fails.
        p = Partial()
        assert not engine_supports(p)

    def test_engine_supports_recognises_class_instances(self):
        e = FakeSearchEngine()
        assert isinstance(e, SearchEngine)


# ============================================================
# default_search_one: end-to-end with the fake
# ============================================================
class TestDefaultSearchOne:
    def test_runs_one_strategy_and_returns_merged_candidates(self):
        e = FakeSearchEngine()
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        result = default_search_one(e, page, ctx)
        # The default ladder has 1 strategy; the engine should
        # have been called once per engine method
        assert len(e.build_url_calls) == 1
        assert len(e.parse_calls) == 1
        # 2 candidates × 1 score call each
        assert len(e.score_calls) == 2
        # Merged: 2 distinct candidates
        assert len(result["candidates"]) == 2
        # Best has the higher score (both equal here, so any)
        assert result["best"] is not None
        # Strategies run
        assert result["strategies_run"] == ["F1"]

    def test_strategy_name_filter_only_runs_named_strategy(self):
        e = FakeSearchEngine(ladder=[
            as_strategy("A1", lambda ctx: {"q": "a"} if ctx.first else None),
            as_strategy("A2", lambda ctx: {"q": "b"} if ctx.last else None),
        ])
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        result = default_search_one(e, page, ctx, strategy_name="A2")
        assert result["strategies_run"] == ["A2"]
        assert len(e.build_url_calls) == 1

    def test_unknown_strategy_name_raises(self):
        e = FakeSearchEngine()
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        with pytest.raises(ValueError, match="Unknown"):
            default_search_one(e, page, ctx, strategy_name="NOPE")

    def test_blocking_classification_skips_strategy(self):
        # When classify returns a blocking response, the runner
        # should NOT call parse_results_page for that strategy
        # and should continue to subsequent strategies.
        e = FakeSearchEngine(classification=_BlockingClassification())
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        result = default_search_one(e, page, ctx)
        # The runner still navigated and classified
        assert len(e.classify_calls) >= 1
        # But did NOT call parse (because classification blocked)
        assert e.parse_calls == []
        # And the candidates list is empty
        assert result["candidates"] == []
        assert result["best"] is None

    def test_build_url_exception_does_not_take_down_run(self):
        e = FakeSearchEngine(build_url_exc=RuntimeError("boom"))
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        # Should not raise; the strategy is skipped.
        result = default_search_one(e, page, ctx)
        assert result["candidates"] == []
        assert "boom" in (result["error"] or "")

    def test_score_exception_records_error_in_evidence(self):
        e = FakeSearchEngine(score_exc=RuntimeError("scorer broken"))
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        result = default_search_one(e, page, ctx)
        # Parsing succeeded; scoring failed
        assert len(result["candidates"]) == 2
        for c in result["candidates"]:
            assert c["score"] == 0.0
            assert "scorer broken" in c["score_evidence"]["error"]

    def test_merge_keeps_highest_score_per_id(self):
        e = FakeSearchEngine(candidates=[
            {"id": "1", "name": "Alice"},
            {"id": "1", "name": "Alice dup"},
            {"id": "2", "name": "Bob"},
        ], score=0.7)
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        result = default_search_one(e, page, ctx)
        ids = [c["id"] for c in result["candidates"]]
        assert sorted(ids) == ["1", "2"]
        # Id "1" was seen twice; the merged entry should have
        # one of them (whichever, both have score 0.7)

    def test_empty_ladder_returns_empty_result(self):
        e = FakeSearchEngine()
        e.ladder = []  # override the default one-strategy ladder
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        result = default_search_one(e, page, ctx)
        assert result["candidates"] == []
        assert result["best"] is None
        assert result["strategies_run"] == []


# ============================================================
# Engine methods called with right arguments
# ============================================================
class TestEngineMethodCalls:
    def test_apply_filters_receives_params_and_ctx(self):
        e = FakeSearchEngine()
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith", state="OK")
        default_search_one(e, page, ctx)
        assert len(e.apply_filters_calls) == 1
        passed_params, passed_ctx = e.apply_filters_calls[0]
        # The strategy put {"q": "Alice"} into params
        assert passed_params == {"q": "Alice"}
        # The ctx is the same one we passed
        assert passed_ctx is ctx

    def test_build_url_called_with_filtered_params(self):
        e = FakeSearchEngine()
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        default_search_one(e, page, ctx)
        # apply_filters returned dict(params) (no change)
        # so build_url received the strategy's params
        assert e.build_url_calls == [{"q": "Alice"}]

    def test_parse_called_with_navigated_url(self):
        e = FakeSearchEngine()
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        default_search_one(e, page, ctx)
        # build_url returns the URL; the page navigated there;
        # parse was called with that URL
        assert e.parse_calls == ["https://fake.example.com/search?q=Alice"]

    def test_score_called_for_each_candidate(self):
        e = FakeSearchEngine(candidates=[
            {"id": "1"}, {"id": "2"}, {"id": "3"},
        ])
        page = _StubPage()
        ctx = SearchContext(first="Alice", last="Smith")
        default_search_one(e, page, ctx)
        assert len(e.score_calls) == 3
        # Each call gets the same ctx
        for passed_ctx, cand in e.score_calls:
            assert passed_ctx is ctx
            assert "id" in cand


# ============================================================
# Classification base class
# ============================================================
class TestClassification:
    def test_default_is_normal(self):
        c = Classification()
        assert c.is_normal is True
        assert c.is_blocking is False
        assert c.value == "unknown"

    def test_subclass_overrides(self):
        c = _BlockingClassification()
        assert c.is_blocking is True
        assert c.is_normal is False
        assert c.value == "challenge"
