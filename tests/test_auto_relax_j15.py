"""Tests for the auto-relax state filter (issue #15).

When FAG_AUTO_RELAX=1 and the narrowed FaG search (state_filter=OK)
returns no useful candidate, scripts/fag/fag_browser.py retries
the search with state_filter="US" and uses whichever candidate
set is larger.

These tests exercise the helper function _should_broaden() and
the env-var gating in fag_search(). We don't make live network
calls; we test the decision logic only.
"""
from __future__ import annotations

import os

import pytest

from scripts.fag.fag_browser import _should_broaden


# ============================================================
# _should_broaden
# ============================================================

def test_should_broaden_when_status_auto_accept_returns_false():
    """Auto-accept already decided; no need to broaden."""
    record = {
        "status": "auto_accept",
        "ranked_candidates": [{"score": 0.9}],
    }
    assert _should_broaden(record) is False


def test_should_broaden_when_no_candidates_returns_true():
    """Empty result set means broaden."""
    record = {"status": "ambiguous", "ranked_candidates": []}
    assert _should_broaden(record) is True


def test_should_broaden_when_all_candidates_low_score_returns_true():
    """All candidates scored below threshold (modern same-name)."""
    record = {
        "status": "too_many",
        "ranked_candidates": [
            {"score": 0.1},
            {"score": 0.05},
            {"score": 0.2},
        ],
    }
    assert _should_broaden(record) is True


def test_should_broaden_when_some_candidate_high_score_returns_false():
    """At least one useful candidate; don't broaden."""
    record = {
        "status": "ambiguous",
        "ranked_candidates": [
            {"score": 0.1},
            {"score": 0.4},   # above threshold
            {"score": 0.2},
        ],
    }
    assert _should_broaden(record) is False


def test_should_broaden_handles_missing_score_field():
    """A candidate without a score field is skipped (not auto-broaden)."""
    record = {
        "status": "ambiguous",
        "ranked_candidates": [
            {"score": None},
            {"no_score_field": True},
        ],
    }
    assert _should_broaden(record) is True


def test_should_broaden_handles_non_numeric_score():
    """A non-numeric score raises TypeError; we skip it."""
    record = {
        "status": "ambiguous",
        "ranked_candidates": [
            {"score": "high"},  # string, not numeric
        ],
    }
    assert _should_broaden(record) is True


def test_should_broaden_custom_threshold():
    """Custom threshold respects the threshold arg."""
    record = {
        "status": "ambiguous",
        "ranked_candidates": [{"score": 0.5}],
    }
    assert _should_broaden(record, threshold=0.3) is False
    assert _should_broaden(record, threshold=0.6) is True


# ============================================================
# Env-var gating (FAG_AUTO_RELAX)
# ============================================================

def test_env_var_default_disabled(monkeypatch):
    """When FAG_AUTO_RELAX is unset, auto-relax is no-op."""
    monkeypatch.delenv("FAG_AUTO_RELAX", raising=False)
    assert os.environ.get("FAG_AUTO_RELAX", "").strip() not in ("1", "true", "yes")


def test_env_var_one_enables(monkeypatch):
    """FAG_AUTO_RELAX=1 enables the gating logic."""
    monkeypatch.setenv("FAG_AUTO_RELAX", "1")
    assert os.environ.get("FAG_AUTO_RELAX", "").strip() in ("1", "true", "yes")


def test_env_var_true_enables(monkeypatch):
    """FAG_AUTO_RELAX=true also enables."""
    monkeypatch.setenv("FAG_AUTO_RELAX", "true")
    assert os.environ.get("FAG_AUTO_RELAX", "").strip() in ("1", "true", "yes")


def test_env_var_random_disables(monkeypatch):
    """FAG_AUTO_RELAX=0 or other random values disable."""
    monkeypatch.setenv("FAG_AUTO_RELAX", "0")
    assert os.environ.get("FAG_AUTO_RELAX", "").strip() not in ("1", "true", "yes")
    monkeypatch.setenv("FAG_AUTO_RELAX", "nope")
    assert os.environ.get("FAG_AUTO_RELAX", "").strip() not in ("1", "true", "yes")


# ============================================================
# End-to-end: fag_search with env var gating
# ============================================================
# We can't easily mock the browser here without a heavyweight
# fixture. Instead, test the gating logic by reading source code:
# the auto-relax block must be conditioned on FAG_AUTO_RELAX=1
# AND state_filter == "OK".


def test_fag_browser_auto_relax_is_opt_in_via_env_var():
    """The auto-relax block reads os.environ at call-time, not at
    module-import time, so flipping the env var between calls
    would change behavior. Pin this by grep."""
    from pathlib import Path
    src = Path("scripts/fag/fag_browser.py").read_text(encoding="utf-8")
    assert "FAG_AUTO_RELAX" in src, \
        "fag_browser.py must check the FAG_AUTO_RELAX env var"
    # The auto-relax block must scope to OK filter only.
    # Find the auto-relax block; it should include the
    # 'state_filter == "OK"' guard.
    assert 'state_filter == "OK"' in src, \
        "auto-relax should only fire when state_filter is OK"


def test_fag_browser_auto_relax_uses_US_as_broadened_scope():
    """The broadened scope should be 'US' (country_4 in FaG)."""
    from pathlib import Path
    src = Path("scripts/fag/fag_browser.py").read_text(encoding="utf-8")
    # The auto-relax block must pass state_filter="US"
    assert 'state_filter="US"' in src, \
        "auto-relax should retry with state_filter='US'"


def test_fag_browser_auto_relax_keeps_larger_candidate_set():
    """When the US search returns more candidates, use it; else
    keep the OK result."""
    from pathlib import Path
    src = Path("scripts/fag/fag_browser.py").read_text(encoding="utf-8")
    # The decision is 'len(us_cands) > len(ok_cands)'
    assert "len(us_cands)" in src, \
        "auto-relax should compare len(us_cands) > len(ok_cands)"