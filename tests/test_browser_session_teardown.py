"""Tests for scripts/fag/browser_session.py teardown ordering — Phase 4 Slice 4.2."""

from unittest.mock import MagicMock


def test_close_calls_teardown_in_reverse_order():
    """BrowserSession.close() tears down page→context→browser→Playwright."""
    from scripts.fag.browser_session import BrowserSession

    session = BrowserSession.__new__(BrowserSession)
    # Bypass __init__ — set fields manually
    session.throttle = 0.1
    session.reset_every = 9999
    session.headless = False
    session.state_filter = "OK"
    session.auto_relax = False
    session.max_consecutive_errors = 10
    session.user_agent = "test"
    session._lock = __import__("threading").Lock()

    # Manually set mock objects
    mock_page = MagicMock()
    mock_ctx = MagicMock()
    mock_browser = MagicMock()
    mock_pw_cm = MagicMock()

    session._page = mock_page
    session._ctx = mock_ctx
    session._browser = mock_browser
    session._pw_cm = mock_pw_cm
    session._playwright = MagicMock()
    session._started = True

    # Track call order
    call_order = []

    def _record(name):
        def _inner():
            call_order.append(name)
        return _inner

    mock_page.close.side_effect = _record("page.close")
    mock_ctx.close.side_effect = _record("context.close")
    mock_browser.close.side_effect = _record("browser.close")
    mock_pw_cm.__exit__.side_effect = lambda *a: call_order.append("playwright.__exit__")

    session.close()

    assert call_order == [
        "page.close",
        "context.close",
        "browser.close",
        "playwright.__exit__",
    ], f"Expected reverse order, got {call_order}"
def test_throttle_below_floor_rejected():
    """BrowserSession never accepts a FaG throttle below project floor."""
    import pytest

    from scripts.fag.browser_session import BrowserSession

    with pytest.raises(ValueError, match="2.5"):
        BrowserSession(throttle=0.1)


def test_close_continues_after_teardown_error():
    """One close failure must not leak remaining browser resources."""
    from scripts.fag.browser_session import BrowserSession

    session = BrowserSession.__new__(BrowserSession)
    session._page = MagicMock()
    session._ctx = MagicMock()
    session._browser = MagicMock()
    session._pw_cm = MagicMock()
    session._playwright = MagicMock()
    session._started = True
    session._page.close.side_effect = RuntimeError("page already closed")

    context = session._ctx
    browser = session._browser
    playwright_manager = session._pw_cm

    session.close()

    context.close.assert_called_once_with()
    browser.close.assert_called_once_with()
    playwright_manager.__exit__.assert_called_once_with(None, None, None)
    assert session._page is None
    assert session._ctx is None
    assert session._browser is None
    assert session._pw_cm is None
