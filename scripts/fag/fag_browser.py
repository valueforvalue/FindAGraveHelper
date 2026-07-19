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
import os
import threading
import time
from typing import Callable, Optional


from scripts.fag.search import search_one_pensioner
from scripts.fag.search import setup_browser, warmup_session


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


def _should_broaden(record: dict, threshold: float = 0.3) -> bool:
    """True when the narrowed FaG search returned no useful candidate.

    Used by auto-relax (issue #15) to decide whether to retry the
    search with a broader state_filter. 'No useful candidate' means:
      - status is not auto_accept, AND
      - either no candidates at all, OR
      - no candidate scored above `threshold` (default 0.3).

    Args:
        record: the dict returned by search_one_pensioner
            (has 'ranked_candidates', 'status', etc.).
        threshold: minimum per-candidate score to count as 'useful'.
            The strategy ladder weights names, dates, and burial
            location. A score >= 0.3 means we found a candidate
            whose name matches at least partially. Below that,
            candidates are typically modern same-name people who
            happened to rank by name.

    Returns True if broadening to US (or global) is worth attempting.
    """
    if record.get("status") == "auto_accept":
        return False
    cands = record.get("ranked_candidates", []) or []
    if not cands:
        return True
    for c in cands:
        score = c.get("score")
        if score is None:
            continue
        try:
            if float(score) >= threshold:
                return False
        except (TypeError, ValueError):
            continue
    return True


def make_fag_search_fn(
    throttle: float = 2.5,
    reset_browser_every: int = 250,
    watchdog: Optional["object"] = None,
    max_consecutive_errors: int = 10,
    state_filter: Optional[str] = None,
    session: Any = None,  # BrowserSession (Phase W3)
) -> Callable:
    """[DEPRECATED] Create a fag_search_fn closure.

    Kept for leftover_investigation.py and retry_errors.py.
    New code should use BrowserSession directly.

    Holds a Playwright page. Every reset_browser_every pensioner
    calls, the browser context is closed and re-opened (new
    cookies, fresh Cloudflare session). This recovers from the
    cumulative state issues that arise on long runs.

    Args:
        throttle: seconds between FaG requests
        reset_browser_every: force-reset browser every N records
        watchdog: optional RSSWatchdog instance.
        max_consecutive_errors: after this many in-a-row errors, abort.
        state_filter: FaG locationId scope.
        session: optional BrowserSession for delegate mode.

    Returns a closure suitable for UnifiedRunnerConfig.fag_search_fn.
    """
    # Fast path: delegate to BrowserSession (Phase W3)
    if session is not None:
        log.info("Using BrowserSession delegate (closure wraps session.search).")
        def _session_search(pensioner: dict, config) -> tuple[list, str]:
            return session.search(pensioner)
        return _session_search

    # Apply the Playwright Python memory leak fix BEFORE any Playwright
    # import path that creates tasks. See:
    #   github.com/microsoft/playwright/issues/15400
    #   comments by laztheripper (2026-06): __pw_stack__ and
    #   __pw_stack_trace__ pin Python frames in the asyncio event loop,
    #   accumulating gigabytes over hours of navigations. The fix is to
    #   replace these with empty lists (the captured stack traces were
    #   debugging hints, not load-bearing). We monkey-patch the relevant
    #   method on SyncBase before sync_playwright() is constructed.
    try:
        from scripts.fag.playwright_leak_fix import apply_playwright_leak_fix
        applied = apply_playwright_leak_fix()
        if applied:
            log.info("Applied Playwright Python memory-leak fix "
                     "(suppresses __pw_stack__ frame pinning).")
    except Exception as e:
        # Best-effort: if the fix module can't load (e.g. older
        # Playwright), the run continues without it. The other
        # mitigations (RSS watchdog, browser reset) still apply.
        log.warning("Playwright leak fix not applied: %s", e)

    from playwright.sync_api import sync_playwright

    log.info(
        "Building browser (visible Chromium + playwright-stealth, "
        "reset every %d records [250 = conservative for memory leak "
        "prevention], target-closed auto-recovery=enabled)...",
        reset_browser_every,
    )
    pw_cm = sync_playwright()
    pw = pw_cm.__enter__()
    state = {
        "pw_cm": pw_cm,
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
        """Open a fresh browser + Playwright session (used on init + after reset).

        Closes the old browser/context/page AND tears down the
        sync_playwright() session entirely. This destroys the
        asyncio event loop, freeing all accumulated Task objects
        (see #15400 — ~220 Tasks/pensioner pinned in loop._tasks).

        On failure logs and continues — opening a fresh one will
        still work.
        """
        # 1. Close browser layer: page, context, then browser.
        for attr in ("page", "ctx", "browser"):
            obj = state.get(attr)
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass
            state[attr] = None
        # 2. Tear down the Playwright session (kills event loop + all Tasks).
        old_cm = state.get("pw_cm")
        if old_cm is not None:
            try:
                old_cm.__exit__(None, None, None)
            except Exception:
                pass
            state["pw_cm"] = None
            state["pw"] = None
        # 3. Encourage GC before Chromium startup (transient RSS spike).
        import gc as _gc
        _gc.collect()
        # 4. Create a fresh Playwright session (new event loop, clean slate).
        new_cm = sync_playwright()
        state["pw_cm"] = new_cm
        state["pw"] = new_cm.__enter__()
        log.info("Playwright session reset (event loop + tasks freed).")
        # 5. Open browser in the new session.
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
                record = search_one_pensioner(
                    state["page"], pensioner,
                    throttle_seconds=throttle,
                    state_filter=state_filter,
                )
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

            # Auto-relax state filter (issue #15). When the
            # narrowed search returns nothing useful (no
            # high-score candidate AND not auto_accept), try the
            # broader scope before giving up. Opt-in via env var
            # FAG_AUTO_RELAX=1. Skipped silently otherwise.
            # Throttle-gated: only runs when the search took the
            # full timeout window, to avoid penalising fast searches.
            if (
                os.environ.get("FAG_AUTO_RELAX", "").strip() in ("1", "true", "yes")
                and state_filter == "OK"
                and record.get("status") != "auto_accept"
                and _should_broaden(record)
            ):
                log.info(
                    "Auto-relax: broadening #%d to US (OK returned no high-score)",
                    pensioner.get("id"),
                )
                try:
                    broader_record = search_one_pensioner(
                        state["page"], pensioner,
                        throttle_seconds=throttle,
                        state_filter="US",
                    )
                except Exception as e:
                    log.warning("Auto-relax US search failed for #%d: %s",
                                pensioner.get("id"), e)
                    broader_record = None
                if broader_record is not None:
                    ok_cands = record.get("ranked_candidates", []) or []
                    us_cands = broader_record.get("ranked_candidates", []) or []
                    if len(us_cands) > len(ok_cands):
                        record = broader_record
                        log.info("Auto-relax: US returned %d > OK's %d; using US",
                                 len(us_cands), len(ok_cands))
                    else:
                        log.info("Auto-relax: US returned %d <= OK's %d; keeping OK",
                                 len(us_cands), len(ok_cands))

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
