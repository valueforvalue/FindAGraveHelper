"""Tests for SearchContext + run_ladder (refactor 2026-07-20).

The new search layer is:
  - SearchContext (frozen dataclass with first/middle/last/years/
    state/extras)
  - Strategy protocol
  - run_ladder() helper with mode='first' (default) and mode='all'
  - FunctionStrategy wrapper

Tests pin:
  - SearchContext construction + has() guard + extras access
  - from_pensioner() maps pensioner-style dicts correctly
  - run_ladder() mode='first' returns first applicable strategy
  - run_ladder() mode='all' returns every applicable strategy
  - run_ladder() catches exceptions in strategies (one bad
    strategy MUST NOT take down the whole ladder)
  - FunctionStrategy is a Strategy (Protocol conformance)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.search.context import SearchContext, from_pensioner
from scripts.search.strategy import (
    Strategy,
    FunctionStrategy,
    as_strategy,
)
from scripts.search.ladder import run_ladder


# Test sentinels (module-level so the helper can reference them)
_SENTINEL = object()
_RAISE = object()


# ============================================================
# SearchContext basics
# ============================================================
class TestSearchContext:
    def test_minimal_construction(self):
        ctx = SearchContext(first="John", last="Smith")
        assert ctx.first == "John"
        assert ctx.last == "Smith"
        assert ctx.middle == ""
        assert ctx.birth_year == ""
        assert ctx.death_year == ""
        assert ctx.state == ""
        assert dict(ctx.extras) == {}

    def test_full_construction(self):
        ctx = SearchContext(
            first="John", middle="Q", last="Smith",
            birth_year="1844", death_year="1920",
            state="OK", extras={"regiment": "CSA", "unit": "1st TX"},
        )
        assert ctx.birth_year == "1844"
        assert ctx.death_year == "1920"
        assert ctx.state == "OK"
        assert ctx.extra("regiment") == "CSA"
        assert ctx.extra("missing", "default") == "default"

    def test_is_frozen(self):
        ctx = SearchContext(first="John", last="Smith")
        with pytest.raises(Exception):  # FrozenInstanceError subclass
            ctx.first = "Jane"

    def test_has_guard(self):
        ctx = SearchContext(first="John", last="Smith")
        assert ctx.has("first", "last") is True
        assert ctx.has("first", "middle") is False
        assert ctx.has("middle") is False
        assert ctx.has("nonsense") is False  # missing attr is falsy

    def test_extra_returns_default(self):
        ctx = SearchContext(first="John", last="Smith")
        assert ctx.extra("regiment") == ""
        assert ctx.extra("regiment", default="CSA") == "CSA"


# ============================================================
# from_pensioner
# ============================================================
class TestFromPensioner:
    def test_canonical_keys(self):
        ctx = from_pensioner({
            "pensioner_first": "Margaret",
            "pensioner_middle": "Ward",
            "pensioner_last": "Slemp",
            "pensioner_birth_year": "1845",
            "pensioner_death_year": "1925",
            "fag_state_filter": "OK",
            "regiment": "CSA",
        })
        assert ctx.first == "Margaret"
        assert ctx.middle == "Ward"
        assert ctx.last == "Slemp"
        assert ctx.birth_year == "1845"
        assert ctx.death_year == "1925"
        assert ctx.state == "OK"
        assert ctx.extra("regiment") == "CSA"

    def test_unprefixed_keys(self):
        ctx = from_pensioner({
            "first_name": "John",
            "last_name": "Smith",
            "birth_year": "1844",
        })
        assert ctx.first == "John"
        assert ctx.last == "Smith"
        assert ctx.birth_year == "1844"

    def test_empty_dict(self):
        ctx = from_pensioner({})
        assert ctx.first == ""
        assert ctx.last == ""
        assert dict(ctx.extras) == {}

    def test_unknown_keys_go_to_extras(self):
        ctx = from_pensioner({
            "first_name": "John",
            "last_name": "Smith",
            "cemetery_id": 123,
            "maiden_name": "Jones",
            "notes": "ACW veteran",
        })
        assert ctx.extra("cemetery_id") == 123
        assert ctx.extra("maiden_name") == "Jones"
        assert ctx.extra("notes") == "ACW veteran"

    def test_strips_whitespace(self):
        ctx = from_pensioner({
            "first_name": "  John  ",
            "last_name": " Smith ",
        })
        assert ctx.first == "John"
        assert ctx.last == "Smith"


# ============================================================
# FunctionStrategy + Protocol
# ============================================================
class TestFunctionStrategy:
    def test_conforms_to_protocol(self):
        def my_fn(ctx):
            return {"x": 1}
        s = FunctionStrategy("test", my_fn)
        assert isinstance(s, Strategy)  # runtime_checkable

    def test_name_passes_through(self):
        s = FunctionStrategy("B1", lambda ctx: None)
        assert s.name == "B1"

    def test_params_calls_fn(self):
        called_with = []

        def my_fn(ctx):
            called_with.append(ctx)
            return {"k": ctx.first}
        s = FunctionStrategy("t", my_fn)
        ctx = SearchContext(first="John", last="Smith")
        assert s.params(ctx) == {"k": "John"}
        assert called_with == [ctx]

    def test_as_strategy_helper(self):
        s = as_strategy("hello", lambda ctx: {"a": 1})
        assert s.name == "hello"
        assert isinstance(s, Strategy)


# ============================================================
# run_ladder
# ============================================================
class TestRunLadder:
    @staticmethod
    def _make_ladder(*strategies):
        """Build a ladder from (name, return_value) tuples.

        Use _RAISE as the return value to make that strategy
        raise RuntimeError when called.
        """
        ladder = []
        for name, ret in strategies:
            if ret is _RAISE:
                def fn(ctx, _e=RuntimeError("boom")):
                    raise _e
            else:
                def fn(ctx, r=ret):
                    return r
            ladder.append(FunctionStrategy(name, fn))
        return ladder

    def test_first_mode_picks_first_applicable(self):
        ladder = self._make_ladder(
            ("B1", {"k": 1}),
            ("B2", {"k": 2}),
            ("B3", {"k": 3}),
        )
        ctx = SearchContext(first="John", last="Smith")
        name, params = run_ladder(ladder, ctx, mode="first")
        assert name == "B1"
        assert params == {"k": 1}

    def test_first_mode_skips_None(self):
        ladder = self._make_ladder(
            ("B1", None),
            ("B2", {"k": 2}),
            ("B3", {"k": 3}),
        )
        ctx = SearchContext(first="John", last="Smith")
        name, params = run_ladder(ladder, ctx, mode="first")
        assert name == "B2"
        assert params == {"k": 2}

    def test_first_mode_returns_none_tuple_when_no_match(self):
        ladder = self._make_ladder(
            ("B1", None),
            ("B2", None),
        )
        ctx = SearchContext(first="John", last="Smith")
        name, params = run_ladder(ladder, ctx, mode="first")
        assert name is None
        assert params is None

    def test_all_mode_returns_every_applicable(self):
        ladder = self._make_ladder(
            ("B1", {"k": 1}),
            ("B2", None),
            ("B3", {"k": 3}),
            ("B4", {"k": 4}),
        )
        ctx = SearchContext(first="John", last="Smith")
        results = run_ladder(ladder, ctx, mode="all")
        assert results == [
            ("B1", {"k": 1}),
            ("B3", {"k": 3}),
            ("B4", {"k": 4}),
        ]

    def test_all_mode_empty_when_none_apply(self):
        ladder = self._make_ladder(
            ("B1", None),
            ("B2", None),
        )
        ctx = SearchContext(first="John", last="Smith")
        results = run_ladder(ladder, ctx, mode="all")
        assert results == []

    def test_exception_in_one_strategy_doesnt_kill_ladder(self):
        # The raise strategy crashes; subsequent ones should still
        # be tried. (Failure is treated as 'not applicable'.)
        ladder = self._make_ladder(
            ("BAD", _RAISE),
            ("OK", {"k": 1}),
        )
        ctx = SearchContext(first="John", last="Smith")
        name, params = run_ladder(ladder, ctx, mode="first")
        assert name == "OK"
        assert params == {"k": 1}

    def test_unknown_mode_raises(self):
        ladder = self._make_ladder(("B1", {"k": 1}))
        ctx = SearchContext(first="John", last="Smith")
        with pytest.raises(ValueError, match="Unknown ladder mode"):
            run_ladder(ladder, ctx, mode="bogus")


# ============================================================
# Real strategy ladder end-to-end
# ============================================================
class TestRealLadder:
    """The 10 FaG strategies from scripts/search/strategies.py
    wired through run_ladder. End-to-end check that the refactor
    preserves behavior."""

    def test_first_mode_finds_b1_for_full_name(self):
        from scripts.search.strategies import STRATEGIES
        ctx = SearchContext(
            first="William", middle="Pickney", last="Looney",
            birth_year="1844", death_year="1932",
        )
        name, params = run_ladder(STRATEGIES, ctx, mode="first")
        # B1 wins (applies + first in ladder order)
        assert name == "B1-exact"
        assert params["firstname"] == "William"
        assert params["middlename"] == "Pickney"
        assert params["lastname"] == "Looney"

    def test_first_mode_finds_b1_for_minimal_name(self):
        from scripts.search.strategies import STRATEGIES
        # No middle, so B2 returns None (needs single-letter middle).
        # B1 still fires (only requires first + last).
        ctx = SearchContext(first="William", last="Looney")
        name, params = run_ladder(STRATEGIES, ctx, mode="first")
        assert name == "B1-exact"

    def test_all_mode_finds_year_sniper_when_both_years_present(self):
        from scripts.search.strategies import STRATEGIES
        ctx = SearchContext(
            first="William", last="Looney",
            birth_year="1844", death_year="1932",
        )
        results = run_ladder(STRATEGIES, ctx, mode="all")
        names = [n for n, _ in results]
        # F1c-year-sniper should be in the applicable set
        assert "F1c-year-sniper" in names
        # F1d-year-window should also be there
        assert "F1d-year-window" in names
