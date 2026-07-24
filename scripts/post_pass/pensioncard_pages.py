"""Pensioncard pages post-pass (Slice 2).

Moves the inline `_annotate_pensioncard_pages` helper from
`scripts/pipeline/run_unified.py` into a post-pass module with a
flat `run(results_path, *, config, out_dir, log) -> PostPassStats`
signature. Behavior is preserved byte-for-byte: reads a sidecar
JSON of `{pensioner_id: [page_id, ...]}`, populates each matching
state row's `pensioncard_pages` field, and atomically rewrites
state.jsonl.

Note: the pre-loop "load pensioncard_pages cache" block in
`run_unified.py` (lines 852–864) is intentionally NOT part of
this pass. That cache is consumed during per-pensioner row
building (where `row["pensioncard_pages"] = pages` happens inline),
which is the main loop's responsibility, not a post-pass.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts.post_pass.types import BasePassConfig, PostPassStats


@dataclass(frozen=True)
class PensioncardPagesConfig(BasePassConfig):
    """Configuration for the pensioncard_pages pass.

    `sidecar_path` is the explicit path to the sidecar JSON. When
    None, the pass auto-detects `<out_dir>/pensioncard_pages.json`.
    """

    sidecar_path: Path | None = None


class _LoggerLike(Protocol):
    """Subset of logging.Logger used by this pass."""

    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...


def run(
    results_path: Path,
    *,
    config: PensioncardPagesConfig,
    out_dir: Path,
    log: _LoggerLike,
) -> PostPassStats:
    """Annotate state.jsonl rows with pensioncard_pages from a sidecar.

    Reads the sidecar from `config.sidecar_path` if it exists;
    otherwise looks for `<out_dir>/pensioncard_pages.json`. If no
    sidecar exists, returns `skipped=True` without touching the
    state file.

    On success, rewrites `results_path` atomically (tmp file +
    replace) with each matching row's `pensioncard_pages` field
    populated from the sidecar.

    Args:
        results_path: Path to state.jsonl (L5 newline-delimited).
        config: Pass config (sidecar path).
        out_dir: Output directory (used for sidecar auto-detection).
        log: Logger for non-fatal warnings.

    Returns:
        PostPassStats with `name="pensioncard_pages"`, `skipped=True`
        when no sidecar exists, `matched` set to the count of
        rows whose `pensioncard_pages` field was populated.
    """
    started = time.monotonic()

    sidecar: Path | None = None
    if config.sidecar_path and config.sidecar_path.exists():
        sidecar = config.sidecar_path
    else:
        candidate = out_dir / "pensioncard_pages.json"
        if candidate.exists():
            sidecar = candidate

    if sidecar is None:
        return PostPassStats(
            name="pensioncard_pages",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    try:
        cache: dict = json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("pensioncard_pages annotation load failed: %s", e)
        return PostPassStats(
            name="pensioncard_pages",
            skipped=True,
            errors=1,
            duration_s=time.monotonic() - started,
            notes=f"sidecar load failed: {e}",
        )

    if not cache:
        return PostPassStats(
            name="pensioncard_pages",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    annotated = 0
    records: list[dict] = []
    if results_path.exists():
        with results_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    records.append({})
                    continue
                pid = str(rec.get("pensioner_id", ""))
                pages = cache.get(pid)
                if pages:
                    rec["pensioncard_pages"] = pages
                    annotated += 1
                records.append(rec)

    if not annotated:
        return PostPassStats(
            name="pensioncard_pages",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    tmp = results_path.with_suffix(results_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(results_path)

    log.info(
        "Annotated %d records with pensioncard_pages from %s",
        annotated,
        sidecar,
    )

    return PostPassStats(
        name="pensioncard_pages",
        matched=annotated,
        duration_s=time.monotonic() - started,
    )


def config_from(parent: Any) -> PensioncardPagesConfig:
    """Build PensioncardPagesConfig from the runner config.

    Pulls `pensioncard_pages_path` (Path | None) from the parent.
    """
    sidecar = getattr(parent, "pensioncard_pages_path", None)
    return PensioncardPagesConfig(sidecar_path=sidecar)