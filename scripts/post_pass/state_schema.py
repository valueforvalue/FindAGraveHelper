"""State-schema post-pass — issue #98 (versioned projection).

Writes `state.schema.json` next to `state.jsonl` documenting the
current row shape. The schema spec is the canonical field list
in `scripts.projection.schema`; the file is auto-regenerated on
every run so it never drifts from what `ProjectionBuilder` emits.

The view-layer (view.html, v2.html) reads the schema file first
and can warn on shape drift; that read-side warning is a separate
slice (out of scope for issue #98, which is the write side).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts.post_pass.types import BasePassConfig, PostPassStats
from scripts.projection.schema import render_schema_json


@dataclass(frozen=True)
class StateSchemaConfig(BasePassConfig):
    """Configuration for the state_schema post-pass.

    `state_path` is the path to the state.jsonl file. The schema
    file is emitted next to it (same stem, `.schema.json`).
    """

    state_path: Path | None = None


class _LoggerLike(Protocol):
    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...


def _schema_path_for(state_path: Path) -> Path:
    """Compute the schema file path for a given state file.

    `state.jsonl` → `state.schema.json`. Same stem; the .schema
    suffix replaces the .jsonl suffix.
    """
    return state_path.with_name(state_path.stem + ".schema.json")


def run(
    *,
    config: StateSchemaConfig,
    log: _LoggerLike,
) -> PostPassStats:
    """Emit state.schema.json next to state.jsonl.

    Args:
        config: Pass config (state_path).
        log: Logger for non-fatal warnings.

    Returns:
        PostPassStats with `name="state_schema"`. `skipped=True`
        when no state_path is provided.
    """
    started = time.monotonic()
    if config.state_path is None:
        return PostPassStats(
            name="state_schema",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    schema = render_schema_json()
    target = _schema_path_for(config.state_path)
    target.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Wrote projection schema (v%d) to %s", schema["schema_version"], target)
    return PostPassStats(
        name="state_schema",
        matched=len(schema["fields"]),
        duration_s=time.monotonic() - started,
        notes=f"wrote v{schema['schema_version']} to {target.name}",
    )


def config_from(parent: Any, *, results_path: Path | None) -> StateSchemaConfig:
    """Build StateSchemaConfig from the runner config + run context."""
    return StateSchemaConfig(state_path=results_path)