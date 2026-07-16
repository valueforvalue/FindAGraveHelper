"""Tests for the Playwright Python memory-leak fix module.

Validates the runtime monkey-patch without spinning up a real
browser. The integration test (test_leak_fix_real.py in the
isolation worktree) measures the actual RSS reduction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestLeakFixModule:
    def test_apply_is_idempotent(self):
        from scripts.playwright_leak_fix import apply_playwright_leak_fix
        # First call: True (applied)
        first = apply_playwright_leak_fix()
        # Second call: False (already applied)
        second = apply_playwright_leak_fix()
        assert first is True
        assert second is False

    def test_sync_does_not_capture_inspect_stack(self):
        """The patched _sync must NOT call inspect.stack() to capture
        a stack trace. We check the source string for the offender
        patterns that the original Playwright code uses.
        """
        from scripts.playwright_leak_fix import apply_playwright_leak_fix
        apply_playwright_leak_fix()
        # `SyncBase._sync` is bound to the closure produced by the
        # patch module. `inspect.getsource` follows the original
        # closure, which is in playwright_leak_fix.py — not the
        # pre-patch file. So we read the closure's `__code__.co_filename`
        # and verify the patch module is the source.
        from playwright._impl._sync_base import SyncBase
        method = SyncBase._sync
        co = method.__code__
        assert "scripts/playwright_leak_fix.py" in co.co_filename or \
            co.co_filename.endswith("playwright_leak_fix.py"), (
                f"SyncBase._sync should bind to playwright_leak_fix.py; "
                f"got {co.co_filename!r}"
            )
        # Read the source as it would be loaded.
        import inspect
        src = inspect.getsource(method)
        assert "inspect.stack" not in src, (
            "_sync must not call inspect.stack(). Patched source:\n" + src
        )
        assert "traceback.extract_stack" not in src, (
            "_sync must not call traceback.extract_stack(). "
            "Patched source:\n" + src
        )

    def test_closure_log_message_does_not_leak(self):
        """As a small drift-protection test: if a future refactor
        accidentally re-adds a stack-capture, this test catches it.
        """
        from scripts.playwright_leak_fix import apply_playwright_leak_fix
        apply_playwright_leak_fix()
        import inspect
        from playwright._impl._sync_base import SyncBase
        method = SyncBase._sync
        src = inspect.getsource(method)
        # Both old offenders are gone; the patched version sets empty lists.
        assert "__pw_stack__" in src
        assert "__pw_stack_trace__" in src
        assert (
            'setattr(task, "__pw_stack__", [])' in src
        ), f"expected patched __pw_stack__ assignment in:\n{src}"
        assert (
            'setattr(task, "__pw_stack_trace__", [])' in src
        ), f"expected patched __pw_stack_trace__ assignment in:\n{src}"
