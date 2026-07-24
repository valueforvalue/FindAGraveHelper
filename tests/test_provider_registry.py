"""Tests for ProviderRegistry (Slice 10).

Pin the registry shape: defaults loaded lazily, gates are
singletons per provider, lookup of unknown name raises,
register() overwrites, factories are called lazily.
"""

from __future__ import annotations

import pytest

from scripts.fag.request_gate import RequestGate
from scripts.network.gates import ProviderRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test gets a fresh registry to avoid cross-test pollution."""
    ProviderRegistry.reset()
    yield
    ProviderRegistry.reset()


def test_fag_default_factory_is_registered():
    """findagrave.com has a lazy factory out of the box."""
    assert "findagrave.com" in ProviderRegistry.known_providers()


def test_for_returns_gate_for_known_provider():
    """ProviderRegistry.get('findagrave.com') returns a RequestGate."""
    gate = ProviderRegistry.get("findagrave.com")
    assert isinstance(gate, RequestGate)
    assert gate.provider == "findagrave.com"
    assert gate.min_interval == 2.5  # L1 floor


def test_for_returns_same_instance_for_same_name():
    """The same provider always returns the same gate (singleton)."""
    g1 = ProviderRegistry.get("findagrave.com")
    g2 = ProviderRegistry.get("findagrave.com")
    assert g1 is g2


def test_for_raises_keyerror_for_unknown_provider():
    """Unknown provider name raises KeyError with helpful message."""
    with pytest.raises(KeyError) as excinfo:
        ProviderRegistry.get("nytimes.com")
    assert "nytimes.com" in str(excinfo.value)
    assert "findagrave.com" in str(excinfo.value)


def test_register_overrides_default_factory():
    """register() replaces any existing entry under that name."""
    custom_gate = RequestGate(provider="findagrave.com", min_interval=99.0)
    ProviderRegistry.register("findagrave.com", custom_gate)
    gate = ProviderRegistry.get("findagrave.com")
    assert gate is custom_gate
    assert gate.min_interval == 99.0


def test_register_factory_is_lazy():
    """register_factory stores the factory; it's not called until get()."""
    calls: list[int] = []

    def factory():
        calls.append(1)
        return RequestGate(provider="myengine.com", min_interval=1.0)

    ProviderRegistry.register_factory("myengine.com", factory)
    assert calls == []
    gate = ProviderRegistry.get("myengine.com")
    assert isinstance(gate, RequestGate)
    assert gate.provider == "myengine.com"
    assert calls == [1]
    # Second lookup reuses the cached gate.
    ProviderRegistry.get("myengine.com")
    assert calls == [1]


def test_known_providers_lists_both_gates_and_factories():
    """known_providers reports the union of registered gates + factories."""
    ProviderRegistry.register(
        "explicit.com", RequestGate(provider="explicit.com", min_interval=1.0)
    )
    ProviderRegistry.register_factory(
        "lazy.com", lambda: RequestGate(provider="lazy.com", min_interval=1.0)
    )
    known = ProviderRegistry.known_providers()
    assert "findagrave.com" in known  # default factory
    assert "explicit.com" in known
    assert "lazy.com" in known


def test_reset_drops_all_state():
    """reset() clears gates and factories; defaults re-init on next get()."""
    ProviderRegistry.get("findagrave.com")  # populates _gates
    ProviderRegistry.reset()
    # Default factory re-installs on next access.
    assert "findagrave.com" in ProviderRegistry.known_providers()