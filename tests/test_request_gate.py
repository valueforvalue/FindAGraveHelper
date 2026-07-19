"""Tests for scripts/fag/request_gate.py — Phase 4 Slice 4.1."""

import time

import pytest

from scripts.fag.request_gate import AcquireToken, RequestGate


def test_acquire_returns_token():
    """gate.acquire() returns an AcquireToken with provider and kind."""
    gate = RequestGate(provider="test.com", min_interval=0.0)
    with gate.acquire("search") as token:
        assert token.provider == "test.com"
        assert token.kind == "search"
        assert token.acquired_at > 0


def test_acquire_blocks_on_min_interval():
    """Second acquire blocks until min_interval elapsed."""
    gate = RequestGate(provider="test.com", min_interval=0.05)
    t0 = time.monotonic()
    with gate.acquire("search"):
        pass
    with gate.acquire("search"):
        pass
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.05


def test_default_fag_has_2500ms_floor():
    """RequestGate.default_fag() enforces 2.5s minimum."""
    gate = RequestGate.default_fag()
    assert gate.min_interval == 2.5


def test_cooldown_for_blocks_acquire():
    """After cooldown_for(), acquire() blocks until cooldown expires."""
    gate = RequestGate(provider="test.com", min_interval=0.0)
    gate.cooldown_for(0.1)

    t0 = time.monotonic()
    with gate.acquire("search"):
        pass
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.1


def test_cooldown_capped_at_max():
    """cooldown_for() caps at max_cooldown."""
    gate = RequestGate(provider="test.com", min_interval=0.0, max_cooldown=0.1)
    gate.cooldown_for(999.0)  # would be 999s, capped at 0.1s
    t0 = time.monotonic()
    with gate.acquire("search"):
        pass
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.1
    assert elapsed < 0.5  # not 999s


def test_set_not_before_iso_blocks():
    """set_not_before_iso with future timestamp blocks acquire."""
    from datetime import datetime, timedelta, timezone

    gate = RequestGate(provider="test.com", min_interval=0.0)
    # Use 1s delay + microsecond precision so truncation doesn't zero it out
    future_dt = datetime.now(timezone.utc) + timedelta(seconds=1.0)
    iso = future_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    gate.set_not_before_iso(iso)

    t0 = time.monotonic()
    with gate.acquire("search"):
        pass
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.5  # at least half the original delay


def test_set_not_before_iso_past_is_noop():
    """set_not_before_iso with past timestamp is a no-op."""
    gate = RequestGate(provider="test.com", min_interval=0.0)
    gate.set_not_before_iso("2020-01-01T00:00:00Z")  # past
    t0 = time.monotonic()
    with gate.acquire("search"):
        pass
    elapsed = time.monotonic() - t0
    assert elapsed < 0.01  # no blocking


def test_not_before_property():
    """not_before returns max of last_acquire+interval and cooldown."""
    gate = RequestGate(provider="test.com", min_interval=0.0)
    assert gate.not_before == 0.0

    with gate.acquire("search"):
        pass
    # After acquire, not_before should be >= last_acquire time
    assert gate.not_before > 0


def test_token_bot_wall_flag():
    """AcquireToken.bot_wall_observed is False by default."""
    gate = RequestGate(provider="test.com", min_interval=0.0)
    with gate.acquire("search") as token:
        assert token.bot_wall_observed is False
        token.bot_wall_observed = True
    # Token is discarded after context; gate state unchanged unless
    # cooldown_for() was explicitly called
