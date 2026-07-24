"""Spouse post-pass (Slice 5).

Moves the inline spouse post-pass block from
`scripts/pipeline/run_unified.py` (lines ~1013–1030) into a
post-pass module. Calls
`scripts.cgr.spouse_compare.annotate_records_via_session` to
navigate the live browser, fetch spouse sections from FaG
memorial pages, and emit SpouseMatch observations to the store.

Opt-in via `FAG_SCRAPE_SPOUSE=1|true|yes` (same env-var gate as
the original inline code). When disabled, returns skipped=True
without touching the store. Non-fatal: exceptions are logged and
reflected in stats.errors.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts.post_pass.types import BasePassConfig, PostPassStats


@dataclass(frozen=True)
class SpouseConfig(BasePassConfig):
    """Configuration for the spouse post-pass.

    `enabled` mirrors the FAG_SCRAPE_SPOUSE env var.
    `browser_session` is the BrowserSession to navigate with.
    `results_path` is the path to state.jsonl (which the helper
    reads to find pensioner rows).
    """

    enabled: bool = False
    browser_session: Any = None
    results_path: Path | None = None


class _LoggerLike(Protocol):
    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...


def run(
    store: Any,
    *,
    config: SpouseConfig,
    run_id: str,
    log: _LoggerLike,
) -> PostPassStats:
    """Run the spouse post-pass.

    Args:
        store: Blackboard store for observation persistence.
        config: Pass config (enabled flag, browser_session, results_path).
        run_id: Run identifier (unused; kept for signature parity).
        log: Logger for non-fatal warnings.

    Returns:
        PostPassStats with `name="spouse"`. `skipped=True` when
        disabled. When enabled, carries `matched`, `attempted`,
        `errors` from the underlying helper.
    """
    del run_id  # currently unused; the helper uses its own PostPassObserver
    started = time.monotonic()
    if not config.enabled:
        return PostPassStats(
            name="spouse",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    try:
        from scripts.cgr.spouse_compare import annotate_records_via_session

        log.info("Spouse post-pass: starting (may take a while)...")
        raw_stats = annotate_records_via_session(
            results_path=config.results_path,
            session=config.browser_session,
            store=store,
        )
        log.info(
            "Spouse post-pass: matched=%d, attempted=%d, errors=%d",
            raw_stats.get("matched", 0),
            raw_stats.get("total_attempted", 0),
            raw_stats.get("errors", 0),
        )
        return PostPassStats(
            name="spouse",
            matched=raw_stats.get("matched", 0),
            attempted=raw_stats.get("total_attempted", 0),
            errors=raw_stats.get("errors", 0),
            duration_s=time.monotonic() - started,
        )
    except Exception as exc:
        log.warning("Spouse post-pass failed (non-fatal): %s", exc)
        return PostPassStats(
            name="spouse",
            skipped=True,
            errors=1,
            duration_s=time.monotonic() - started,
            notes=f"exception: {exc}",
        )


def config_from(parent: Any, *, browser_session: Any, results_path: Path | None) -> SpouseConfig:
    """Build SpouseConfig from the environment + run context.

    Reads FAG_SCRAPE_SPOUSE; the runner config does not own this
    flag (it's env-only). `browser_session` and `results_path` are
    passed by the runner (per-run, not config fields).
    """
    import os

    enabled = os.environ.get("FAG_SCRAPE_SPOUSE", "").lower() in ("1", "true", "yes")
    return SpouseConfig(
        enabled=enabled,
        browser_session=browser_session,
        results_path=results_path,
    )