"""Tests for BrowserConfig + BrowserSession.from_config (Slice 9).

Pin that the new dataclass carries all 8 BrowserSession knobs
and that `BrowserSession.from_config(BrowserConfig)` produces a
session whose attributes match the config values.
"""

from __future__ import annotations

from scripts.fag.browser_config import BrowserConfig


def test_browser_config_defaults_match_browser_session_defaults():
    """BrowserConfig() reproduces pre-Slice-9 BrowserSession defaults."""
    cfg = BrowserConfig()
    assert cfg.throttle == 2.5
    assert cfg.reset_every == 250
    assert cfg.headless is False
    assert cfg.state_filter == "OK"
    assert cfg.auto_relax is False
    assert cfg.max_consecutive_errors == 10
    assert cfg.user_agent is None
    assert cfg.enforce_throttle_floor is True


def test_browser_config_is_frozen():
    """BrowserConfig is a frozen dataclass — immutable after init."""
    cfg = BrowserConfig()
    import pytest

    with pytest.raises(Exception):
        cfg.throttle = 1.0  # type: ignore[misc]


def test_browser_config_from_unified_reads_parent_fields():
    """from_unified pulls each field from the parent via getattr."""

    class _Parent:
        throttle_seconds = 1.5
        browser_reset_every = 100
        headless = True
        browser_state_filter = "US"
        auto_relax = True
        max_consecutive_errors = 5
        enforce_throttle_floor = False

    cfg = BrowserConfig.from_unified(_Parent())
    assert cfg.throttle == 1.5
    assert cfg.reset_every == 100
    assert cfg.headless is True
    assert cfg.state_filter == "US"
    assert cfg.auto_relax is True
    assert cfg.max_consecutive_errors == 5
    assert cfg.enforce_throttle_floor is False


def test_browser_config_from_unified_uses_defaults_for_missing_fields():
    """When a parent field is absent, the BrowserConfig default wins."""

    class _Empty:
        pass

    cfg = BrowserConfig.from_unified(_Empty())
    assert cfg.throttle == 2.5
    assert cfg.reset_every == 250
    assert cfg.headless is False
    assert cfg.state_filter == "OK"


def test_from_config_produces_session_with_config_values(monkeypatch):
    """BrowserSession.from_config returns a session whose attrs match."""
    # Don't actually start Playwright; build the session object only.
    # from_config returns without calling start(), so this is safe.
    from scripts.fag.browser_session import BrowserSession

    cfg = BrowserConfig(
        throttle=2.5,
        reset_every=42,
        headless=True,
        state_filter="US",
        auto_relax=True,
        max_consecutive_errors=3,
        user_agent="custom-agent/1.0",
        enforce_throttle_floor=True,
    )
    session = BrowserSession.from_config(cfg)

    try:
        assert session.throttle == 2.5
        assert session.reset_every == 42
        assert session.headless is True
        assert session.state_filter == "US"
        assert session.auto_relax is True
        assert session.max_consecutive_errors == 3
        assert session.user_agent == "custom-agent/1.0"
        assert session._started is False
    finally:
        # Avoid the close path touching Playwright (session never started).
        pass


def test_from_config_overrides_win_over_config(monkeypatch):
    """Per-kwarg overrides passed to from_config win over config values."""
    from scripts.fag.browser_session import BrowserSession

    cfg = BrowserConfig(throttle=2.5, reset_every=250)
    session = BrowserSession.from_config(cfg, reset_every=999)

    try:
        assert session.reset_every == 999
        assert session.throttle == 2.5  # from config, not overridden
    finally:
        pass


def test_from_config_rejects_non_browser_config():
    """from_config raises TypeError when given anything other than BrowserConfig."""
    from scripts.fag.browser_session import BrowserSession

    import pytest

    with pytest.raises(TypeError):
        BrowserSession.from_config({"throttle": 1.0})  # dict, not BrowserConfig