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


def test_browser_session_imports():
    """BrowserSession can be imported."""
    from scripts.fag.browser_session import BrowserSession
    assert BrowserSession is not None
