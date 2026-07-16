"""FaG browser adapter for the unified runner.

Wraps search_fag.search_one_pensioner() into a callable that:
  - Holds the Playwright page
  - Throttles between requests
  - Periodically resets the browser context (every N records)
    to recover from cumulative state issues (Cloudflare
    stale cookies, memory pressure, etc.)
  - Auto-recovers from Playwright closed-page errors (e.g. "Target
    page, context or browser has been closed") that occur when
    Chromium crashes or is killed externally — without this, every
    subsequent search returns 'error' forever until the process
    restarts.
  - Optionally consults an external RSS watchdog (rss_watchdog.py)
    that can force a browser reset when the Python process exceeds
    a memory threshold (Chromium RSS climbs per navigation).
  - Returns (record_or_list, status_str)

The runner (run_unified.py) injects the result into the
unified_pipeline, which expects either:
  - (dict, str) — single FaG record
  - (list[dict], str) — list of FaG records
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional


from scripts.search_fag import (
    search_one_pensioner,
    setup_browser,
    warmup_session,
)


log = logging.getLogger("fag_browser")


# Substring patterns that indicate the browser/page context died and
# any future call will fail until we reopen. Matched against the
# exception message (case-insensitive). Each entry is a stable signal
# across Playwright versions.
_TARGET_CLOSED_PATTERNS = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "context has been closed",
    "page has been closed",
    "connection has been closed",
    "browser is not connected",
    "context is not connected",
    "page is not closed",
)


def _is_target_closed(exc: BaseException) -> bool:
    """True if the exception indicates the browser/page/context died.

    We can't import the concrete TargetClosedError class reliably
    across Playwright versions, so match on both string patterns and
    isinstance against the public playwright.sync_api.Error class.
    """
    try:
        from playwright.sync_api import Error as PWError
        if isinstance(exc, PWError):
            msg = str(exc).lower()
            return any(p in msg for p in _TARGET_CLOSED_PATTERNS)
    except ImportError:
        pass
    msg = str(exc).lower()
    return any(p in msg for p in _TARGET_CLOSED_PATTERNS)


def make_fag_search_fn(
    throttle: float = 1.5,
    reset_browser_every: int = 250,
    watchdog: Optional["object"] = None,
    max_consecutive_errors: int = 10,
) -> Callable:
    """Create a fag_search_fn(pensioner, config) closure.

    Holds a Playwright page. Every reset_browser_every pensioner
    calls, the browser context is closed and re-opened (new
    cookies, fresh Cloudflare session). This recovers from the
    cumulative state issues that arise on long runs.

    Args:
        throttle: seconds between FaG requests
        reset_browser_every: force-reset browser every N records
        watchdog: optional RSSWatchdog instance. When its
            force_reset_event is set, the browser is reopened at
            the next opportunity (typically the current record).
        max_consecutive_errors: after this many in-a-row 'error'
            results, give up and re-raise the last exception so the
            outer loop can stop the run rather than thrash.

    Returns a closure suitable for UnifiedRunnerConfig.fag_search_fn.
    """
    from playwright.sync_api import sync_playwright

    log.info(
        "Building browser (visible Chromium + playwright-stealth, "
        "reset every %d records [250 = conservative for memory leak "
        "prevention], target-closed auto-recovery=enabled)...",
        reset_browser_every,
    )
    pw = sync_playwright().__enter__()
    state = {
        "pw": pw,
        "browser": None,
        "ctx": None,
        "page": None,
        "last_request_at": 0.0,
        "request_count": 0,
        "consecutive_errors": 0,
        "lock": threading.Lock(),
    }

    def _open_browser():
        """Open a fresh browser context (used on init + after reset).

        Tries to close any prior context AND browser cleanly first
        (the previous version only closed the browser, leaking the
        context ref). On failure logs and continues — opening a
        fresh one will still work.
        """
        # Close in order: page, context, then browser. Each step
        # may itself raise; swallow so we still drop the references
        # and let GC reclaim them.
        for attr in ("page", "ctx", "browser"):
            obj = state.get(attr)
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
            state[attr] = None
        # Encourage the Python interpreter to free cycle refs
        # before we spawn a new Chromium (Chromium startup holds
        # a transient RSS spike, easier to do this on a small heap).
        import gc as _gc
        _gc.collect()
        try:
            browser, ctx, page = setup_browser(state["pw"])
        except Exception as e:
            log.error("Failed to open browser: %s", e)
            raise
        warmup_session(page, log)
        state["browser"] = browser
        state["ctx"] = ctx
        state["page"] = page
        log.info("Browser ready.")

    _open_browser()

    def _maybe_recover(exc: BaseException) -> bool:
        """Try to reopen the browser after a closed-target failure.

        Returns True if recovery succeeded (caller may retry).
        Returns False if recovery itself failed — caller should
        give up on this record.
        """
        try:
            log.warning("Target closed, attempting browser reopen: %s", exc)
            _open_browser()
            return state["page"] is not None
        except Exception as reopen_exc:
            log.error("Browser reopen failed: %s", reopen_exc)
            return False

    def _maybe_watchdog_reset():
        """If the watchdog says RSS is too high, force a browser reset."""
        if watchdog is None:
            return
        try:
            if watchdog.should_force_reset():
                log.warning(
                    "RSS watchdog triggered browser reset (rss=%d MB)",
                    watchdog.current_rss_mb(),
                )
                watchdog.clear_force_reset()
                try:
                    _open_browser()
                except Exception as e:
                    log.error("Watchdog-triggered reopen failed: %s", e)
        except Exception as e:
            log.debug("watchdog check failed: %s", e)

    def fag_search(pensioner: dict, config) -> tuple[list, str]:
        """Run FaG search for one pensioner.

        Returns (list_of_candidates, status_str). Empty list means
        no_results/error.

        Behavior on browser death:
          - First closed-target error mid-search: reopen, return
            error (caller flushes error record), do NOT retry.
            Subsequent calls will use the new browser cleanly.
          - 3+ consecutive errors: still returns error but logs
            prominently.
          - 10+ consecutive errors: re-raise to let the outer
            loop terminate the run (better than spinning for hours).
        """
        with state["lock"]:
            # Periodic browser reset to recover from long-run issues
            if state["request_count"] > 0 and (
                state["request_count"] % reset_browser_every == 0
            ):
                log.warning(
                    "Periodic browser reset (after %d requests)",
                    state["request_count"],
                )
                try:
                    _open_browser()
                except Exception as e:
                    log.error("Periodic browser reset failed: %s", e)

            # RSS-triggered reset (if a watchdog is attached)
            _maybe_watchdog_reset()

            state["request_count"] += 1

            # Throttle between requests
            now = time.time()
            gap = now - state["last_request_at"]
            if state["last_request_at"] > 0 and gap < throttle:
                time.sleep(throttle - gap)
            state["last_request_at"] = time.time()

            try:
                record = search_one_pensioner(state["page"], pensioner)
            except Exception as e:
                state["consecutive_errors"] += 1
                if _is_target_closed(e):
                    # Try one browser reopen so the NEXT record can
                    # succeed. Don't retry the same record inline —
                    # doing so can double-write if the state-flush
                    # path already wrote something before the death.
                    recovered = _maybe_recover(e)
                    log.warning(
                        "FaG search failed for #%d (target closed, "
                        "recovery=%s, consecutive=%d): %s",
                        pensioner.get("id"), recovered,
                        state["consecutive_errors"], e,
                    )
                else:
                    log.warning(
                        "FaG search failed for #%d (consecutive=%d): %s",
                        pensioner.get("id"), state["consecutive_errors"], e,
                    )
                if (
                    max_consecutive_errors > 0
                    and state["consecutive_errors"] >= max_consecutive_errors
                ):
                    log.error(
                        "Aborting: %d consecutive FaG errors; "
                        "raising to stop the run",
                        state["consecutive_errors"],
                    )
                    raise
                return [], "error"

            # search_one_pensioner returns a state record. We want
            # the candidates inside, not the wrapper.
            candidates = record.get("ranked_candidates", []) or []
            status = record.get("status", "no_results")
            if status == "error":
                # Internal status='error' from search_fag (e.g. CAPTCHA,
                # parse failure); not a target-closed situation.
                state["consecutive_errors"] += 1
                log.info(
                    "FaG status=error for #%d. "
                    "strategies_run=%s, consecutive=%d",
                    pensioner.get("id"),
                    record.get("strategies_run", []),
                    state["consecutive_errors"],
                )
            else:
                state["consecutive_errors"] = 0
            return candidates, status

    return fag_search
