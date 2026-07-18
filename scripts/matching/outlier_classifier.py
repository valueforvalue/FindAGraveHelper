"""Outlier classifier for unified state records.

Given a unified state record, decide whether it's an 'outlier'
(needs another run with different strategies / human review).

Per user decision:
  - Outlier = top FaG score < threshold (default 0.40) OR
              no FaG candidates at all OR
              FaG search errored/captcha'd.
  - Done     = otherwise.

Threshold is configurable.

Outliers get written to outliers.jsonl so follow-up runs can
target them with extra/different strategies (e.g. fuzzy name
matching, expanded biography search).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class Classification(Enum):
    DONE = "done"
    OUTLIER = "outlier"


@dataclass
class OutlierConfig:
    """Tunable thresholds for outlier classification.

    Issue #28 follow-up: the default `low_score_threshold` is
    imported from scoring_constants so this config, the CLI
    default, and the dry-run path all agree. The dataclass
    default uses `field(default_factory=...)` because module-level
    constants can't be used directly as `default=` values when
    they could be mutated.
    """
    low_score_threshold: float = field(
        default_factory=lambda: _low_score_threshold_default()
    )
    # Statuses that are outliers regardless of score
    outlier_statuses: tuple[str, ...] = (
        "no_results",
        "error",
        "captcha",
        "not_run",
    )


def _low_score_threshold_default() -> float:
    """Lazy import to avoid a circular import at module load.

    scripts.pipeline.scoring_constants is a small leaf module
    with no dependencies on scripts.matching.*, so the import
    direction is safe — but evaluating it at field-construction
    time is the cleanest way to share the constant.
    """
    from scripts.pipeline.scoring_constants import LOW_SCORE_THRESHOLD
    return LOW_SCORE_THRESHOLD


def _top_score(rec: dict) -> float:
    """Best score across all FaG candidates."""
    cands = rec.get("fag_records", []) or []
    if not cands:
        return 0.0
    return max((c.get("score", 0) or 0) for c in cands)


def is_outlier(rec: dict, config: OutlierConfig) -> bool:
    """Predict whether a record is an outlier.

    Outlier if:
      - FaG status is in outlier_statuses, OR
      - top FaG score is below low_score_threshold.
    """
    status = rec.get("fag_status", "")
    if status in config.outlier_statuses:
        return True
    if _top_score(rec) < config.low_score_threshold:
        return True
    return False


def classify_record(
    rec: dict, config: OutlierConfig
) -> Classification:
    """Classify into DONE or OUTLIER."""
    return Classification.OUTLIER if is_outlier(rec, config) else Classification.DONE


def summary_for_records(
    records: Iterable[dict], config: OutlierConfig
) -> dict:
    """Aggregate counts + percentages for a list of records."""
    counts = {"done": 0, "outlier": 0}
    total = 0
    for r in records:
        total += 1
        cls = classify_record(r, config)
        counts[cls.value] += 1
    out_pct = round((counts["outlier"] / total) * 100, 1) if total else 0.0
    done_pct = round((counts["done"] / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "counts": counts,
        "outlier_pct": out_pct,
        "done_pct": done_pct,
        "low_score_threshold": config.low_score_threshold,
    }


def outlier_records(
    records: Iterable[dict], config: OutlierConfig
) -> list[dict]:
    """Filter to outlier records only."""
    return [r for r in records if is_outlier(r, config)]


def done_records(
    records: Iterable[dict], config: OutlierConfig
) -> list[dict]:
    """Filter to done records only."""
    return [r for r in records if not is_outlier(r, config)]


def write_outliers(
    records: Iterable[dict], config: OutlierConfig, out_path: Path
) -> int:
    """Write outliers to a JSONL file. Returns count written."""
    import json
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            if is_outlier(r, config):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                n += 1
    return n