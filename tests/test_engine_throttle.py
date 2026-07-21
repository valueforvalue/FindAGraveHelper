"""Tests for issue #61 close: per-strategy throttle in engine flow.

The engine path was burning the throttle budget by firing
multiple navigations back-to-back with no inter-strategy
delay. Fix: thread a throttle_fn through default_search_one
and have the engine call it before every page.goto. RequestGate
provides the `wait()` method that enforces min_interval without
acquiring a fresh token (so per-strategy waits stack with the
per-pensioner outer acquire).
"""

from __future__ import annotations

import time

import pytest

from scripts.fag.request_gate import RequestGate


# ============================================================
# RequestGate: per-strategy wait() stacks with acquire()
# ============================================================


def test_request_gate_wait_enforces_min_interval():
    """Two back-to-back wait() calls must enforce min_interval."""
    gate = RequestGate(provider="findagrave.com", min_interval=0.1)
    t0 = time.monotonic()
    gate.wait("test")
    t1 = time.monotonic()
    gate.wait("test")
    t2 = time.monotonic()
    # First wait: 0s. Second wait: >= 0.1s.
    assert t2 - t1 >= 0.09, (
        f"second wait fired too early: gap={t2 - t1:.3f}s (min_interval=0.1)"
    )


def test_request_gate_wait_stacks_with_acquire():
    """`wait()` enforces the same min_interval as `acquire()`. A
    sequence of acquire / wait / acquire must serialize them all.
    """
    gate = RequestGate(provider="findagrave.com", min_interval=0.1)
    # Prime the gate with an acquire (so subsequent ones must wait).
    with gate.acquire("prime"):
        pass
    t0 = time.monotonic()
    with gate.acquire("first"):
        pass
    t1 = time.monotonic()
    gate.wait("middle")
    t2 = time.monotonic()
    with gate.acquire("last"):
        pass
    t3 = time.monotonic()
    # All three intervals >= min_interval (allow a small float fuzz).
    assert t1 - t0 >= 0.09
    assert t2 - t1 >= 0.09
    assert t3 - t2 >= 0.09


def test_request_gate_wait_noop_when_already_cooled():
    """If the gate is already cool, `wait()` returns immediately."""
    gate = RequestGate(provider="findagrave.com", min_interval=0.1)
    time.sleep(0.15)  # Let the gate cool
    t0 = time.monotonic()
    gate.wait("test")
    t1 = time.monotonic()
    # Should be ~0s; allow generous tolerance for scheduling.
    assert t1 - t0 < 0.05


# ============================================================
# default_search_one: per-strategy throttle_fn contract
# ============================================================


def test_default_search_one_calls_throttle_fn_per_strategy():
    """The engine must invoke `throttle_fn()` BEFORE every
    page.goto. This is the fix for the 1015 burst the smoke
    exposed — engine path was firing 5-13 navigations inside
    the L1 floor.
    """
    from scripts.search.engine import default_search_one
    from scripts.search.context import SearchContext

    # Minimal SearchEngine stub: 3 strategies, each navigates.
    class _StubEngine:
        name = "stub"
        base_url = "https://example.com"

        def ordered_ladder(self, ctx):
            return self.ladder

        def apply_filters(self, params, ctx):
            return dict(params)

        def build_url(self, params):
            return f"https://example.com/?q={params.get('q', '')}"

        def classify_response(self, page):
            from scripts.search.engine import Classification
            return Classification()

        def parse_results_page(self, page, url):
            return [{"id": "1", "name": "x"}]

        def score(self, ctx, candidate):
            return 0.5, {}

        ladder = []  # filled in per-test

    class _StubPage:
        def __init__(self):
            self.goto_count = 0

        def goto(self, url, **kwargs):
            self.goto_count += 1
            return None

    engine = _StubEngine()
    from scripts.search.strategy import FunctionStrategy

    def _strat_fn(name):
        def fn(ctx):
            return {"q": name}
        return fn

    engine.ladder = [
        FunctionStrategy("S1", _strat_fn("s1")),
        FunctionStrategy("S2", _strat_fn("s2")),
        FunctionStrategy("S3", _strat_fn("s3")),
    ]

    page = _StubPage()
    ctx = SearchContext(first="John", last="Smith")
    throttle_calls: list[str] = []

    def throttle_fn():
        throttle_calls.append("tick")

    result = default_search_one(
        engine, page=page, ctx=ctx, throttle_fn=throttle_fn
    )

    # Engine navigated 3 times → 3 navigations, each preceded
    # by a throttle tick.
    assert page.goto_count == 3
    assert throttle_calls == ["tick", "tick", "tick"], (
        f"throttle not called per strategy: {throttle_calls}"
    )
    # Strategies were all attempted (strategies_run records names).
    assert result["strategies_run"] == ["S1", "S2", "S3"]


def test_default_search_one_no_throttle_fn_is_burst_mode():
    """If the caller doesn't supply a throttle_fn, the engine
    fires in burst (the behavior the smoke exposed). Pin it
    so callers can't accidentally regress.
    """
    from scripts.search.engine import default_search_one
    from scripts.search.context import SearchContext

    class _StubEngine:
        name = "stub"
        base_url = "https://example.com"

        def ordered_ladder(self, ctx):
            return self.ladder

        def apply_filters(self, params, ctx):
            return dict(params)

        def build_url(self, params):
            return "https://example.com/?x=1"

        def classify_response(self, page):
            from scripts.search.engine import Classification
            return Classification()

        def parse_results_page(self, page, url):
            return []

        def score(self, ctx, candidate):
            return 0.0, {}

        ladder = []

    from scripts.search.strategy import FunctionStrategy

    engine = _StubEngine()
    engine.ladder = [
        FunctionStrategy("S1", lambda ctx: {"q": "s1"}),
        FunctionStrategy("S2", lambda ctx: {"q": "s2"}),
    ]

    class _StubPage:
        def __init__(self):
            self.goto_count = 0

        def goto(self, url, **kwargs):
            self.goto_count += 1
            return None

    page = _StubPage()
    ctx = SearchContext(first="John", last="Smith")

    # No throttle_fn supplied → burst mode (documented behavior).
    result = default_search_one(engine, page=page, ctx=ctx)
    assert page.goto_count == 2


# ============================================================
# FaGScraperKS: throttle_fn is wired through to the engine
# ============================================================


def test_fag_scraper_ks_constructs_gate_with_provided_min_interval():
    """The gate passed to FaGScraperKS must reflect the
    config-supplied min_interval. When the operator sets
    `--allow-low-throttle` (1.5s), the gate drops to 1.5s too —
    issue #61's "no magic numbers" requirement.
    """
    from scripts.fag.request_gate import RequestGate
    from scripts.knowledge.fag_scraper import FaGScraperKS

    # The default gate should be 2.5s (L1 floor).
    ks1 = FaGScraperKS(browser_session=None, gate_min_interval=2.5)
    assert ks1._gate.min_interval == 2.5

    # Operator opt-in: 1.5s.
    ks2 = FaGScraperKS(browser_session=None, gate_min_interval=1.5)
    assert ks2._gate.min_interval == 1.5