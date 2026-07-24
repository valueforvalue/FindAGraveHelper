"""Tests for the Strategy registry (#99).

Pin the StrategyRegistry singleton:
  - get(name) returns the registered Strategy.
  - register(name, strategy) overwrites any existing entry.
  - Same name returns the same instance (singleton-per-name).
  - Unknown name raises KeyError with a helpful message.
  - The FaG engine and any future engine can resolve the
    same shared Strategy (year_sniper, etc.) by name.
"""

from __future__ import annotations

import pytest

from scripts.search.context import SearchContext
from scripts.search.strategy import (
    FunctionStrategy,
    Strategy,
    as_strategy,
)
from scripts.search.strategy_registry import StrategyRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test gets a fresh registry to avoid cross-test pollution."""
    StrategyRegistry.reset()
    yield
    StrategyRegistry.reset()


def _ctx(first="John", last="Doe", middle="", birth_year="", death_year="") -> SearchContext:
    return SearchContext(
        first=first, middle=middle, last=last,
        birth_year=birth_year, death_year=death_year,
    )


def test_registry_starts_empty_after_reset():
    """A reset registry has no entries; known-providers/strategies
    list is empty."""
    assert StrategyRegistry.known_strategies() == []


def test_register_and_get_returns_same_instance():
    """register(name, strategy) + get(name) returns the same instance."""
    strat = as_strategy("year_sniper", lambda ctx: {"year": "x"})
    StrategyRegistry.register("year_sniper", strat)
    got = StrategyRegistry.get("year_sniper")
    assert got is strat
    # Singleton-per-name: a second get returns the same object.
    assert StrategyRegistry.get("year_sniper") is got


def test_register_overwrites_existing():
    """register() replaces the existing entry under that name."""
    first = as_strategy("year_sniper", lambda ctx: {"v": 1})
    second = as_strategy("year_sniper", lambda ctx: {"v": 2})
    StrategyRegistry.register("year_sniper", first)
    StrategyRegistry.register("year_sniper", second)
    assert StrategyRegistry.get("year_sniper") is second
    # And calling it returns the new behavior.
    out = StrategyRegistry.get("year_sniper").params(_ctx())
    assert out == {"v": 2}


def test_register_factory_is_lazy():
    """register_factory() stores the factory; it's not called until get()."""
    calls: list[int] = []

    def factory():
        calls.append(1)
        return as_strategy("lazy_one", lambda ctx: {"k": "v"})

    StrategyRegistry.register_factory("lazy_one", factory)
    assert calls == []
    s = StrategyRegistry.get("lazy_one")
    assert isinstance(s, Strategy)
    assert calls == [1]
    # Second lookup reuses the cached instance.
    StrategyRegistry.get("lazy_one")
    assert calls == [1]


def test_get_raises_keyerror_for_unknown():
    """Unknown name raises KeyError with a helpful message."""
    with pytest.raises(KeyError) as excinfo:
        StrategyRegistry.get("not_registered")
    msg = str(excinfo.value)
    assert "not_registered" in msg


def test_known_strategies_lists_both_gates_and_factories():
    """known_strategies() reports the union of registered + factories."""
    StrategyRegistry.register(
        "explicit", as_strategy("explicit", lambda ctx: None)
    )
    StrategyRegistry.register_factory(
        "lazy", lambda: as_strategy("lazy", lambda ctx: None)
    )
    known = StrategyRegistry.known_strategies()
    assert "explicit" in known
    assert "lazy" in known


def test_reset_drops_all_state():
    """reset() clears entries; subsequent register calls re-populate."""
    StrategyRegistry.register("s1", as_strategy("s1", lambda ctx: None))
    StrategyRegistry.reset()
    assert StrategyRegistry.known_strategies() == []
    # And the registry accepts a fresh registration.
    StrategyRegistry.register("s2", as_strategy("s2", lambda ctx: None))
    assert "s2" in StrategyRegistry.known_strategies()


def test_register_defaults_populates_year_sniper():
    """register_defaults() is the canonical entry point for engines.
    It registers the cross-engine year_sniper strategy.
    """
    StrategyRegistry.register_defaults()
    s = StrategyRegistry.get("year_sniper")
    assert isinstance(s, Strategy)
    assert s.name == "year_sniper"


def test_register_defaults_is_idempotent():
    """Calling register_defaults() twice doesn't double-register."""
    StrategyRegistry.register_defaults()
    first = StrategyRegistry.get("year_sniper")
    StrategyRegistry.register_defaults()
    second = StrategyRegistry.get("year_sniper")
    # Same instance — defaults were not re-registered.
    assert first is second


def test_register_overrides_default():
    """register() after register_defaults() replaces the default."""
    StrategyRegistry.register_defaults()
    custom = as_strategy("year_sniper", lambda ctx: {"custom": True})
    StrategyRegistry.register("year_sniper", custom)
    assert StrategyRegistry.get("year_sniper") is custom


def test_year_sniper_registered_via_factory():
    """The shared year_sniper factory is a canonical use case:
    one registration, multiple engines, no duplication."""
    from scripts.search.strategies import year_sniper

    StrategyRegistry.register_factory(
        "year_sniper", lambda: as_strategy("year_sniper", year_sniper)
    )
    a = StrategyRegistry.get("year_sniper")
    b = StrategyRegistry.get("year_sniper")
    assert a is b
    # And it actually works on a real context.
    out = a.params(_ctx(birth_year="1840", death_year="1920"))
    assert out is not None
    assert "birthyear" in out or "deathyear" in out


def test_reset_resets_lazy_factory_caches():
    """reset() clears both the registered entries AND any cached
    results from lazy factories."""
    calls: list[int] = []

    def factory():
        calls.append(1)
        return as_strategy("f", lambda ctx: None)

    StrategyRegistry.register_factory("f", factory)
    StrategyRegistry.get("f")
    assert calls == [1]  # one call so far
    StrategyRegistry.reset()
    # After reset, the factory entry is gone.
    with pytest.raises(KeyError):
        StrategyRegistry.get("f")
    # And re-registering with the same factory will call it again
    # on the next get, appending to the closure's calls list.
    StrategyRegistry.register_factory("f", factory)
    StrategyRegistry.get("f")
    assert calls == [1, 1]