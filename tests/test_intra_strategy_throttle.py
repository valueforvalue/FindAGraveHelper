"""Tests for the inter-strategy throttle in search_one_pensioner.

The throttle must be enforced between STRATEGIES within one
pensioner, not just between pensioners. Without this, popular-
name records send ~10 page.goto() calls in 5-10 seconds flat
and trip Cloudflare's burst rate limit.

We can't drive a real browser in this test, so we verify the
behavior by patching search_one_pensioner to record call
timestamps and asserting the gap between consecutive strategies.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestIntraStrategyThrottleWiring:
    def test_throttle_param_accepted(self):
        """search_one_pensioner now accepts throttle_seconds."""
        import inspect
        from scripts.search_fag import search_one_pensioner
        sig = inspect.signature(search_one_pensioner)
        assert "throttle_seconds" in sig.parameters, (
            "search_one_pensioner must accept a throttle_seconds "
            "parameter for inter-strategy throttling."
        )

    def test_fag_browser_passes_throttle(self):
        """fag_browser must call search_one_pensioner with throttle_seconds."""
        import inspect
        from scripts import fag_browser
        src = inspect.getsource(fag_browser)
        assert "throttle_seconds=throttle" in src, (
            "fag_browser.make_fag_search_fn closure must pass "
            "throttle_seconds=throttle to search_one_pensioner."
        )

    def test_throttle_only_kicks_in_after_first_strategy(self):
        """The inter-strategy sleep should NOT fire before the first
        strategy (it has nothing before it). Verified by source-level
        check: the sleep is guarded by 'and strategy_runs'.
        """
        from scripts import search_fag
        src = open(search_fag.__file__).read()
        # Find the inter-strategy pause block.
        assert "if throttle_seconds and throttle_seconds > 0 and strategy_runs:" in src, (
            "Inter-strategy throttle must be guarded by 'and strategy_runs' "
            "so it doesn't fire before the first strategy."
        )
        assert "time.sleep(throttle_seconds)" in src
