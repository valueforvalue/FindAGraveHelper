"""Retry pensioners that ended with status='error' in state.jsonl.

After the main run, some records will have fag_status='error'
(due to DOM crashes, transient network, etc.). The fix is in
place for the root cause, but we want to retry those records
with the corrected code so the final report is complete.

This module:
  1. Reads state.jsonl, collects pensioner_ids with status=error
  2. Re-runs the unified pipeline for each (using the corrected fag_browser)
  3. Updates the corresponding state record IN-PLACE (same line in
     the JSONL, preserving record order so other fields are not
     disturbed)
  4. Marks each retried record with a `retried_at` timestamp

This is a separate run from the main pipeline, not a re-run.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


from scripts.pipeline.core import (
    run_pipeline_for_pensioner,
    PipelineConfig,
)
from scripts.run_unified import result_to_dict, now_iso


@dataclass
class RetryResult:
    """Result of a retry pass."""
    retried: int = 0
    recovered: int = 0
    still_error: int = 0
    pensioner_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "retried": self.retried,
            "recovered": self.recovered,
            "still_error": self.still_error,
            "pensioner_ids_tried": self.pensioner_ids[:20],  # cap for log
        }


def collect_error_pensioner_ids(state_path: Path) -> set[int]:
    """Read state.jsonl and collect pensioner_ids with status='error'.

    Returns a set of ints. Handles missing files (returns empty).

    Issue #22: routed through JsonlStateRepository. The Repository
    owns the iter_all() JSON-decoding discipline.
    """
    from scripts.state.repository import JsonlStateRepository
    ids: set[int] = set()
    for rec in JsonlStateRepository(state_path).iter_all():
        if rec.get("fag_status") == "error":
            pid = rec.get("pensioner_id")
            if pid is not None:
                ids.add(pid)
    return ids


def _atomic_rewrite_state(
    state_path: Path,
    records: list[dict],
) -> None:
    """Rewrite state.jsonl atomically with the given records.

    Issue #22: routed through JsonlStateRepository. Single internal
    caller is the retry pipeline; new code should call
    `JsonlStateRepository(state_path).replace_all(records)` directly.
    """
    from scripts.state.repository import JsonlStateRepository
    JsonlStateRepository(state_path).replace_all(records)


def retry_error_pensioners(
    state_path: Path,
    cemeteries: list[dict],
    pensioners_by_id: dict[int, dict],
    fag_search_fn: Callable,
    throttle_seconds: float = 1.0,
) -> RetryResult:
    """Retry every errored pensioner and update the state file in-place.

    Args:
        state_path: state.jsonl to read + update
        cemeteries: CGR records for blocking lookup
        pensioners_by_id: full pensioner dicts keyed by id (we'll lookup)
        fag_search_fn: callable for FaG search
        throttle_seconds: between requests

    Returns:
        RetryResult with counts.
    """
    err_ids = collect_error_pensioner_ids(state_path)
    if not err_ids:
        return RetryResult()

    # Load all records into memory
    all_records = []
    from scripts.state.repository import JsonlStateRepository
    all_records = list(JsonlStateRepository(state_path).iter_all())

    result = RetryResult(pensioner_ids=sorted(err_ids))
    pipeline_cfg = PipelineConfig(throttle_seconds=throttle_seconds)
    last_request_at = 0.0

    # Build a lookup of pensioner_id -> record (for in-place update)
    by_pid = {r.get("pensioner_id"): r for r in all_records}

    for pid in sorted(err_ids):
        if pid not in pensioners_by_id:
            continue
        pensioner = pensioners_by_id[pid]
        result.retried += 1

        # Throttle
        now = time.time()
        gap = now - last_request_at
        if last_request_at > 0 and gap < throttle_seconds:
            time.sleep(throttle_seconds - gap)
        last_request_at = time.time()

        try:
            pipeline_result = run_pipeline_for_pensioner(
                pensioner=pensioner,
                cgr_index_vets=cemeteries,
                config=pipeline_cfg,
                fag_search_fn=fag_search_fn,
            )
            new_record = result_to_dict(pipeline_result)
            # Preserve original record's position; only update fields
            existing = by_pid[pid]
            existing.update(new_record)
            existing["retried_at"] = now_iso()

            if pipeline_result.fag_status != "error":
                result.recovered += 1
                existing["retry_succeeded"] = True
            else:
                result.still_error += 1
                existing["retry_succeeded"] = False
        except Exception as e:
            existing = by_pid[pid]
            existing["retry_error"] = str(e)[:200]
            result.still_error += 1

    # Atomic rewrite
    _atomic_rewrite_state(state_path, all_records)
    return result


def retry_main(
    state_path: Path,
    pensioners_path: Path,
    cgr_path: Path,
    fag_search_fn: Optional[Callable] = None,
    no_fag: bool = False,
    throttle_seconds: float = 1.0,
    watchdog: Optional["object"] = None,
    max_consecutive_errors: int = 10,
    reset_browser_every: int = 250,
) -> RetryResult:
    """Convenience: load inputs by path, then run retry_error_pensioners.

    Used by the retry CLI.
    """
    from scripts.fag.fag_browser import make_fag_search_fn
    from scripts.run_unified import _load_cems

    # Load pensioners
    with pensioners_path.open(encoding="utf-8") as f:
        pensioners = json.load(f)
    pensioners_by_id = {p["id"]: p for p in pensioners if p.get("id") is not None}

    # Load CGR
    cems = _load_cems(cgr_path)

    if fag_search_fn is None and not no_fag:
        fag_search_fn = make_fag_search_fn(
            throttle=throttle_seconds,
            reset_browser_every=reset_browser_every,
            watchdog=watchdog,
            max_consecutive_errors=max_consecutive_errors,
        )

    if no_fag:
        # No actual FaG search; just re-run CGR
        fag_search_fn = lambda p, cfg: ([], "no_results")

    return retry_error_pensioners(
        state_path=state_path,
        cemeteries=cems,
        pensioners_by_id=pensioners_by_id,
        fag_search_fn=fag_search_fn,
        throttle_seconds=throttle_seconds,
    )