"""Labels post-pass (Slice 6).

Moves the inline `_collect_labels_if_enabled` from
`scripts/pipeline/run_unified.py` into a post-pass module.
Reads the most recent `decisions_*.json` sidecar and appends
LabelSnapshot JSON lines to the configured labels path.

Slice 6 behavior is preserved byte-for-byte: same recipe gate
(`post.collect_labels`), same sidecar glob (newest by name),
same LabelExtractor call, same write discipline.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

from scripts.post_pass.types import BasePassConfig, PostPassStats


@dataclass(frozen=True)
class LabelsConfig(BasePassConfig):
    """Configuration for the labels post-pass.

    `recipe` is the RunRecipe (or any object with a `.post` attr
    carrying `.collect_labels` and `.labels_path`). When None,
    the pass is skipped.
    `out_dir` is the run output directory (where decisions sidecars
    are written).
    """

    recipe: Any
    out_dir: Path
    labels_path: Path | None = None  # resolved at run() time if absent


class _LoggerLike(Protocol):
    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...


def _resolve_labels_path(recipe: Any) -> Optional[Path]:
    """Extract labels_path from the recipe, or None if absent."""
    post_cfg = getattr(recipe, "post", None)
    if post_cfg is None:
        return None
    raw = getattr(post_cfg, "labels_path", None)
    return Path(raw) if raw else None


def run(
    *,
    config: LabelsConfig,
    log: _LoggerLike,
) -> PostPassStats:
    """Run the labels post-pass.

    Args:
        config: Pass config (recipe, out_dir, labels_path).
        log: Logger for non-fatal warnings.

    Returns:
        PostPassStats with `name="labels"`. `skipped=True` when
        no recipe, `collect_labels=False`, no decisions sidecar,
        or the extractor raises. `matched` set to the number of
        LabelSnapshots written.
    """
    started = time.monotonic()
    recipe = config.recipe
    if recipe is None:
        return PostPassStats(
            name="labels",
            skipped=True,
            duration_s=time.monotonic() - started,
        )
    post_cfg = getattr(recipe, "post", None)
    if post_cfg is None or not getattr(post_cfg, "collect_labels", False):
        return PostPassStats(
            name="labels",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    labels_path = config.labels_path or _resolve_labels_path(recipe)
    if labels_path is None:
        return PostPassStats(
            name="labels",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    # Find the most recent decisions_*.json in the output dir
    sidecar_path: Path | None = None
    for p in sorted(config.out_dir.glob("decisions_*.json"), reverse=True):
        sidecar_path = p
        break
    if sidecar_path is None:
        log.info("No decisions sidecar found; skipping label collection.")
        return PostPassStats(
            name="labels",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    try:
        from scripts.learning.label_extractor import LabelExtractor

        extractor = LabelExtractor()
        labels = extractor.from_decisions_file(sidecar_path)
    except Exception as e:
        log.warning("Label extraction failed: %s", e)
        return PostPassStats(
            name="labels",
            skipped=True,
            errors=1,
            duration_s=time.monotonic() - started,
            notes=f"exception: {e}",
        )

    if not labels:
        log.info("No labels extracted from %s", sidecar_path)
        return PostPassStats(
            name="labels",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    labels_path.parent.mkdir(parents=True, exist_ok=True)
    with labels_path.open("a", encoding="utf-8") as f:
        for label in labels:
            f.write(
                json.dumps(
                    {
                        "pensioner_id": label.pensioner_id,
                        "human_review_decision": label.human_review_decision,
                        "extracted_at": label.extracted_at,
                        "source_policy_version": label.source_policy_version,
                    }
                )
                + "\n"
            )

    log.info(
        "Collected %d labels from %s \u2192 %s",
        len(labels),
        sidecar_path.name,
        labels_path,
    )

    return PostPassStats(
        name="labels",
        matched=len(labels),
        duration_s=time.monotonic() - started,
    )


def config_from(parent: Any, *, out_dir: Path) -> LabelsConfig:
    """Build LabelsConfig from the runner config + run context.

    Pulls `_recipe` from the parent (the runner attaches the
    RunRecipe as a private attr). `out_dir` is passed by the
    runner (per-run, not a config field).
    """
    return LabelsConfig(
        recipe=getattr(parent, "_recipe", None),
        out_dir=out_dir,
    )