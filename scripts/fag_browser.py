"""FaG browser adapter for the unified runner.

Wraps search_fag.search_one_pensioner() into a callable that:
  - Holds the Playwright page
  - Throttles between requests
  - Periodically resets the browser context (every N records)
    to recover from cumulative state issues (Cloudflare
    stale cookies, memory pressure, etc.)
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


def make_fag_search_fn(
    throttle: float = 1.5,
    reset_browser_every: int = 500,
) -> Callable:
    """Create a fag_search_fn(pensioner, config) closure.

    Holds a Playwright page. Every reset_browser_every pensioner
    calls, the browser context is closed and re-opened (new
    cookies, fresh Cloudflare session). This recovers from the
    cumulative state issues that arise on long runs.

    Returns a closure suitable for UnifiedRunnerConfig.fag_search_fn.
    """
    from playwright.sync_api import sync_playwright

    log.info(
        "Building browser (visible Chromium + playwright-stealth, "
        "reset every %d records)...",
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
        "lock": threading.Lock(),
    }

    def _open_browser():
        """Open a fresh browser context (used on init + after reset)."""
        if state["browser"] is not None:
            try:
                state["browser"].close()
            except Exception:
                pass
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

    def fag_search(pensioner: dict, config) -> tuple[list, str]:
        """Run FaG search for one pensioner.

        Returns (list_of_candidates, status_str). Empty list means
        no_results/error.
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
                _open_browser()

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
                log.warning(
                    "FaG search failed for #%d: %s",
                    pensioner.get("id"), e,
                )
                return [], "error"

            # search_one_pensioner returns a state record. We want
            # the candidates inside, not the wrapper.
            candidates = record.get("ranked_candidates", []) or []
            status = record.get("status", "no_results")
            # If status=error, log the underlying issue at INFO level
            if status == "error":
                err_keys = [
                    k for k in record
                    if k not in ("pensioner_id", "pensioner_name",
                                 "pensioner_first", "pensioner_last",
                                 "ranked_candidates", "best_score",
                                 "strategies_run", "timestamp")
                ]
                log.info(
                    "FaG error for #%d: empty candidates. "
                    "strategies_run=%s",
                    pensioner.get("id"),
                    record.get("strategies_run", []),
                )
            return candidates, status

    return fag_search