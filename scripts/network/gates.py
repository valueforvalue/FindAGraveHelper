"""ProviderRegistry: per-provider RequestGate lookup (Slice 10).

Pre-emptive infrastructure for multi-provider throttling. Today
only FaG is registered; future engines (NewspapersComEngine,
any third-party) call `ProviderRegistry.for(name)` to get the
shared throttle seam. The FaG gate is constructed on first
lookup and reused for the rest of the process.

Usage:
    from scripts.network.gates import ProviderRegistry

    gate = ProviderRegistry.for("findagrave.com")
    with gate.acquire("search") as token:
        page.goto(token.url)

The registry is sync-only; async engines are deferred per
the Slice 10 design's "when to revisit" section.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from scripts.fag.request_gate import RequestGate


class ProviderRegistry:
    """Singleton registry mapping provider name → RequestGate.

    `for(name)` returns the existing gate if registered, or builds
    a default one if `auto_register_defaults` covers the name.
    New providers can be registered explicitly via `register()`.
    """

    _gates: dict[str, RequestGate] = {}
    _factories: dict[str, Callable[[], RequestGate]] = {}
    _initialized: bool = False

    @classmethod
    def _ensure_defaults(cls) -> None:
        """Lazy-init the default factories (FaG only today)."""
        if cls._initialized:
            return
        cls._factories["findagrave.com"] = RequestGate.default_fag
        cls._initialized = True

    @classmethod
    def register(cls, name: str, gate: RequestGate) -> None:
        """Register a gate under `name`. Overwrites any existing entry."""
        cls._ensure_defaults()
        cls._gates[name] = gate

    @classmethod
    def register_factory(
        cls, name: str, factory: Callable[[], RequestGate]
    ) -> None:
        """Register a lazy factory for `name` (called on first lookup)."""
        cls._ensure_defaults()
        cls._factories[name] = factory

    @classmethod
    def get(cls, name: str) -> RequestGate:
        """Return the gate for `name`, building it via the factory if needed.

        Raises KeyError if `name` is not registered.
        """
        cls._ensure_defaults()
        if name in cls._gates:
            return cls._gates[name]
        if name in cls._factories:
            cls._gates[name] = cls._factories[name]()
            return cls._gates[name]
        raise KeyError(
            f"No gate registered for provider {name!r}. "
            f"Known providers: {sorted(set(cls._gates) | set(cls._factories))}"
        )

    @classmethod
    def reset(cls) -> None:
        """Drop all gates and re-enable default factories.

        Test-only helper; production code should never call this.
        """
        cls._gates.clear()
        cls._factories.clear()
        cls._initialized = False

    @classmethod
    def known_providers(cls) -> list[str]:
        """List provider names currently registered (gates + factories)."""
        cls._ensure_defaults()
        return sorted(set(cls._gates) | set(cls._factories))


__all__ = ["ProviderRegistry"]