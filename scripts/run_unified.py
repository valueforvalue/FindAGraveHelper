"""Unified runner CLI for Find a Grave Helper.

The runner coordinates per-pensioner:
  1. CGR blocking lookup (fast, no network)
  2. Annotate matches with match_strength
  3. Decide outlier status (low score or no results)
  4. Run FaG search (browser, 1.5s throttle)
  5. Write state.jsonl (resumable)
  6. Append outliers to outliers.jsonl

Output files (under out_dir):
  - state.jsonl: every pensioner (resumable)
  - outliers.jsonl: pensioners needing follow-up runs
  - run.log: heartbeat + per-pensioner log
  - report.md, report.json: at completion

Usage:
  python scripts/run_unified.py \\
    --pensioners docs/research/digitalprairie/ok_pensioners.json \\
    --cgr docs/research/cgr/ok_vets_enriched.jsonl \\
    --out data/results/run_2026_07_16/ \\
    --limit 50                    # for smoke tests

  # Full run:
  python scripts/run_unified.py \\
    --pensioners docs/research/digitalprairie/ok_pensioners.json \\
    --cgr docs/research/cgr/ok_vets_enriched.jsonl \\
    --out data/results/run_2026_07_16/ \\
    --all
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from scripts.unified_pipeline import (
    run_pipeline_for_pensioner,
    PipelineConfig,
    PipelineResult,
)
from scripts.unified_runner import (
    build_cgr_blocking_index,
    lookup_cgr_for_pensioner,
    annotate_cgr_matches,
)
from scripts.outlier_classifier import (
    OutlierConfig,
    is_outlier,
)
from scripts.report_generator import (
    build_report,
    write_report,
)


# ============================================================
# Configuration
# ============================================================
@dataclass
class UnifiedRunnerConfig:
    """Configuration for the unified runner."""
    out_dir: Optional[Path] = None
    # Pipeline
    throttle_seconds: float = 1.5
    low_score_threshold: float = 0.40
    max_cgr_candidates: int = 20
    # Limits
    limit: Optional[int] = None
    # Behavioral
    write_outliers_separately: bool = True
    write_heartbeat_every: int = 50  # every N pensioners
    # Browser (kept abstract; the actual FaG search is injected)
    fag_search_fn: Optional[Callable] = None


# ============================================================
# Resume support
# ============================================================
class ResumeTracker:
    """Tracks which pensioner IDs have already been processed.

    Reads the existing state file (if any) and lets the runner
    skip already-processed pensioners. State file is JSONL.
    """

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.completed_ids: set[int] = set()
        self._load()

    def _load(self):
        if not self.state_path.exists():
            return
        with self.state_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pid = rec.get("pensioner_id")
                if pid is not None:
                    self.completed_ids.add(pid)

    def count(self) -> int:
        return len(self.completed_ids)

    def is_done(self, pid: int) -> bool:
        return pid in self.completed_ids


def load_existing_ids(state_path: Path) -> set[int]:
    """Standalone helper to read pensioner_ids from a state file."""
    if not state_path.exists():
        return set()
    ids = set()
    with state_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = rec.get("pensioner_id")
            if pid is not None:
                ids.add(pid)
    return ids


# ============================================================
# Line writers
# ============================================================
def write_unified_line(state_path: Path, record: dict) -> None:
    """Append one record to the unified state file."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


def write_outliers_line(outliers_path: Path, record: dict) -> None:
    """Append one record to outliers.jsonl."""
    outliers_path.parent.mkdir(parents=True, exist_ok=True)
    with outliers_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


# ============================================================
# CGR-only run (test mode)
# ============================================================
def run_one_pensioner_cgr_only(
    pensioner: dict,
    cemeteries: list[dict],
    config: UnifiedRunnerConfig,
) -> dict:
    """Run CGR-only lookup for one pensioner.

    No FaG search is performed. Useful for testing the CGR
    pipeline without the browser.
    """
    pipeline_cfg = PipelineConfig(throttle_seconds=config.throttle_seconds)
    result: PipelineResult = run_pipeline_for_pensioner(
        pensioner=pensioner,
        cgr_index_vets=cemeteries,
        config=pipeline_cfg,
        fag_search_fn=None,
    )
    record = result_to_dict(result)
    return record


def result_to_dict(result: PipelineResult) -> dict:
    """Convert a PipelineResult into a JSON-serializable dict."""
    return {
        "pensioner_id": result.pensioner.get("id"),
        "pensioner_app_number": result.pensioner.get("application_number", ""),
        "pensioner_name": " ".join([
            result.pensioner.get("first_name", ""),
            result.pensioner.get("middle_name", ""),
            result.pensioner.get("last_name", ""),
        ]).strip().replace("  ", " "),
        "pensioner_first": result.pensioner.get("first_name", ""),
        "pensioner_middle": result.pensioner.get("middle_name", ""),
        "pensioner_last": result.pensioner.get("last_name", ""),
        "pensioner_birth_year": result.pensioner.get("birth_year", ""),
        "pensioner_death_year": result.pensioner.get("death_year", ""),
        "regiment": result.pensioner.get("regiment", ""),
        "company": result.pensioner.get("company", ""),
        "pensioncard_backlink": result.pensioner.get("pensioncard_backlink", ""),
        "cgr_records": result.cgr_records,
        "cgr_status": result.cgr_status,
        "fag_records": result.fag_records,
        "fag_status": result.fag_status,
        "both_match": result.both_match,
        "best_score": (
            max((c.get("score", 0) or 0) for c in result.fag_records)
            if result.fag_records
            else 0.0
        ),
        "status": result.fag_status,
        "timestamp": result.timestamp,
        "error": result.error,
    }


# ============================================================
# Heartbeat
# ============================================================
def heartbeat_logger(
    log: logging.Logger,
    state_path: Path,
    total: int,
    processed: int,
    started_at: float,
    now: float,
) -> None:
    """Emit a one-line progress update."""
    elapsed = now - started_at
    rate = processed / elapsed if elapsed > 0 else 0
    remaining = total - processed
    eta_sec = remaining / rate if rate > 0 else 0
    eta_min = eta_sec / 60
    log.info(
        "Heartbeat: %d/%d (%.1f%%)  rate=%.2f rec/s  eta=%.1f min  "
        "size=%.1f KB",
        processed, total,
        (processed / total) * 100 if total else 0,
        rate,
        eta_min,
        state_path.stat().st_size / 1024 if state_path.exists() else 0,
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")