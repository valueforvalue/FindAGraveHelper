"""FaG browser adapter for the unified runner.

Wraps search_fag.search_one_pensioner() into a callable that:
  - Holds the Playwright page
  - Throttles between requests
  - Returns (record_or_list, status_str)

The runner (run_unified.py) injects the result into the
unified_pipeline, which expects either:
  - (dict, str) — single FaG record
  - (list[dict], str) — list of FaG records
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from scripts.search_fag import (
    search_one_pensioner,
    setup_browser,
    warmup_session,
)


log = logging.getLogger("fag_browser")


def make_fag_search_fn(throttle: float = 1.5) -> Callable:
    """Create a fag_search_fn(pensioner, config) closure.

    Holds a single Playwright page for the whole batch. If
    the page fails (e.g. Cloudflare challenge), the function
    may raise; the runner's try/except catches it.

    Returns a closure suitable for UnifiedRunnerConfig.fag_search_fn.
    """
    from playwright.sync_api import sync_playwright
    log.info("Building browser (visible Chromium + playwright-stealth)...")
    pw = sync_playwright().__enter__()
    try:
        browser, ctx, page = setup_browser(pw)
    except Exception:
        pw.stop()
        raise
    warmup_ok = warmup_session(page, log)

    last_request_at = 0.0

    def fag_search(pensioner: dict, config) -> tuple[list, str]:
        """Run FaG search for one pensioner.

        Returns (list_of_candidates, status_str). Empty list means
        no_results/error.
        """
        nonlocal last_request_at

        # Throttle between requests
        now = time.time()
        gap = now - last_request_at
        if last_request_at > 0 and gap < throttle:
            time.sleep(throttle - gap)
        last_request_at = time.time()

        try:
            record = search_one_pensioner(page, pensioner)
        except Exception as e:
            log.warning("FaG search failed for #%d: %s", pensioner.get("id"), e)
            return [], "error"

        # search_one_pensioner returns a state record. We want
        # the candidates inside, not the wrapper.
        candidates = record.get("ranked_candidates", []) or []
        status = record.get("status", "no_results")
        return candidates, status

    return fag_search