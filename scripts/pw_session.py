"""Production fix: periodic Playwright session reset for memory leak.

Add to fag_browser.py or call from the runner periodically.

The fix: every N records, tear down sync_playwright() entirely
and create a fresh one. This destroys the event loop and all
accumulated asyncio Tasks.

Use in fag_browser.py's _open_browser() equivalent, or as a
wrapper that replaces the long-lived pw instance.
"""

from __future__ import annotations

import gc
import logging
from typing import Optional

log = logging.getLogger("pw_reset")


class PlaywrightSession:
    """Manages a sync_playwright() session with periodic hard reset.

    Usage:
        session = PlaywrightSession(
            reset_every_n=500,  # hard-reset session every 500 records
            headless=False,
        )
        session.start()
        try:
            for pensioner in pensioners:
                page = session.page
                result = search_one_pensioner(page, pensioner)
                session.record_processed()  # increments counter
        finally:
            session.stop()
    """

    def __init__(
        self,
        reset_every_n: int = 500,
        headless: bool = False,
        user_agent: Optional[str] = None,
    ):
        self.reset_every_n = reset_every_n
        self.headless = headless
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._count = 0

    @property
    def page(self):
        return self._page

    @property
    def context(self):
        return self._ctx

    def start(self):
        """Initialize the Playwright session (call once at the start)."""
        self._reset_session()

    def stop(self):
        """Tear down (call at end of run)."""
        self._close_all()
        self._pw = None

    def record_processed(self):
        """Call after each pensioner. Triggers hard reset at threshold."""
        self._count += 1
        if self._count % self.reset_every_n == 0:
            log.info(
                "Hard-resetting Playwright session after %d records "
                "(frees accumulated asyncio Tasks + Chromium heap)",
                self._count,
            )
            self._reset_session()

    def force_reset(self):
        """Reset immediately regardless of counter."""
        log.info("Forced Playwright session reset (RSS watchdog or manual)")
        self._reset_session()

    # ── internals ──────────────────────────────────────────

    def _close_all(self):
        for attr in ("_page", "_ctx", "_browser"):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        if self._pw is not None:
            try:
                self._pw.__exit__(None, None, None)
            except Exception:
                pass
            self._pw = None
            self._playwright = None
        gc.collect()

    def _reset_session(self):
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth

        self._close_all()

        _cm = sync_playwright()
        _playwright = _cm.__enter__()
        self._pw = _cm
        self._playwright = _playwright

        try:
            browser = _playwright.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                timezone_id="America/Chicago",
            )
            page = ctx.new_page()
            try:
                Stealth().apply_stealth_sync(ctx)
            except Exception:
                Stealth().apply_stealth_sync(page)

            self._browser = browser
            self._ctx = ctx
            self._page = page
            log.info("Playwright session ready (hard reset complete).")
        except Exception:
            self._close_all()
            raise
