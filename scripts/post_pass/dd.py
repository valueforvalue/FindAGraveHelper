"""DixieData post-pass (Slice 4).

Moves the inline DD post-pass block from
`scripts/pipeline/run_unified.py` (lines ~975–1010) into a
post-pass module. Loads the DD index, iterates state rows,
emits DixieDataMatch observations via PostPassObserver, and
writes them to the Blackboard store.

Slice 4 behavior is preserved byte-for-byte: same env-var gate
(`DIXIEDATA_DB` or `DIXIEDATA_ZIP_BACKUP`), same non-fatal
exception handling, same log message.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts.post_pass.types import BasePassConfig, PostPassStats


@dataclass(frozen=True)
class DDConfig(BasePassConfig):
    """Configuration for the DixieData post-pass.

    `db_path` and `zip_path` mirror the DIXIEDATA_DB and
    DIXIEDATA_ZIP_BACKUP environment variables. When both are
    None, the pass is skipped.
    """

    db_path: Path | None = None
    zip_path: Path | None = None


class _StoreLike(Protocol):
    """Subset of BlackboardStore methods used by this pass."""

    def iter_all(self, *, strict: bool = ...) -> Any: ...


class _LoggerLike(Protocol):
    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...


def run(
    state_repo: _StoreLike,
    store: Any,  # BlackboardStore; type omitted to avoid import cycle
    *,
    config: DDConfig,
    run_id: str,
    log: _LoggerLike,
) -> PostPassStats:
    """Run the DixieData post-pass.

    Loads the DD index, iterates state rows, calls
    `_match_pensioner_to_dd` for each row, and writes matching
    observations to the store via PostPassObserver.

    Never raises; exceptions are logged and reflected in
    `stats.errors`.

    Args:
        state_repo: State repository (iterates `iter_all(strict=True)`).
        store: Blackboard store for observation persistence.
        config: Pass config (db_path, zip_path).
        run_id: Run identifier forwarded to PostPassObserver.
        log: Logger for non-fatal warnings.

    Returns:
        PostPassStats with `name="dd"`. `skipped=True` when no
        env vars set or the index is empty; `matched` set to the
        number of observations written.
    """
    started = time.monotonic()
    if config.db_path is None and config.zip_path is None:
        return PostPassStats(
            name="dd",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    try:
        from scripts.cgr.dixiedata_match import (
            _match_pensioner_to_dd,
            load_dd_index,
        )
        from scripts.pipeline.post_pass_observer import PostPassObserver

        dd_index = load_dd_index(
            db_path=str(config.db_path) if config.db_path else None,
            zip_path=str(config.zip_path) if config.zip_path else None,
        )
        if not dd_index:
            return PostPassStats(
                name="dd",
                skipped=True,
                duration_s=time.monotonic() - started,
            )

        observer = PostPassObserver(run_id=run_id)
        dd_matched = 0
        for record in state_repo.iter_all(strict=True):
            pid = record.get("pensioner_id")
            if pid is None:
                continue
            dd_result = _match_pensioner_to_dd(record, dd_index)
            if dd_result:
                observer.observe_dixiedata_match(
                    pensioner_id=int(pid),
                    dd_match=dd_result,
                    match_found=True,
                )
                dd_matched += 1
        observer.write_to_store(store)
        log.info(
            "DD post-pass: %d matches, wrote observations.",
            dd_matched,
        )
        return PostPassStats(
            name="dd",
            matched=dd_matched,
            duration_s=time.monotonic() - started,
        )
    except Exception as exc:
        log.warning("DD post-pass failed (non-fatal): %s", exc)
        return PostPassStats(
            name="dd",
            skipped=True,
            errors=1,
            duration_s=time.monotonic() - started,
            notes=f"exception: {exc}",
        )


def config_from(parent: Any) -> DDConfig:
    """Build DDConfig from environment variables.

    Reads DIXIEDATA_DB and DIXIEDATA_ZIP_BACKUP; the runner config
    does not own these (they're env-only).
    """
    import os

    db = os.environ.get("DIXIEDATA_DB")
    zip_ = os.environ.get("DIXIEDATA_ZIP_BACKUP")
    return DDConfig(
        db_path=Path(db) if db else None,
        zip_path=Path(zip_) if zip_ else None,
    )