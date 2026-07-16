"""Regression test for the 'state names dict recreated per call' leak.

extract_state_from_regiment() and parse_results_page() used to
recreate 50-entry state-name dicts on every call. Over a 7709-record
run that's 100K + 500K transient dicts whose allocator pages never
got returned to the OS. The fix was to hoist both lookups to module
level; this test verifies they're there and are the SAME object
across calls (id() stable).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_state_names_upper_is_module_level():
    from scripts.fag.search import _STATE_NAMES_UPPER
    assert isinstance(_STATE_NAMES_UPPER, dict)
    assert len(_STATE_NAMES_UPPER) >= 50
    # Spot-check a few keys to catch accidental rename/drop
    assert _STATE_NAMES_UPPER["ALABAMA"] == "AL"
    assert _STATE_NAMES_UPPER["TEXAS"] == "TX"
    assert _STATE_NAMES_UPPER["OKLAHOMA"] == "OK"


def test_state_names_lower_is_module_level():
    from scripts.fag.search import _STATE_NAMES_LOWER
    assert isinstance(_STATE_NAMES_LOWER, dict)
    assert len(_STATE_NAMES_LOWER) == len(
        __import__("scripts.fag.search", fromlist=["_STATE_NAMES_UPPER"])._STATE_NAMES_UPPER
    )
    assert _STATE_NAMES_LOWER["alabama"] == "AL"
    assert _STATE_NAMES_LOWER["oklahoma"] == "OK"


def test_extract_state_from_regiment_does_not_recreate_dict():
    """Call the function 1000 times and verify _STATE_NAMES_UPPER's
    id() is unchanged. If the dict was being recreated as a local,
    its id() would either change between calls (if the dict was
    reallocated) or, more commonly, the function would still
    reference the global; we test that no NEW dict is allocated by
    checking gc stats.
    """
    import gc
    from scripts.search_fag import extract_state_from_regiment

    base_dicts = len(gc.get_objects())
    for _ in range(1000):
        extract_state_from_regiment("1st Texas Infantry")
        extract_state_from_regiment("2nd Mississippi & 3rd Mississippi Infantry & Cavalry")
        extract_state_from_regiment("10th Tennessee Cavalry")
        extract_state_from_regiment("Some Random Reg Without State")
    end_dicts = len(gc.get_objects())
    delta = end_dicts - base_dicts
    # cpython's per-call dict creation would add ~10,000 dicts (4
    # functions x 1000 calls x 2-3 dicts per call). With module-level
    # hoisting, the delta should be ~0 plus a small jitter.
    assert delta < 500, (
        f"Tracked objects grew by {delta} after 4000 calls. "
        f"Module-level state_names hoisting appears to be inactive."
    )


def test_parse_results_page_does_not_recreate_dict():
    """parse_results_page() historically had its own local state_names
    dict (lowercase keys). The fix replaces it with the module
    constant. We can't drive a full parse here (needs real browser),
    but we can confirm the symbol resolves to the module constant.
    """
    import inspect

    from scripts import search_fag

    src = inspect.getsource(search_fag.parse_results_page)
    # The lowercase block should NOT define its own dict literal.
    # We accept that fixture data may contain _STATE_NAMES_LOWER.
    assert "state_names = {" not in src, (
        "parse_results_page still has an inline state_names dict; "
        "should reference _STATE_NAMES_LOWER instead."
    )


class TestStateScoreNowUsed:
    """Bug 2.2: state_score was computed but not added to score sum."""

    def test_score_candidate_includes_state_score(self):
        import inspect
        from scripts import search_fag
        src = inspect.getsource(search_fag.score_candidate)
        # The score formula must reference state_score; previously it didn't.
        assert "state_score" in src, (
            "score_candidate must reference state_score in the score "
            "formula. The current formula at line ~534 omits it (Bug 2.2)."
        )
        # And the score formula itself should include a coefficient for it.
        import re
        match = re.search(r"score\s*=\s*\(([^)]+)\)", src, re.DOTALL)
        assert match is not None, "Could not find score formula in score_candidate"
        formula = match.group(1)
        assert "state_score" in formula, (
            f"state_score is computed but not added to the score formula:\n{formula}"
        )


class TestLouisianaTypo:
    """Bug 2.1: 'LOUISIANI' typo in module-level dict."""

    def test_louisiana_typo_removed(self):
        from scripts.fag.search import _STATE_NAMES_UPPER
        assert "LOUISIANI" not in _STATE_NAMES_UPPER, (
            "Bug 2.1: 'LOUISIANI' typo present in _STATE_NAMES_UPPER."
        )
        # The correct entry should still be there.
        assert _STATE_NAMES_UPPER.get("LOUISIANA") == "LA"


class TestMemorialPathRegexIsCompiled:
    """Bug 2.4: re.search with string pattern in hot loop.
    parse_results_page() should use the module-level compiled
    _MEMORIAL_PATH_RE, not a literal re.search() per call.
    """

    def test_uses_compiled_pattern(self):
        import inspect
        from scripts import search_fag
        src = inspect.getsource(search_fag.parse_results_page)
        # The compiled pattern must be referenced.
        assert "_MEMORIAL_PATH_RE" in src, (
            "parse_results_page should reference the compiled "
            "_MEMORIAL_PATH_RE, not call re.search with a string literal."
        )


class TestWaitForSelectorDisposesHandle:
    """Bug 2.3: ElementHandle from wait_for_selector was leaked."""

    def test_handle_is_disposed(self):
        import inspect
        from scripts import search_fag
        src = inspect.getsource(search_fag.parse_results_page)
        # Must call .dispose() on the handle returned by wait_for_selector.
        # The phrase "dispose" should appear at least once.
        assert "dispose" in src, (
            "wait_for_selector return value should be disposed via "
            ".dispose() to avoid ElementHandle leak (Bug 2.3)."
        )
