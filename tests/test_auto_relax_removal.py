"""Tests for the auto-relax removal (#74, #80).

Per issues #74 and #80: the engine-flow auto-relax methods
(`_try_auto_relax` and `_try_auto_relax_engine` on
`BrowserSession`) are dead code. The 4-tier plan ladder
(`RegionalPlannerKS` → OK → regiment → TX → US) carries
broadening responsibility; OK-scoped plans preserve their
result without being replaced by a US re-search.

These tests pin that:
- The methods are GONE from `BrowserSession`.
- `fag_scraper.py` does NOT call them.
- The legacy opt-in path (`FAG_AUTO_RELAX=1` in
  `scripts/fag/fag_browser.py`) is unaffected — that's the
  pre-Blackboard code path, env-gated.
- `BrowserSession.auto_relax` is still a config field (test
  doubles need it) but the methods that acted on it are gone.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_browser_session_has_no_try_auto_relax():
    """The legacy _try_auto_relax method is removed from
    BrowserSession. (The config field `auto_relax` stays so
    test doubles and recipe serialization don't break.)"""
    from scripts.fag.browser_session import BrowserSession

    assert not hasattr(BrowserSession, "_try_auto_relax"), (
        "BrowserSession._try_auto_relax should be removed "
        "(issue #80). The 4-tier plan ladder handles broadening."
    )


def test_browser_session_has_no_try_auto_relax_engine():
    """The engine-flow counterpart is removed from BrowserSession."""
    from scripts.fag.browser_session import BrowserSession

    assert not hasattr(BrowserSession, "_try_auto_relax_engine"), (
        "BrowserSession._try_auto_relax_engine should be removed "
        "(issue #74). The 4-tier plan ladder handles broadening."
    )


def test_fag_scraper_does_not_call_try_auto_relax():
    """scripts/knowledge/fag_scraper.py should not reference the
    removed methods. (Source-level check; the methods are gone
    from the class, so a static import would AttributeError, but
    a leftover comment or doc reference would mislead future
    contributors.)"""
    src = Path("scripts/knowledge/fag_scraper.py").read_text(encoding="utf-8")
    assert "_try_auto_relax" not in src, (
        "fag_scraper.py should not reference the removed "
        "auto-relax methods."
    )


def test_legacy_fag_browser_auto_relax_unchanged():
    """The opt-in legacy auto-relax in scripts/fag/fag_browser.py
    (gated by FAG_AUTO_RELAX=1) is unaffected by this change.
    That path is the pre-Blackboard code path and is env-gated
    for operator opt-in. We grep the source to confirm it's
    still there."""
    src = Path("scripts/fag/fag_browser.py").read_text(encoding="utf-8")
    assert "FAG_AUTO_RELAX" in src
    assert '_should_broaden' in src
    # And the auto-relax block still uses the right US scope.
    assert 'state_filter="US"' in src


def test_browser_session_auto_relax_field_still_present():
    """The `auto_relax` config field on BrowserSession stays
    (test doubles + recipe serialization rely on it). What
    changed: the *methods* that acted on it are gone. The
    field is now informational; the engine-flow auto-relax
    no longer runs."""
    from scripts.fag.browser_session import BrowserSession

    # Init the field with auto_relax=False; the field is still
    # settable even though no method acts on it.
    sess = BrowserSession(
        throttle=2.5, auto_relax=False, enforce_throttle_floor=True
    )
    assert sess.auto_relax is False
    # And the no-FAG_AUTO_RELAX legacy env var still works as
    # before (this is a separate, opt-in code path).
    import os
    assert os.environ.get("FAG_AUTO_RELAX", "").strip() not in (
        "1", "true", "yes"
    )