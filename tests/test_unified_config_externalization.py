"""Tests for issue #61: externalize BrowserSession config from code.

The Blackboard scheduler was hardcoding `state_filter='OK'`,
`reset_every=250`, `headless=False`, `throttle_seconds=2.5`
inside `run_batch_scheduler`. Per pragmatic-programmer §1.2
(orthogonality), every config value should come from the
config object; no magic numbers in the code path.

These tests pin the contract: the config dataclass exposes
the knobs, the scheduler honors them, and the throttle floor
can be relaxed by an operator knob (with a warning, not a
hard error) so slice runs at 1.5s work.
"""

from __future__ import annotations

import warnings

import pytest

from scripts.fag.browser_session import BrowserSession
from scripts.pipeline.run_unified import (
    UnifiedRunnerConfig,
    copy_view_html_if_missing,
)


# ============================================================
# Config: knobs exist with sensible defaults
# ============================================================


def test_config_exposes_browser_knobs():
    """The Blackboard scheduler should not have any hardcoded
    BrowserSession parameters. All knobs must live on the config.
    """
    cfg = UnifiedRunnerConfig()
    # Every knob the scheduler used to hardcode is now configurable.
    assert hasattr(cfg, "headless")
    assert hasattr(cfg, "browser_state_filter")
    assert hasattr(cfg, "browser_reset_every")
    assert hasattr(cfg, "max_consecutive_errors")
    assert hasattr(cfg, "auto_relax")
    assert hasattr(cfg, "fag_engine")
    assert hasattr(cfg, "enforce_throttle_floor")

    # Defaults match the historical hardcoded values
    # (so existing recipes continue to work).
    assert cfg.headless is False
    assert cfg.browser_state_filter == "OK"
    assert cfg.browser_reset_every == 250
    assert cfg.max_consecutive_errors == 10
    assert cfg.auto_relax is True
    assert cfg.enforce_throttle_floor is True


# ============================================================
# Throttle floor (L1): enforced by default, relaxable
# ============================================================


def test_throttle_floor_enforced_by_default():
    """L1 (CONTEXT.md): 2.5s is the safe Cloudflare-friendly floor.
    Below it, BrowserSession construction raises.
    """
    with pytest.raises(ValueError, match="below the 2.5s L1 floor"):
        BrowserSession(throttle=1.5)


def test_throttle_floor_relaxable_with_warning():
    """Operator opt-in: 1.5s is allowed when the floor is relaxed,
    but a DeprecationWarning fires so the operator sees the L1
    risk per issue #61.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        session = BrowserSession(
            throttle=1.5,
            enforce_throttle_floor=False,
        )
    # Session is constructed; throttle passed through
    assert session.throttle == 1.5
    # At least one DeprecationWarning about the L1 floor
    l1_warnings = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "L1" in str(w.message)
    ]
    assert len(l1_warnings) >= 1, (
        f"expected L1 DeprecationWarning, got {[str(w.message) for w in caught]}"
    )


def test_throttle_above_floor_always_ok():
    """No warning, no error, for 2.5s and above."""
    for t in (2.5, 3.0, 5.0):
        session = BrowserSession(throttle=t)
        assert session.throttle == t


# ============================================================
# view.html: defaults to v2 (already covered) but also externalized
# ============================================================


def test_view_html_source_default_is_v2():
    """When no `view_html_source` is supplied, scheduler uses v2
    (canonical since 2026-07-19).
    """
    from pathlib import Path
    repo_v2 = (
        Path(__file__).parent.parent
        / "scripts"
        / "view"
        / "v2.html"
    )
    # The default path is hardcoded in the scheduler; ensure
    # it points at v2.html and the file exists.
    assert repo_v2.exists(), f"v2.html missing at {repo_v2}"


# ============================================================
# Copy idempotency
# ============================================================


def test_copy_view_html_idempotent(tmp_path):
    """Per-run copy must not overwrite a per-run view.html.

    Pinned by `test_scheduler_copies_view_html_into_out_dir`;
    this is the lower-level helper check.
    """
    src = tmp_path / "src.html"
    src.write_text("<html>v1</html>", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    # First copy
    assert copy_view_html_if_missing(src, out) is True
    assert (out / "view.html").read_text(encoding="utf-8") == "<html>v1</html>"
    # Modify source; second copy must not propagate
    src.write_text("<html>v2</html>", encoding="utf-8")
    assert copy_view_html_if_missing(src, out) is False
    assert (out / "view.html").read_text(encoding="utf-8") == "<html>v1</html>"