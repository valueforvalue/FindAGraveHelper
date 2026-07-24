"""Observation enrichment post-pass (Slice 1).

Moves the inline `_enrich_state_rows_with_observations` helper from
`scripts/pipeline/run_unified.py` into a `scripts/post_pass/` module
with a flat `run(state_repo, store, *, config, run_id, log) -> PostPassStats`
signature. Behavior is preserved byte-for-byte; only the wrapper shape
and `stats` return value are new.

Per Slice 1's success criterion, running the runner produces a
state.jsonl whose rows are enriched with CGR/DD/Spouse observations
identically to before the slice.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from scripts.post_pass._ids import deterministic_observation_id
from scripts.post_pass.types import BasePassConfig, PostPassStats


@dataclass(frozen=True)
class ObservationEnrichmentConfig(BasePassConfig):
    """No tunables today; reserved for future filtering or scoping."""

    pass


class _StateRepoLike(Protocol):
    """Subset of StateRepository methods used by this pass."""

    def iter_all(self, *, strict: bool = ...) -> Any: ...
    def replace_all(self, records: Any, *, atomic: bool = ...) -> None: ...


class _StoreLike(Protocol):
    """Subset of BlackboardStore methods used by this pass."""

    def read_observations_since(self, cursor: str | None) -> Any: ...


def run(
    state_repo: _StateRepoLike,
    store: _StoreLike,
    *,
    config: ObservationEnrichmentConfig,
    run_id: str,
    log: logging.Logger,
) -> PostPassStats:
    """Enrich state rows with CGR + DD + Spouse observations.

    Reads all CGRCorroboration, DixieDataMatch, and SpouseMatch
    observations from the Blackboard store, matches them to pensioner
    rows, and writes the evidence back as `cgr_match`, `dd_match`,
    and `spouse_match` fields on the matching rows.

    Idempotent: safe to call on already-enriched rows (skips rows that
    already carry the field for that evidence kind). Never raises;
    errors are logged and reflected in `stats.errors`.

    Args:
        state_repo: Mutable state repository (JsonlStateRepository or
            InMemoryStateRepository for tests).
        store: Blackboard store providing `read_observations_since(None)`.
        config: Pass config (no tunables today; reserved).
        run_id: Run identifier forwarded from the runner.
        log: Logger for non-fatal warnings.

    Returns:
        PostPassStats with `name="observation_enrichment"`, `skipped=True`
        when the store had no observations to apply, `matched` set to
        the number of state rows newly enriched.
    """
    started = time.monotonic()
    # Importing inside the function keeps the module import-light and
    # avoids a circular-import risk with the blackboard package at
    # module load time. The old inline implementation did the same.
    from scripts.blackboard.schema import Kind as _Kind

    all_obs = store.read_observations_since(None)

    cgr_by_pid: dict[int, dict[str, Any]] = {}
    dd_by_pid: dict[int, dict[str, Any]] = {}
    spouse_by_pid: dict[int, dict[str, Any]] = {}

    for obs in all_obs:
        pid = obs.pensioner_id
        if pid == 0:
            continue
        if obs.kind == _Kind.CGRCorroboration:
            cgr_by_pid[pid] = obs.payload
        elif obs.kind == _Kind.DixieDataMatch:
            dd_by_pid[pid] = obs.payload
        elif obs.kind == _Kind.SpouseMatch:
            spouse_by_pid[pid] = obs.payload

    if not cgr_by_pid and not dd_by_pid and not spouse_by_pid:
        return PostPassStats(
            name="observation_enrichment",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    enriched = 0
    updated: list[dict[str, Any]] = []
    for record in state_repo.iter_all(strict=True):
        pid = record.get("pensioner_id")
        if pid is None:
            updated.append(record)
            continue
        pid_int = int(pid)
        changed = False

        if pid_int in cgr_by_pid and "cgr_match" not in record:
            record["cgr_match"] = cgr_by_pid[pid_int]
            changed = True
        if pid_int in dd_by_pid and "dd_match" not in record:
            record["dd_match"] = dd_by_pid[pid_int]
            changed = True
        if pid_int in spouse_by_pid and "spouse_match" not in record:
            record["spouse_match"] = spouse_by_pid[pid_int]
            changed = True

        if changed:
            enriched += 1
        updated.append(record)

    if enriched:
        state_repo.replace_all(updated)
        log.info(
            "Enriched %d state rows with CGR/DD/spouse observations.",
            enriched,
        )

    return PostPassStats(
        name="observation_enrichment",
        matched=enriched,
        duration_s=time.monotonic() - started,
    )


def config_from(parent: Any) -> ObservationEnrichmentConfig:
    """Build ObservationEnrichmentConfig from the runner config.

    No fields today; reserved for future filtering or scoping. Kept
    here so the per-pass config-from-parent convention (Q2) is
    uniform across all post-pass modules.
    """
    del parent  # currently no fields are pulled from the parent
    return ObservationEnrichmentConfig()