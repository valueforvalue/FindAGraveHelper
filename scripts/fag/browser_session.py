"""BrowserSession: single owner for Playwright browser lifecycle.

Consolidates the browser lifecycle from fag_browser.py (closure-based
state dict) and pw_session.py (PlaywrightSession class) into one deep
module that owns:

  - Stealth application at context level (prevents per-page CDP leak)
  - Warmup (homepage visit to prime Cloudflare cookies)
  - Gated navigation through RequestGate
  - Reset: page→context→browser→Playwright teardown (reverse order)
  - Target-closed recovery
  - RSS-triggered and periodic reset
  - Context manager (__enter__ / __exit__) for safe cleanup

Usage:
    with BrowserSession.open(throttle=2.5) as session:
        for pensioner in batch:
            candidates, status = session.search(pensioner)
"""
from __future__ import annotations

import gc
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("browser_session")


class BrowserSession:
    """Owns a Playwright Chromium instance with stealth + warmup.

    Callers acquire the session, run searches, and close. The session
    manages its own lock, throttle, reset cadence, and recovery.
    """

    def __init__(
        self,
        throttle: float = 2.5,
        reset_every: int = 250,
        headless: bool = False,
        state_filter: str = "OK",
        auto_relax: bool = False,
        max_consecutive_errors: int = 10,
        user_agent: str | None = None,
    ) -> None:
        self.throttle = throttle
        self.reset_every = max(reset_every, 1)  # prevent modulo-zero
        self.headless = headless
        self.state_filter = state_filter
        self.auto_relax = auto_relax
        self.max_consecutive_errors = max_consecutive_errors
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Internal state
        self._pw_cm: Any = None
        self._playwright: Any = None
        self._browser: Any = None
        self._ctx: Any = None
        self._page: Any = None
        self._lock = threading.Lock()
        self._request_count: int = 0
        self._consecutive_errors: int = 0
        self._last_request_at: float = 0.0
        self._started: bool = False

    # ----------------------------------------------------------
    # Context manager
    # ----------------------------------------------------------

    @classmethod
    def open(cls, **kwargs: Any) -> "BrowserSession":
        """Factory: create and start a session. Use as context manager."""
        session = cls(**kwargs)
        session.start()
        return session

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------

    def start(self) -> None:
        """Initialize Playwright + apply leak fix + open first browser."""
        if self._started:
            return

        # Apply Playwright memory leak fix before any Playwright import
        try:
            from scripts.fag.playwright_leak_fix import apply_playwright_leak_fix

            if apply_playwright_leak_fix():
                log.info("Applied Playwright Python memory-leak fix.")
        except Exception as e:
            log.warning("Playwright leak fix not applied: %s", e)

        self._open_browser()
        self._started = True

    def close(self) -> None:
        """Tear down in reverse order: page → context → browser → Playwright."""
        self._started = False
        for attr in ("_page", "_ctx", "_browser"):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        if self._pw_cm is not None:
            try:
                self._pw_cm.__exit__(None, None, None)
            except Exception:
                pass
            self._pw_cm = None
            self._playwright = None
        gc.collect()
        log.info("BrowserSession closed (page→context→browser→Playwright).")

    def reset(self) -> None:
        """Hard reset: close everything and open fresh browser."""
        log.info("BrowserSession hard reset.")
        self.close()
        self._started = False
        self.start()

    # ----------------------------------------------------------
    # Search
    # ----------------------------------------------------------

    def search(
        self, pensioner: dict[str, Any], *, state_filter: str | None = None
    ) -> tuple[list[dict[str, Any]], str]:
        """Run FaG search for one pensioner. Thread-safe.

        Args:
            pensioner: pensioner dict with first_name, last_name, etc.
            state_filter: override session state_filter (None = use session default).

        Returns (candidates_list, status_str).
        """
        from scripts.fag.search import search_one_pensioner

        sf = state_filter if state_filter is not None else self.state_filter

        with self._lock:
            self._maybe_periodic_reset()

            self._request_count += 1
            self._throttle_wait()

            try:
                record = search_one_pensioner(
                    self._page, pensioner,
                    throttle_seconds=self.throttle,
                    state_filter=sf,
                )
            except Exception as e:
                self._consecutive_errors += 1
                if self._is_target_closed(e):
                    log.warning("Target closed; attempting browser reopen.")
                    try:
                        self._open_browser()
                    except Exception as reopen_exc:
                        log.error("Browser reopen failed: %s", reopen_exc)
                if (
                    self.max_consecutive_errors > 0
                    and self._consecutive_errors >= self.max_consecutive_errors
                ):
                    log.error("Aborting: %d consecutive errors.", self._consecutive_errors)
                    raise
                return [], "error"

            # Auto-relax (env-controlled, OK→US broadening)
            if (
                self.auto_relax
                and self.state_filter == "OK"
                and record.get("status") != "auto_accept"
            ):
                record = self._try_auto_relax(pensioner, record)

            candidates = record.get("ranked_candidates", []) or []
            status = record.get("status", "no_results")
            if status == "error":
                self._consecutive_errors += 1
            else:
                self._consecutive_errors = 0
            return candidates, status

    @property
    def page(self) -> Any:
        """Current Playwright page (for direct access in migration)."""
        return self._page

    @property
    def request_count(self) -> int:
        return self._request_count

    # ----------------------------------------------------------
    # Internal
    # ----------------------------------------------------------

    def _open_browser(self) -> None:
        """Open fresh browser + context + page with stealth + warmup."""
        from playwright.sync_api import sync_playwright
        from scripts.fag.search import setup_browser, warmup_session

        # Close any existing first
        for attr in ("_page", "_ctx", "_browser"):
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        if self._pw_cm is not None:
            try:
                self._pw_cm.__exit__(None, None, None)
            except Exception:
                pass
            self._pw_cm = None
            self._playwright = None

        gc.collect()

        self._pw_cm = sync_playwright()
        self._playwright = self._pw_cm.__enter__()

        try:
            browser, ctx, page = setup_browser(self._playwright)
        except Exception:
            self._pw_cm.__exit__(None, None, None)
            self._pw_cm = None
            self._playwright = None
            raise

        warmup_session(page, log)
        self._browser = browser
        self._ctx = ctx
        self._page = page
        log.info("BrowserSession browser ready.")

    def _throttle_wait(self) -> None:
        """Wait until throttle interval has passed since last request."""
        now = time.time()
        gap = now - self._last_request_at
        if self._last_request_at > 0 and gap < self.throttle:
            time.sleep(self.throttle - gap)
        self._last_request_at = time.time()

    def _maybe_periodic_reset(self) -> None:
        """Reset browser periodically to prevent cumulative state issues."""
        if self._request_count > 0 and self._request_count % self.reset_every == 0:
            log.warning("Periodic browser reset (after %d requests).", self._request_count)
            try:
                self._open_browser()
            except Exception as e:
                log.error("Periodic reset failed: %s", e)

    def _try_auto_relax(
        self, pensioner: dict[str, Any], ok_record: dict[str, Any]
    ) -> dict[str, Any]:
        """Attempt US-wide search and return broader if better."""
        from scripts.fag.search import search_one_pensioner

        log.info("Auto-relax: broadening #%d to US.", pensioner.get("id"))
        try:
            broader = search_one_pensioner(
                self._page, pensioner,
                throttle_seconds=self.throttle,
                state_filter="US",
            )
        except Exception as e:
            log.warning("Auto-relax US search failed for #%d: %s", pensioner.get("id"), e)
            return ok_record

        ok_cands = ok_record.get("ranked_candidates", []) or []
        us_cands = broader.get("ranked_candidates", []) or []
        if len(us_cands) > len(ok_cands):
            log.info("Auto-relax: US returned %d > OK's %d; using US.",
                     len(us_cands), len(ok_cands))
            return broader
        log.info("Auto-relax: US returned %d <= OK's %d; keeping OK.",
                 len(us_cands), len(ok_cands))
        return ok_record

    @staticmethod
    def _is_target_closed(exc: BaseException) -> bool:
        """True if the exception indicates the browser page/context died."""
        msg = str(exc).lower()
        return (
            "target closed" in msg
            or "browser closed" in msg
            or "page closed" in msg
            or "context closed" in msg
        )
