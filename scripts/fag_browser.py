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
    build_browser,
    warmup_session,
    BASE_URL,
)


log = logging.getLogger("fag_browser")


def make_fag_search_fn(throttle: float = 1.5) -> Callable:
    """Create a fag_search_fn(pensioner, config) closure.

    Holds a single Playwright page for the whole batch. If
    the page fails (e.g. Cloudflare challenge), the function
    may raise; the runner's try/except catches it.

    Returns a closure suitable for UnifiedRunnerConfig.fag_search_fn.
    """
    log.info("Building browser...")
    browser, ctx, page = build_browser(log)
    warmup_ok = warmup_session(page, log)

    last_request_at = 0.0

    def fag_search(pensioner: dict, config) -> tuple[Optional[dict], str]:
        """Run FaG search for one pensioner.

        Returns (record_dict_or_None, status_str).
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
            return None, "error"

        status = record.get("status", "no_results")
        # Return the FaG-searched record as-is (legacy FaG-only format).
        # The unified runner sees it and stores both formats
        # (ranked_candidates + fag_records).
        return record, status

    return fag_search