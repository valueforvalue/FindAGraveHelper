"""Tests for the stealth backend selection (#94).

Pin the STEALTH_BACKEND factory:
- `patchright` (default) — sync Playwright drop-in with binary-
  level Runtime.Enable fix (the check Cloudflare Turnstile uses).
  Pairs with playwright-stealth v2 for JS-level evasions.
- `playwright_stealth` — legacy path (AtuboDad / Mattwmaster58).
  Keep as a back-compat option.
- `playwright` — bare Playwright, no stealth. For testing and
  local development.
- Unknown name → ValueError with the list of valid options.
- `cf_verify()` is exposed as a no-op stub today (operator PR
  wires a real challenge re-fetch).
"""

from __future__ import annotations

import os

import pytest

from scripts.fag.browser_backend import (
    SUPPORTED_BACKENDS,
    BrowserBackend,
    cf_verify,
    get_backend,
)


def test_supported_backends_listed():
    """The three documented backends are present."""
    assert set(SUPPORTED_BACKENDS) == {
        "patchright",
        "playwright_stealth",
        "playwright",
    }


def test_get_backend_default_is_patchright(monkeypatch):
    """Default STEALTH_BACKEND is 'patchright' (per the audit)."""
    monkeypatch.delenv("STEALTH_BACKEND", raising=False)
    backend = get_backend()
    assert backend.name == "patchright"


def test_get_backend_playwright_stealth(monkeypatch):
    """STEALTH_BACKEND=playwright_stealth selects the legacy path."""
    monkeypatch.setenv("STEALTH_BACKEND", "playwright_stealth")
    backend = get_backend()
    assert backend.name == "playwright_stealth"


def test_get_backend_bare_playwright(monkeypatch):
    """STEALTH_BACKEND=playwright selects the bare path (no stealth)."""
    monkeypatch.setenv("STEALTH_BACKEND", "playwright")
    backend = get_backend()
    assert backend.name == "playwright"


def test_get_backend_unknown_raises(monkeypatch):
    """Unknown STEALTH_BACKEND raises ValueError with the valid list."""
    monkeypatch.setenv("STEALTH_BACKEND", "nope")
    with pytest.raises(ValueError) as excinfo:
        get_backend()
    msg = str(excinfo.value)
    assert "nope" in msg
    for b in SUPPORTED_BACKENDS:
        assert b in msg


def test_backend_protocol_satisfied():
    """A BrowserBackend exposes the right surface."""

    class _FakeBackend:
        name = "fake"
        description = "test"
        layer_stealth = False
        cloudflare_bypass = False

        def sync_playwright(self):
            return None

    backend = _FakeBackend()
    assert isinstance(backend, BrowserBackend)
    assert backend.name == "fake"


def test_cf_verify_noop_today():
    """cf_verify is a documented no-op; the operator PR replaces it
    with a real challenge re-fetch. Today it returns False so
    callers see the consistent 'no recovery' signal."""
    assert cf_verify() is False


def test_cf_verify_accepts_url_for_forward_compat(monkeypatch):
    """cf_verify(url) is the future API; today it's a no-op."""
    assert cf_verify("https://findagrave.com/memorial/123") is False