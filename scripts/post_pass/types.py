"""Post-pass shared types.

`PostPassStats` is the return value every post-pass must produce so
`run_unified.py` can log uniformly. `BasePassConfig` is the shared
parent type for per-pass frozen dataclasses (Q2 decision).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PostPassStats:
    """Result of one post-pass invocation.

    `name` is the registry key (e.g. "observation_enrichment").
    `skipped` is True when the pass early-returned without writing
    (e.g. env-gate unset, no observations to enrich).
    `matched`, `attempted`, `errors` are pass-specific counts.
    `duration_s` is wall-clock time for observability.
    `notes` is a free-form tail for one-line logging.
    """

    name: str
    skipped: bool = False
    matched: int = 0
    attempted: int = 0
    errors: int = 0
    duration_s: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class BasePassConfig:
    """Marker parent for per-pass config dataclasses.

    Each pass module owns a frozen dataclass that subclasses this.
    `config_from(parent: UnifiedRunnerConfig)` is the factory that
    derives the pass-specific config from the top-level runner config.
    """