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
        enforce_throttle_floor: bool = True,
    ) -> None:
        # L1 (CONTEXT.md) — throttle is the only thing between us
        # and a 30-minute Cloudflare backoff. The 2.5s floor is the
        # safe default; lowering below it re-introduces the 1015
        # rate-limit risk (per 2026-07-16 live monitoring). For
        # explicit operator opt-in (slice runs, low-volume A/B
        # tests) the floor can be relaxed with a warning. Issue
        # #61: this knob lets the operator run a 50-record slice
        # at 1.5s without re-introducing the historical rate-limit.
        if throttle < 2.5:
            if enforce_throttle_floor:
                raise ValueError(
                    f"BrowserSession throttle {throttle}s is below the 2.5s "
                    f"L1 floor. Pass enforce_throttle_floor=False to relax "
                    f"(emits a warning, see issue #61)."
                )
            import warnings
            warnings.warn(
                f"BrowserSession throttle {throttle}s is below the L1 floor "
                f"of 2.5s. Sustained < 2.5s throttle re-introduces the "
                f"Cloudflare 1015 risk that L1 was raised to fix "
                f"(2026-07-16 live monitoring).",
                DeprecationWarning,
                stacklevel=2,
            )
            log.warning(
                "BrowserSession throttle=%ss below L1 floor (2.5s); "
                "issue #61 operator opt-in. Watch for 1015 backoff.",
                throttle,
            )
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

        # Mock FaG: when set, intercepts all FaG search URLs
        self._mock_fag_fixture: str | None = None

    # ----------------------------------------------------------
    # Context manager
    # ----------------------------------------------------------

    @classmethod
    def open(cls, **kwargs: Any) -> "BrowserSession":
        """Factory: create and start a session. Use as context manager."""
        session = cls(**kwargs)
        session.start()
        return session

    @classmethod
    def from_config(
        cls, config: Any, **overrides: Any
    ) -> "BrowserSession":
        """Factory: build a session from a BrowserConfig (Slice 9).

        Reads all BrowserSession.__init__ kwargs from the
        BrowserConfig dataclass. Per-kwarg `overrides` win over
        the config values (useful for tests).
        """
        from scripts.fag.browser_config import BrowserConfig

        if not isinstance(config, BrowserConfig):
            raise TypeError(
                f"from_config requires BrowserConfig, got {type(config).__name__}"
            )
        kwargs = {
            "throttle": config.throttle,
            "reset_every": config.reset_every,
            "headless": config.headless,
            "state_filter": config.state_filter,
            "auto_relax": config.auto_relax,
            "max_consecutive_errors": config.max_consecutive_errors,
            "user_agent": config.user_agent,
            "enforce_throttle_floor": config.enforce_throttle_floor,
        }
        kwargs.update(overrides)
        session = cls(**kwargs)
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
        self,
        pensioner: dict[str, Any],
        *,
        state_filter: str | None = None,
        strategy_name: str | None = None,
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
                    strategy_name=strategy_name,
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

            # Issue #80: auto-relax removed. The plan ladder carries
            # broadening responsibility; per-plan results are preserved
            # without a US re-search.

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
    # Mock FaG (issue #63)
    # ----------------------------------------------------------

    def enable_mock_fag(self, fixture_path: str) -> None:
        """Intercept all FaG search URLs and return fixture HTML.

        After calling this, every request to
        ``**/findagrave.com/memorial/search**`` is fulfilled with
        the contents of *fixture_path* instead of hitting the real
        server. The fixture should be a saved HTML page from a
        prior real FaG search result.

        Safe to call multiple times (updates the fixture inline).
        Call :meth:`disable_mock_fag` to remove the route.
        """
        from pathlib import Path
        body = Path(fixture_path).read_bytes()
        self._mock_fag_fixture = fixture_path

        async def _handle(route: Any) -> None:
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=body,
            )
        self._page.route("**/findagrave.com/memorial/search**", _handle)
        log.info("Mock FaG enabled: fixture=%s (%d bytes)", fixture_path, len(body))

    def disable_mock_fag(self) -> None:
        """Remove the mock FaG route."""
        try:
            self._page.unroute("**/findagrave.com/memorial/search**")
        except Exception as e:
            log.debug("No mock FaG route to remove: %s", e)
        self._mock_fag_fixture = None
        log.info("Mock FaG disabled.")

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

        # Re-apply mock FaG route if it was active before reset
        if self._mock_fag_fixture:
            self.enable_mock_fag(self._mock_fag_fixture)

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

    def _try_auto_relax_engine(
        self,
        engine: Any,
        page: Any,
        ctx: Any,
        ok_result: dict[str, Any],
        throttle_fn: Any = None,
    ) -> dict[str, Any]:
        """Engine-flow counterpart of `_try_auto_relax`.

        Runs a second `default_search_one` call against the engine
        with a fresh SearchContext whose state is forced to "US",
        then keeps the result with more candidates. Mirrors the
        OK→US broadening that the legacy `search_one_pensioner`
        auto-relax does; issue #61 keeps the semantics in the
        engine path so the Blackboard scheduler inherits the same
        behavior as the legacy god-loop.
        """
        from scripts.search.context import SearchContext
        from scripts.search.engine import default_search_one

        try:
            us_ctx = SearchContext(
                first=ctx.first,
                middle=ctx.middle,
                last=ctx.last,
                birth_year=ctx.birth_year,
                death_year=ctx.death_year,
                state="US",
                extras=dict(ctx.extras),
            )
            # Throttle discipline: honor the per-strategy gate
            # if the caller passed one; otherwise fall back to
            # the session's per-pensioner `_throttle_wait`.
            if throttle_fn is not None:
                try:
                    throttle_fn()
                except Exception:
                    pass
            else:
                self._throttle_wait()
            us_result = default_search_one(
                engine, page=page, ctx=us_ctx, throttle_fn=throttle_fn
            )
        except Exception as e:
            log.warning("Auto-relax engine US search failed: %s", e)
            return ok_result

        ok_n = len(ok_result.get("candidates", []) or [])
        us_n = len(us_result.get("candidates", []) or [])
        if us_n > ok_n:
            log.info("Auto-relax engine: US returned %d > OK's %d; using US.",
                     us_n, ok_n)
            return us_result
        log.info("Auto-relax engine: US returned %d <= OK's %d; keeping OK.",
                 us_n, ok_n)
        return ok_result

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

    # ----------------------------------------------------------
    # Progress overlay (issue #70)
    # ----------------------------------------------------------

    def show_progress_overlay(
        self,
        pensioner_name: str = "",
        pensioner_idx: int = 0,
        pensioner_total: int = 0,
        strategy: str = "",
        elapsed_s: float = 0.0,
        eta_s: float = 0.0,
    ) -> None:
        """Inject a fixed-position progress overlay into the page.

        Call after page load, before parsing — must not interfere
        with FaG page parsing. The overlay is a small div in the
        top-right corner showing current progress.
        """
        try:
            self._page.evaluate(
                """(function() {
                    var el = document.getElementById('_rpiv_progress');
                    if (!el) {
                        el = document.createElement('div');
                        el.id = '_rpiv_progress';
                        el.style.cssText = [
                            'position:fixed; top:10px; right:10px; z-index:99999;',
                            'background:rgba(0,0,0,0.78); color:#eee;',
                            'padding:8px 14px; border-radius:6px;',
                            'font:12px/1.4 Consolas,monospace;',
                            'pointer-events:none; max-width:320px;',
                        ].join('');
                        document.body.appendChild(el);
                    }
                    el.innerHTML = arguments[0];
                })""",
                f"{pensioner_name or '...'} "
                f"({pensioner_idx}/{pensioner_total})<br>"
                f"{strategy or '...'}<br>"
                f"elapsed {elapsed_s:.0f}s"
                + (f"  ETA ~{eta_s:.0f}s" if eta_s else ""),
            )
        except Exception:
            pass

    def hide_progress_overlay(self) -> None:
        """Remove the progress overlay from the page."""
        try:
            self._page.evaluate(
                """(function() {
                    var el = document.getElementById('_rpiv_progress');
                    if (el) el.remove();
                })()"""
            )
        except Exception:
            pass
