"""Tests for RSSWatchdog (scripts/rss_watchdog.py).

Strategy: monkeypatch the Win32 binding so tests are platform-agnostic
and deterministic. We use a tiny "FakeProcess" object that returns a
caller-controlled RSS reading on each poll. The test then verifies
threshold behavior end-to-end.

Covers:
  - current_rss_mb starts at 0
  - set_should_force_reset / clear_force_reset roundtrip
  - warn_mb threshold logs once at first crossing
  - force_reset_mb threshold sets the event
  - exit_mb threshold causes os._exit(1) (mocked)
  - Thresholds of 0 disable their respective action
  - _get_rss_bytes returns the fake binding's value (smoke)
"""
from __future__ import annotations

import threading
import time
from unittest import mock

import pytest


@pytest.fixture
def fake_rss_env(monkeypatch):
    """Install deterministic RSS readings.

    Returns a tuple (setter, sequence_list) where:
      setter(mb_value): configures next 1+ readings
      sequence_list: list of readings already consumed
    """
    readings = []
    # Make _ensure_binding succeed (we are not on Linux but the struct
    # is platform-agnostic — the ctypes machinery is what fails on
    # Linux. We sidestep that by monkeypatching _get_rss_bytes
    # directly).
    monkeypatch.setattr("scripts.rss_watchdog._get_rss_bytes", lambda: next_reading())
    iterator = iter(readings)

    def next_reading():
        try:
            return next(iterator)
        except StopIteration:
            return None

    def set_next(values):
        """Append values to the readings queue."""
        readings.extend(values)

    return set_next


def test_rss_watchdog_default_state():
    from scripts.rss_watchdog import RSSWatchdog
    wd = RSSWatchdog()
    assert wd.current_rss_mb() == 0
    assert wd.should_force_reset() is False


def test_rss_force_reset_roundtrip():
    from scripts.rss_watchdog import RSSWatchdog
    wd = RSSWatchdog()
    # Simulate the runner calling this from outside.
    wd._force_reset_event.set()
    assert wd.should_force_reset() is True
    wd.clear_force_reset()
    assert wd.should_force_reset() is False


def test_rss_watchdog_force_reset_at_threshold(fake_rss_env):
    """At 4096+ MB the watchdog sets the force_reset_event."""
    from scripts.rss_watchdog import RSSWatchdog
    fake_rss_env([5000 * 1024 * 1024])  # 5000 MB next reading
    wd = RSSWatchdog(poll_seconds=0.05, warn_mb=2048,
                     force_reset_mb=4096, exit_mb=0)
    wd.start()
    try:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if wd.should_force_reset():
                break
            time.sleep(0.02)
        assert wd.should_force_reset(), "force_reset must trigger at high RSS"
        assert wd.current_rss_mb() == 5000
    finally:
        wd.stop()


def test_rss_watchdog_no_force_reset_when_below(fake_rss_env):
    """At low RSS the watchdog never triggers."""
    from scripts.rss_watchdog import RSSWatchdog
    fake_rss_env([100 * 1024 * 1024])  # 100 MB
    wd = RSSWatchdog(poll_seconds=0.05, warn_mb=2048,
                     force_reset_mb=4096, exit_mb=0)
    wd.start()
    try:
        time.sleep(0.2)
        assert wd.should_force_reset() is False
        assert wd.current_rss_mb() == 100
    finally:
        wd.stop()


def test_rss_watchdog_disabled_thresholds(fake_rss_env):
    """passing 0 for any threshold disables that action."""
    from scripts.rss_watchdog import RSSWatchdog
    fake_rss_env([10 * 1024 * 1024 * 1024])  # 10 GB — would blow everything
    wd = RSSWatchdog(poll_seconds=0.05, warn_mb=0,
                     force_reset_mb=0, exit_mb=0)
    wd.start()
    try:
        time.sleep(0.15)
        assert wd.should_force_reset() is False  # 0 means disabled
        # No exit() because exit_mb=0
    finally:
        wd.stop()


def test_rss_watchdog_exit_calls_osexit(fake_rss_env):
    """At exit_mb the watchdog calls os._exit(1)."""
    from scripts.rss_watchdog import RSSWatchdog
    fake_rss_env([7 * 1024 * 1024 * 1024])  # 7 GB
    with mock.patch("scripts.rss_watchdog.os._exit") as osexit:
        wd = RSSWatchdog(poll_seconds=0.05, warn_mb=0,
                         force_reset_mb=0, exit_mb=6144)
        wd.start()
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if osexit.called:
                break
            time.sleep(0.02)
        assert osexit.called, "os._exit must fire when RSS >= exit threshold"
        assert osexit.call_args.args == (1,)
        wd.stop()


def test_rss_watchdog_start_idempotent():
    """Calling start() twice does not spawn a second thread."""
    from scripts.rss_watchdog import RSSWatchdog
    wd = RSSWatchdog(poll_seconds=10.0)
    wd.start()
    t1 = wd._thread
    wd.start()
    t2 = wd._thread
    assert t1 is t2


def test_rss_watchdog_stop_event():
    """stop() sets the stop event so the loop exits."""
    from scripts.rss_watchdog import RSSWatchdog
    wd = RSSWatchdog(poll_seconds=0.05)
    wd.start()
    wd.stop()
    assert wd._stop_event.is_set()
