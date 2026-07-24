"""StrategyRegistry: name → Strategy lookup singleton (#99).

Enables cross-engine strategy reuse (issue #99 audit-backlog
item #7). Each engine (FaG, Newspapers.com, future Ancestry)
calls `StrategyRegistry.get(name)` to resolve a shared Strategy
instance, eliminating the per-engine duplication the audit
flagged.

The registry is the strategy-side analog of `ProviderRegistry`
(Slice 10). Sync-only; async strategies are deferred.

Usage:
    from scripts.search.strategy_registry import StrategyRegistry
    from scripts.search.strategy import as_strategy

    StrategyRegistry.register(
        "year_sniper",
        as_strategy("year_sniper", year_sniper_fn),
    )
    s = StrategyRegistry.get("year_sniper")
    params = s.params(ctx)
"""
from __future__ import annotations

from typing import Callable

from scripts.search.strategy import Strategy


class StrategyRegistry:
    """Singleton registry mapping strategy name → Strategy.

    `get(name)` returns the existing Strategy if registered, or
    builds one via the registered factory. New strategies can be
    registered explicitly via `register()` or lazily via
    `register_factory()`. Sync-only.
    """

    _strategies: dict[str, Strategy] = {}
    _factories: dict[str, Callable[[], Strategy]] = {}
    _initialized: bool = False

    @classmethod
    def register_defaults(cls) -> None:
        """Register the canonical cross-engine strategies (idempotent).

        Called by `run_ladder()` and any engine that wants the
        default Strategy population. Engines that want to override
        a default can call `register(name, strategy)` after this
        and their version wins.

        Currently registered:
          - `year_sniper` (F1c) — name + birth year + death year
            triple-filter. The most precise shared strategy; both
            FaG and Newspapers.com use it.
        """
        if cls._initialized:
            return
        # Lazy import to avoid a circular dep at module load.
        from scripts.search.strategies import year_sniper
        from scripts.search.strategy import as_strategy

        cls.register_factory("year_sniper", lambda: as_strategy("year_sniper", year_sniper))
        cls._initialized = True

    @classmethod
    def register(cls, name: str, strategy: Strategy) -> None:
        """Register a strategy under `name`. Overwrites any existing."""
        cls._strategies[name] = strategy

    @classmethod
    def register_factory(
        cls, name: str, factory: Callable[[], Strategy]
    ) -> None:
        """Register a lazy factory for `name` (called on first get)."""
        cls._factories[name] = factory

    @classmethod
    def get(cls, name: str) -> Strategy:
        """Return the strategy for `name`, building via factory if needed.

        Raises KeyError if `name` is not registered.
        """
        if name in cls._strategies:
            return cls._strategies[name]
        if name in cls._factories:
            cls._strategies[name] = cls._factories[name]()
            return cls._strategies[name]
        raise KeyError(
            f"No strategy registered for {name!r}. "
            f"Known strategies: {sorted(set(cls._strategies) | set(cls._factories))}"
        )

    @classmethod
    def reset(cls) -> None:
        """Drop all entries. Test-only helper."""
        cls._strategies.clear()
        cls._factories.clear()
        cls._initialized = False

    @classmethod
    def known_strategies(cls) -> list[str]:
        """List strategy names currently registered (entries + factories)."""
        return sorted(set(cls._strategies) | set(cls._factories))


__all__ = ["StrategyRegistry"]