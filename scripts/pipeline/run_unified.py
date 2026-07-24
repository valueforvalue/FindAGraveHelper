"""Unified runner CLI for Find a Grave Helper.

The runner coordinates per-pensioner:
  1. CGR blocking lookup (fast, no network)
  2. Annotate matches with match_strength
  3. Decide outlier status (low score or no results)
  4. Run FaG search (browser, 2.5s throttle)
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
import os
import stat
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Ensure the scripts/ directory is on the path so this file can be
# executed directly via `python scripts/run_unified.py`.
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
# Also the project root for `scripts.X` imports
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.pipeline.core import (
    run_pipeline_for_pensioner,
    PipelineConfig,
    PipelineResult,
    build_cgr_blocking_index,
    lookup_cgr_for_pensioner,
    annotate_cgr_matches,
)
from scripts.matching.outlier_classifier import (
    OutlierConfig,
    is_outlier,
)


# ============================================================
# Configuration
# ============================================================
@dataclass
class UnifiedRunnerConfig:
    """Configuration for the unified runner."""
    out_dir: Optional[Path] = None
    # Pipeline
    throttle_seconds: float = 2.5
    low_score_threshold: float = 0.40
    max_cgr_candidates: int = 20
    # Limits
    limit: Optional[int] = None
    # Behavioral
    write_outliers_separately: bool = True
    write_heartbeat_every: int = 50  # every N pensioners
    # Issue #21: auto-checkpoint every N records (0 to disable).
    # The scheduler writes a state.jsonl checkpoint snapshot at this
    # cadence. Combined with --rollback-to, this bounds the
    # worst-case data loss window to ~N records.
    checkpoint_every: int = 0
    # Pensioncard pages sidecar (J6). Built by
    # scripts/ingest/fetch_pensioncard_pages.py. Maps
    # pensioner_id (str) -> [page_id, ...] (the IIIF image IDs for
    # Side 1, Side 2, ...). view.html embeds the images directly.
    pensioncard_pages_path: Optional[Path] = None
    # CGR source JSONL path. Used by the post-run CGR <-> FaG
    # dedup (scripts/cgr/cgr_fag_dedup.py). When None, the dedup
    # is skipped.
    cgr_path: Optional[Path] = None
    # Browser mode. False means explicit --no-fag / dry-run execution.
    enable_fag: bool = True
    # Browser (legacy runner only; scheduler owns BrowserSession directly).
    fag_search_fn: Optional[Callable] = None
    # Per-run isolation (J5-S2)
    # Filename for per-pensioner results within out_dir. Defaults to
    # "results.jsonl" (one Results file per run, named after the
    # run). The scheduler is filename-agnostic.
    results_filename: str = "results.jsonl"
    # Path to the source view.html to copy into out_dir at run start.
    # The copy is skipped if out_dir/view.html already exists
    # (preserves user edits during review).
    view_html_source: Optional[Path] = None
    # Blackboard scheduler (Phase W1-W4)
    # Blackboard store bootstrap (always on)
    blackboard_db_path: Optional[Path] = None
    run_manifest: Any = None  # RunManifest, set at runtime

    # Browser session config (issue #61: externalize from code).
    # All previously-hardcoded BrowserSession knobs live here.
    headless: bool = False  # Cloudflare blocks headless; default visible
    browser_state_filter: str = "OK"  # FaG locationId scope at session level
    browser_reset_every: int = 250  # Periodic reopen to bound RSS growth
    max_consecutive_errors: int = 10  # Hard-stop after N in-a-row errors
    auto_relax: bool = True  # OK -> US broadening when narrow is sparse
    # Issue #78: search aggressiveness mode.
    search_mode: str = "standard"  # conservative | standard | aggressive
    # Issue #??: re-process already-completed pensioners.
    reprocess: bool = False
    # SearchEngine instance for FaGScraperKS. When None, defaults
    # to FaGEngine(). Per issue #61: the Blackboard path must use
    # the engine's ladder, not the legacy fag.search one.
    fag_engine: Any = None

    # Override L1 throttle floor. L1 (CONTEXT.md) sets 2.5s as the
    # safe floor; lowering below this re-introduces the Cloudflare
    # 1015 rate-limit risk. When True, the floor is enforced; when
    # False (default for slice runs), the configured value passes
    # through with a DeprecationWarning. Issue #61: operators opt
    # into low-throttle slicing by setting this to False.
    enforce_throttle_floor: bool = True
    # RequestGate minimum interval (per-strategy throttle).
    # Same value as the legacy BrowserSession.throttle. When set
    # lower than 2.5s, the gate matches the lowered budget; the
    # `enforce_throttle_floor` knob still applies to BrowserSession
    # construction (L1 hard floor at 2.5s by default).
    request_gate_min_interval: float = 2.5
    # Issue #63: mock FaG API with HTML fixture (offline testing).
    # When set, all findagrave.com/memorial/search requests are
    # intercepted and fulfilled with the fixture HTML.
    mock_fag_path: Optional[Path] = None


# ============================================================
# view.html copy (J5-S2 + J9 embed)
# ============================================================
# J9: when the runner copies view.html into the run dir, it also
# embeds the matching results.jsonl as a <script type="application/json">
# block. This makes the page work standalone when opened from
# file:// (where fetch() of sibling files is blocked by the
# browser) or from a simple http server. The view.html JS
# reads from the embedded block first, then falls back to fetch.
#
# Slice 3 (post-pass extraction): the implementation + the four
# placeholder constants now live in `scripts/post_pass/view_copy.py`.
# These shims keep the symbols importable from
# `scripts.pipeline.run_unified` for back-compat with existing tests
# (test_view_ux_j9, test_unified_config_externalization).
from scripts.post_pass.view_copy import (
    EMBEDDED_DATA_PLACEHOLDER,
    EMBEDDED_DD_MATCH_PLACEHOLDER,
    EMBEDDED_SPOUSE_FOLLOWUPS_PLACEHOLDER,
    EMBEDDED_SPOUSE_MATCH_PLACEHOLDER,
    copy_view_html_if_missing,
)


# ============================================================
# restart.sh (issue #68)
# ============================================================

def write_restart_script(
    out_dir: Path,
    config_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
) -> Path:
    """Write `restart.sh` to *out_dir* for resuming a failed run.

    The generated script reconstructs CLI args from *config_path*
    (or ``out_dir/config.json``) and resumes from *state_path*
    (or the latest results.jsonl in the directory).

    Returns the path to the written script.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = config_path or out_dir / "config.json"
    if not cfg.is_absolute():
        cfg = cfg.resolve()

    lines = [
        "#!/usr/bin/env bash",
        "# restart.sh — resume a failed FindAGraveHelper run",
        f"# Generated for run directory: {out_dir}",
        "set -euo pipefail",
        "",
        f'RUN_DIR="{out_dir}"',
        f'CONFIG="{cfg}"',
        "",
        'if [ ! -f "$CONFIG" ]; then',
        '  echo "ERROR: config.json not found at $CONFIG" >&2',
        '  exit 1',
        'fi',
        "",
        'echo "Resuming run from $RUN_DIR"',
        'echo "Config: $CONFIG"',
        "",
        f'exec python scripts/run_unified.py --config "$CONFIG" "$@"',
    ]
    script = out_dir / "restart.sh"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Make executable on POSIX
    try:
        script.chmod(0o755)
    except Exception:
        pass
    return script


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
# Issue #22: write_unified_line adapter removed. Callers use
# JsonlStateRepository directly.


def write_outliers_line(outliers_path: Path, record: dict) -> None:
    """Append one record to outliers.jsonl."""
    outliers_path.parent.mkdir(parents=True, exist_ok=True)
    with outliers_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


# ============================================================
# Resume artifact (J5-S3)
# ============================================================
def build_resume_command(
    config_path: Path,
    python_bin: str = sys.executable,
    script_path: str = "scripts/run_unified.py",
) -> str:
    """Build the exact CLI invocation to resume a run.

    Args:
        config_path: Path to the run's config.json (output/<runname>/config.json).
        python_bin: Python interpreter to invoke (defaults to current process).
        script_path: Path to the unified runner script (relative to repo root).

    Returns:
        A single-line shell command string. Path with spaces is
        quoted for POSIX shells; Windows quoting is left to the user.
    """
    cfg_str = str(config_path)
    # Quote if contains whitespace (POSIX-style)
    if any(c.isspace() for c in cfg_str):
        cfg_str = f'"{cfg_str}"'
    return f"{python_bin} {script_path} --config {cfg_str}"


def write_resume_artifact(
    out_dir: Path,
    config_path: Path,
    log: logging.Logger,
) -> Path:
    """Write the resume.sh artifact + log the resume command.

    The artifact is a single-line shell script that, when executed,
    re-invokes the runner with --config pointing at this run's
    config.json. ResumeTracker skips already-done pensioners, so
    re-running is safe (idempotent on the done set).

    Args:
        out_dir: The run directory (output/<runname>/).
        config_path: Path to output/<runname>/config.json.
        log: Logger for the "RESUME COMMAND:" line.

    Returns:
        Path to the written resume.sh.
    """
    out_dir = Path(out_dir)
    config_path = Path(config_path)
    resume_path = out_dir / "resume.sh"

    cmd = build_resume_command(config_path=config_path)

    # Write the script (POSIX \n line endings work fine on Windows when
    # invoked via `bash resume.sh`; not blocking).
    body = (
        "#!/usr/bin/env bash\n"
        "# Auto-generated by scripts/run_unified.py at " + now_iso() + "\n"
        "# Re-running is safe: ResumeTracker skips already-done pensioners.\n"
        "set -euo pipefail\n"
        f"cd \"$(dirname \"$0\")/../..\"\n"  # back to repo root
        f"{cmd}\n"
    )
    resume_path.write_text(body, encoding="utf-8")
    # chmod +x on POSIX; no-op on Windows
    try:
        mode = resume_path.stat().st_mode
        resume_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except (OSError, NameError):
        pass

    log.info("RESUME COMMAND: %s", cmd)
    return resume_path


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


def result_to_dict(result: PipelineResult,
                  pensioncard_pages_cache: Optional[dict] = None) -> dict:
    """Convert a PipelineResult into a JSON-serializable dict.

    pensioncard_pages_cache: optional {pensioner_id_str: [page_ids]}
        from the sidecar built by scripts/ingest/fetch_pensioncard_pages.py.
        When provided and the pensioner has cached page IDs, the
        record carries `pensioncard_pages: [page_ids]` so view.html
        can embed the IIIF images directly. When None or missing
        for this pensioner, the field is omitted.
    """
    record = {
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
        "backlink": result.pensioner.get("backlink", ""),
        # J15: pensioner's known spouse carried into the record so
        # view.html + the post-pipeline comparison can use it.
        # populated only when the source data has spouse_first
        # + spouse_last (default empty otherwise; see J15-S1).
        "pensioner_spouse_first": result.pensioner.get("spouse_first_name", "") or "",
        "pensioner_spouse_middle": result.pensioner.get("spouse_middle_name", "") or "",
        "pensioner_spouse_last": result.pensioner.get("spouse_last_name", "") or "",
        "cgr_records": result.cgr_records,
        "cgr_status": result.cgr_status,
        "fag_records": result.fag_records,
        "fag_status": result.fag_status,
        "both_match": result.both_match,
        "best_score": (
            max((c.get("score", 0) or 0) for c in (result.fag_records or []))
            if (result.fag_records or [])
            else 0.0
        ),
        "status": result.fag_status,
        "timestamp": result.timestamp,
        "error": result.error,
    }
    if pensioncard_pages_cache:
        pages = pensioncard_pages_cache.get(
            str(result.pensioner.get("id"))
        )
        if pages:
            record["pensioncard_pages"] = pages
    # Common engine-agnostic projection (issue #39).
    # Emitted alongside legacy fields so v2 view.html can read
    # either shape; v1 view.html ignores the common key.
    record["common"] = _build_common_record(
        pensioner_id=record["pensioner_id"],
        pensioner_name=record["pensioner_name"],
        engine=getattr(result, "engine_name", None) or "findagrave",
        status=record["fag_status"],
        best_score=record["best_score"],
        candidates=record["fag_records"],
        engine_for_convert=(
            result.engine_for_convert
            if hasattr(result, "engine_for_convert")
            else None
        ),
        corroboration={
            "cgr": record["cgr_records"],
            "dd_match": record.get("both_match"),
            "spouse_match": _build_spouse_section(result),
        },
    )
    return record


def _build_spouse_section(result) -> dict | None:
    """Extract spouse match info from a PipelineResult."""
    spouse = result.pensioner or {}
    first = spouse.get("spouse_first_name", "") or ""
    last = spouse.get("spouse_last_name", "") or ""
    if not first and not last:
        return None
    return {
        "first": first,
        "last": last,
        "matched": bool(result.both_match),
    }


def _build_common_record(
    pensioner_id,
    pensioner_name: str,
    engine: str,
    status: str,
    best_score: float,
    candidates: list[dict],
    engine_for_convert=None,
    corroboration: dict | None = None,
) -> dict:
    """Build the engine-agnostic common record shape (issue #39).

    If engine_for_convert is provided (a SearchEngine instance),
    candidates are converted via engine.to_common_candidate().
    Otherwise they are converted inline based on engine name
    ("findagrave" → FaG fields mapped to common shape).
    """
    common_candidates = candidates
    if engine_for_convert is not None and hasattr(engine_for_convert, "to_common_candidate"):
        common_candidates = [
            engine_for_convert.to_common_candidate(c)
            for c in candidates
        ]
    elif engine == "findagrave":
        common_candidates = [_convert_fag_candidate(c) for c in candidates]
    elif engine == "newspapers_com":
        common_candidates = [_convert_newspapers_candidate(c) for c in candidates]
    return {
        "id": pensioner_id,
        "title": pensioner_name,
        "engine": engine,
        "status": status,
        "best_score": best_score,
        "candidates": common_candidates,
        "corroboration": corroboration or {},
    }


def _convert_fag_candidate(c: dict) -> dict:
    """Convert a raw FaG candidate to common shape without an engine instance."""
    details = c.get("details") or {}
    evidence = c.get("score_evidence") or {}
    score_breakdown = evidence.get("score_breakdown", {})
    common_bd = {}
    if score_breakdown:
        common_bd = {
            "last_name": score_breakdown.get("last", 0),
            "first_name": score_breakdown.get("first", 0),
            "middle_name": score_breakdown.get("middle", 0),
            "year_window": score_breakdown.get("death", 0),
            "state": score_breakdown.get("state", 0),
            "ok_burial": score_breakdown.get("ok_burial", 0),
            "veteran": score_breakdown.get("veteran", 0),
        }
    return {
        "id": str(c.get("memorial_id", "")),
        "title": c.get("name", ""),
        "url": c.get("backlink", ""),
        "score": c.get("score", 0),
        "attributes": {
            "birth_year": details.get("birth_year", ""),
            "death_year": details.get("death_year", ""),
            "state": details.get("state", ""),
        },
        "media": {
            "image_url": c.get("iiif_url", ""),
        },
        "evidence": {
            "score_breakdown": common_bd,
            "raw": c,
        },
    }


def _convert_newspapers_candidate(c: dict) -> dict:
    """Convert a raw Newspapers.com candidate to common shape."""
    return {
        "id": str(c.get("id", "")),
        "title": c.get("title", ""),
        "url": (
            f"https://www.newspapers.com{c['href']}"
            if c.get("href")
            else ""
        ),
        "score": c.get("score", 0),
        "attributes": {
            "date": c.get("iso_date", ""),
            "location": c.get("location", ""),
        },
        "media": {
            "image_url": c.get("thumbnail", ""),
        },
        "evidence": {
            "score_breakdown": c.get("score_evidence", {}),
            "raw": c,
        },
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


# ============================================================
# Batch orchestration
# ============================================================
@dataclass
class BatchResult:
    """Result of a batch run."""
    total: int = 0
    processed: int = 0
    outliers_count: int = 0
    auto_accepts: int = 0
    errors: int = 0
    both_match_total: int = 0
    both_match_direct: int = 0
    both_match_corroborated: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def elapsed_seconds(self) -> float:
        return self.finished_at - self.started_at

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "processed": self.processed,
            "outliers_count": self.outliers_count,
            "auto_accepts": self.auto_accepts,
            "errors": self.errors,
            "both_match_total": self.both_match_total,
            "both_match_direct": self.both_match_direct,
            "both_match_corroborated": self.both_match_corroborated,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
        }


def _load_pensioners(args) -> list[dict]:
    """Load pensioner records from --input or --input-csv."""
    if args.input:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        return data
    if args.input_csv:
        import csv
        rows = list(csv.DictReader(open(args.input_csv, encoding="utf-8")))
        return rows
    raise SystemExit("Provide --input (ok_pensioners.json) or --input-csv")


def _load_cems(cgr_path: Path) -> list[dict]:
    """Load enriched CGR vets, group by cemetery."""
    by_cem = {}
    with cgr_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            cid = rec.get("cemetery_id")
            if cid not in by_cem:
                by_cem[cid] = {
                    "cemetery_id": cid,
                    "cemetery_name": rec.get("cemetery_name"),
                    "county": rec.get("county"),
                    "state": rec.get("state", "OK"),
                    "veterans": [],
                }
            by_cem[cid]["veterans"].append(rec)
    return list(by_cem.values())


# ============================================================
# Scheduler-driven batch runner (Phase W2)
# ============================================================


def run_batch_scheduler(
    pensioners: list[dict],
    cemeteries: list[dict],
    config: UnifiedRunnerConfig,
    log: Optional[logging.Logger] = None,
) -> BatchResult:
    """Run pensioners through Blackboard one durable vertical at a time.

    Each pensioner is ingested, scheduled, projected, and fsynced to the
    state file before the next pensioner starts. Existing state rows are
    treated as complete resume checkpoints.
    """
    from scripts.blackboard.projector import ProjectionBuilder
    from scripts.blackboard.scheduler import BlackboardScheduler
    from scripts.blackboard.schema import Kind, Observation, WorkItem
    from scripts.blackboard.store import BlackboardStore
    from scripts.knowledge.candidate_scorer import CandidateScorerKS, DeepRefinerKS
    from scripts.knowledge.fag_scraper import FaGScraperKS
    from scripts.knowledge.regional_planner import RegionalPlannerKS
    from scripts.state.repository import JsonlStateRepository

    if log is None:
        log = logging.getLogger("run_unified")

    store: BlackboardStore = getattr(config, "_blackboard_store", None)
    if store is None:
        raise ValueError(
            "Blackboard store must be opened before calling run_batch_scheduler"
        )
    if config.out_dir is None:
        raise ValueError("UnifiedRunnerConfig.out_dir must be set")

    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_repo = JsonlStateRepository(out_dir / config.results_filename)
    if not state_repo.path.exists():
        state_repo.path.touch()

    # Issue #68: write restart.sh for resuming failed runs
    write_restart_script(out_dir)

    # Copy view.html into out_dir so the reviewer has a per-run page
    # that works from file:// without a server.
    # NOTE: view.html is copied at the END of the run, not here.
    # The copy embeds results.jsonl at copy-time, so it must
    # happen AFTER the data is written. We mark the source path
    # and copy after the projection loop completes.
    view_html_source = config.view_html_source or Path("scripts/view/v2.html")

    # Issue #62: pensioncard_pages sidecar (loaded below)

    # Load pensioncard_pages sidecar (issue #62). v2 view
    # builds IIIF URLs from page_ids; without the sidecar the
    # pensioner record lacks `pensioncard_pages` and the
    # reviewer's pension card preview is empty.
    pensioncard_pages_cache: dict[str, list[int]] = {}
    if config.pensioncard_pages_path and config.pensioncard_pages_path.exists():
        try:
            pensioncard_pages_cache = json.loads(
                config.pensioncard_pages_path.read_text(encoding="utf-8")
            )
            log.info(
                "Loaded pensioncard_pages cache: %d entries from %s",
                len(pensioncard_pages_cache),
                config.pensioncard_pages_path,
            )
        except Exception as e:
            log.warning("pensioncard_pages cache load failed: %s", e)
    completed_ids = set()
    if not config.reprocess:
        completed_ids = {
            int(record["pensioner_id"])
            for record in state_repo.iter_all(strict=True)
            if record.get("pensioner_id") is not None
        }
    bounded = pensioners[: config.limit] if config.limit else pensioners
    remaining = [
        pensioner
        for pensioner in bounded
        if int(pensioner.get("id") or pensioner.get("application_number") or 0)
        not in completed_ids
    ]

    result = BatchResult(total=len(pensioners), started_at=time.time())
    run_id = config.run_manifest.run_id if config.run_manifest else "run"

    # Issue #71: structured audit log
    from scripts.pipeline.audit_log import RunAuditLog

    # Issue #75: open early so FaGScraperKS can emit per-strategy events.
    audit_log = RunAuditLog.open(out_dir / "run_audit.jsonl")

    # Issue #84: register audit_log as Blackboard observer so
    # all KSs and work transitions are automatically captured.
    store.register_observer(audit_log)  # type: ignore[attr-defined]

    # Issue #84: inline analytics aggregator.
    from scripts.analysis.run_analytics import AnalyticsAggregator

    analytics_aggregator = AnalyticsAggregator()
    store.register_observer(analytics_aggregator)  # type: ignore[attr-defined]

    # CGR observations — one per veteran, keyed by veteran ID as
    # pensioner_id so read_observations_for_pensioner() finds them.
    for cemetery in cemeteries:
        for veteran in cemetery.get("veterans", []):
            veteran_id = veteran.get("id", 0)
            if not veteran_id:
                continue
            store.append_observation(
                Observation(
                    observation_id=f"obs-cgr-vet-{veteran_id}",
                    pensioner_id=int(veteran_id),
                    kind=Kind.CGRCorroboration,
                    source="run_unified",
                    source_version="1",
                    run_id=run_id,
                    pass_id="ingest",
                    payload=dict(veteran),
                )
            )

    scheduler = BlackboardScheduler(store)
    scheduler.register(RegionalPlannerKS(enable_search=config.enable_fag))

    browser_session = None
    if config.enable_fag:
        from scripts.fag.browser_session import BrowserSession

        browser_session = BrowserSession(
            throttle=config.throttle_seconds,
            reset_every=config.browser_reset_every,
            headless=config.headless,
            state_filter=config.browser_state_filter,
            auto_relax=config.auto_relax,
            max_consecutive_errors=config.max_consecutive_errors,
            enforce_throttle_floor=config.enforce_throttle_floor,
        )
        browser_session.start()
        if config.mock_fag_path:
            browser_session.enable_mock_fag(str(config.mock_fag_path))
        scheduler.register(
            FaGScraperKS(
                browser_session=browser_session,
                engine=config.fag_engine,
                gate_min_interval=config.request_gate_min_interval,
                audit_log=audit_log,
            )
        )

    # Issue #78: thread search mode into DeepRefinerKS.
    mode_cfg = {
        "max_refinements": 6,
        "skip_refine_above": 0.85,
        "bail_on_auto_accept": True,
    }
    if config.search_mode:
        from scripts.batch_config import MODE_DEFAULTS
        preset = MODE_DEFAULTS.get(
            config.search_mode, MODE_DEFAULTS["standard"]
        )
        mode_cfg["max_refinements"] = preset["max_refinements"]
        mode_cfg["bail_on_auto_accept"] = preset["bail_on_auto_accept"]

    scheduler.register(CandidateScorerKS())
    scheduler.register(DeepRefinerKS(**mode_cfg))
    builder = ProjectionBuilder()

    # Issue #85: build CGR lookup from already-loaded cemetery data
    # so ProjectionBuilder can annotate rows with CGR corroboration.
    cgr_by_veteran_id: dict[int, dict[str, Any]] = {}
    for cemetery in cemeteries:
        for veteran in cemetery.get("veterans", []):
            vid = veteran.get("id", 0)
            if vid:
                cgr_by_veteran_id[vid] = dict(veteran)

    try:
        for pensioner in remaining:
            pensioner_id = int(
                pensioner.get("id")
                or pensioner.get("application_number")
                or 0
            )
            store.append_observation(
                Observation(
                    observation_id=f"obs-ingest-{pensioner_id}",
                    pensioner_id=pensioner_id,
                    kind=Kind.PensionerImported,
                    source="run_unified",
                    source_version="1",
                    run_id=run_id,
                    pass_id="ingest",
                    payload=dict(pensioner),
                )
            )
            store.enqueue_work(
                WorkItem(
                    work_id=f"work-plan-{pensioner_id}",
                    pensioner_id=pensioner_id,
                    knowledge_source="RegionalPlannerKS",
                )
            )

            # Issue #75: emit per-pensioner start for audit trail.
            audit_log.pensioner_start(
                str(pensioner_id),
                name=str(pensioner.get("name_raw", "") or f"#{pensioner_id}"),
            )

            result.processed += scheduler.run()
            if store.has_pending_work(pensioner_id):
                log.warning(
                    "Pensioner %d has deferred work; state row not checkpointed yet.",
                    pensioner_id,
                )
                continue
            observations = store.read_observations_for_pensioner(pensioner_id)
            candidates_by_id: dict[str, dict] = {}
            for observation in observations:
                if (
                    observation.kind != Kind.FaGCandidateFetch
                    or not observation.payload.get("memorial_id")
                ):
                    continue
                memorial_id = str(observation.payload["memorial_id"])
                current = candidates_by_id.get(memorial_id)
                if current is None or observation.payload.get(
                    "score", 0.0
                ) > current.get("score", 0.0):
                    candidates_by_id[memorial_id] = observation.payload

            # Issue #85: enrich projection with CGR + DD evidence.
            cgr_data: dict[str, Any] | None = None
            cgr_entry = cgr_by_veteran_id.get(pensioner_id)
            if cgr_entry:
                cgr_data = {"match_found": True, "match_details": cgr_entry}

            # DD evidence: read from store if available (written by
            # PostPassObserver during batch post-pass in previous runs).
            dd_data: dict[str, Any] | None = None
            for obs in observations:
                if obs.kind == Kind.DixieDataMatch:
                    dd_data = {
                        "match_found": obs.payload.get("match_found", False),
                        "match_details": obs.payload.get("match_details", {}),
                    }
                    break

            row = builder.build_state_row(
                pensioner_id=pensioner_id,
                pensioner_data=dict(pensioner),
                candidates=list(candidates_by_id.values()),
                cgr_data=cgr_data,
                dd_data=dd_data,
            )
            # Issue #62: populate pensioncard_pages from the
            # sidecar so v2 view's pension card preview works.
            if pensioncard_pages_cache:
                pages = pensioncard_pages_cache.get(str(pensioner_id))
                if pages:
                    row["pensioncard_pages"] = pages
            state_repo.append(row)
            if row.get("status") == "auto_accept":
                result.auto_accepts += 1

            audit_log.pensioner_end(
                pensioner_id=str(pensioner_id),
                total_candidates=len(candidates_by_id),
                status=row.get("status", "unknown"),
                best_score=float(row.get("best_score", 0) or 0),
            )
    finally:
        if browser_session is not None:
            browser_session.close()

    # Issue #85: run DixieData post-pass and append observations to store.
    # Done after all pensioners are processed so DD match can see full results.
    if os.environ.get("DIXIEDATA_DB") or os.environ.get("DIXIEDATA_ZIP_BACKUP"):
        try:
            from scripts.cgr.dixiedata_match import (
                _match_pensioner_to_dd,
                load_dd_index,
            )
            from scripts.pipeline.post_pass_observer import PostPassObserver

            dd_index = load_dd_index(
                db_path=os.environ.get("DIXIEDATA_DB"),
                zip_path=os.environ.get("DIXIEDATA_ZIP_BACKUP"),
            )
            if dd_index:
                dd_observer = PostPassObserver(run_id=run_id)
                dd_matched = 0
                for record in state_repo.iter_all(strict=True):
                    pid = record.get("pensioner_id")
                    if pid is None:
                        continue
                    dd_result = _match_pensioner_to_dd(record, dd_index)
                    if dd_result:
                        dd_observer.observe_dixiedata_match(
                            pensioner_id=int(pid),
                            dd_match=dd_result,
                            match_found=True,
                        )
                        dd_matched += 1
                dd_observer.write_to_store(store)
                log.info(
                    "DD post-pass: %d matches, wrote observations.",
                    dd_matched,
                )
        except Exception as exc:
            log.warning("DD post-pass failed (non-fatal): %s", exc)

    # Issue #88: spouse post-pass (opt-in via FAG_SCRAPE_SPOUSE=1).
    # Requires live browser navigation to each memorial page.
    if os.environ.get("FAG_SCRAPE_SPOUSE", "") in ("1", "true", "yes"):
        try:
            from scripts.cgr.spouse_compare import annotate_records_via_session

            log.info("Spouse post-pass: starting (may take a while)...")
            spouse_stats = annotate_records_via_session(
                results_path=state_repo.path,
                session=browser_session,
                store=store,
            )
            log.info(
                "Spouse post-pass: matched=%d, attempted=%d, errors=%d",
                spouse_stats.get("matched", 0),
                spouse_stats.get("total_attempted", 0),
                spouse_stats.get("errors", 0),
            )
        except Exception as exc:
            log.warning("Spouse post-pass failed (non-fatal): %s", exc)

    # Issue #85: enrich state rows with CGR + DD observations from store.
    # Reads all observations, finds CGR/DD annotations, and annotates
    # each state row in-place via JsonlStateRepository.replace_all().
    from scripts.post_pass import observation_enrichment as _oe
    _oe.run(
        state_repo,
        store,
        config=_oe.config_from(config),
        run_id=run_id,
        log=log,
    )

    # Issue #81: annotate results.jsonl with pensioncard_pages
    # post-hoc, so the operator can fetch pages at any time and
    # re-trigger view generation without re-running FaG.
    from scripts.post_pass import pensioncard_pages as _pcp
    _pcp.run(
        state_repo.path,
        config=_pcp.config_from(config),
        out_dir=out_dir,
        log=log,
    )

    # Copy view.html AFTER the data is written so the embedded
    # results.jsonl is populated. Earlier we deferred this
    # from the scheduler init; the embed-only-if-missing
    # semantics means the copy at init always saw an empty
    # results.jsonl, leaving v2 with no embedded data.
    from scripts.post_pass import view_copy as _vc
    _vc.run(
        config=_vc.config_from(
            config,
            dest_dir=out_dir,
            results_path=state_repo.path,
            source=view_html_source,
        ),
        log=log,
    )

    # Issue #55: post-run label collection.
    _collect_labels_if_enabled(config, out_dir, log)

    result.finished_at = time.time()
    audit_log.summary(
        total_pensioners=len(pensioners),
    )
    # Issue #84: write inline analytics report.
    analytics_aggregator.write_report(out_dir / "run_analytics.json")
    audit_log.close()
    log.info(
        "Scheduler batch complete: %d/%d pensioners projected to %s",
        len(remaining),
        len(bounded),
        state_repo.path,
    )
    return result


# ============================================================
# Post-run label collection (issue #55)
# ============================================================


def _clean_stale_blackboard(bb_path: Path, log: "logging.Logger | None" = None) -> None:
    """Remove stale blackboard database and WAL/journal files.

    The blackboard is a per-run transient store. If it exists
    from a prior run (aborted or completed), its WAL/journal
    sidecars will lock sqlite3 on the next open. Delete them
    so every run starts cleanly.
    """
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(bb_path) + suffix)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                if log:
                    log.warning("Could not remove stale %s", p)


def _post_process_only(
    config: "UnifiedRunnerConfig",
    out_dir: Path,
    log: "logging.Logger | None" = None,
) -> None:
    """Post-process-only mode: annotate existing results.jsonl
    with pensioncard_pages and regenerate view.html.

    Reads results.jsonl from *out_dir*, annotates with pension
    card pages if the sidecar exists, then writes a fresh
    view.html with embedded results. No FaG calls.
    """
    results_path = out_dir / config.results_filename
    if not results_path.exists():
        if log:
            log.error(
                "--post-process-only requires an existing %s in %s",
                config.results_filename, out_dir,
            )
        return

    # Count records for logging.
    n = 0
    if results_path.exists():
        with results_path.open(encoding="utf-8") as f:
            n = sum(1 for line in f if line.strip())
    if log:
        log.info("Post-process-only: %d records in %s", n, results_path)

    # Annotate pensioncard_pages.
    from scripts.post_pass import pensioncard_pages as _pcp
    _pcp.run(
        results_path,
        config=_pcp.config_from(config),
        out_dir=out_dir,
        log=log,
    )

    # Remove stale view.html so copy_view_html_if_missing regenerates.
    view_path = out_dir / "view.html"
    if view_path.exists():
        view_path.unlink()

    # Regenerate view.html with embedded results.
    from scripts.post_pass import view_copy as _vc2
    _vc2.run(
        config=_vc2.config_from(
            config, dest_dir=out_dir, results_path=results_path
        ),
        log=log,
    )

    if log:
        log.info(
            "Post-process-only complete: view.html regenerated in %s",
            out_dir,
        )


def _collect_labels_if_enabled(
    config: "UnifiedRunnerConfig",
    out_dir: Path,
    log: "logging.Logger | None" = None,
) -> None:
    """Collect training labels from decisions sidecar after batch.

    Reads the recipe's post config. When collect_labels is enabled,
    extracts labels from the decisions sidecar JSON and appends to
    the configured labels path.
    """
    recipe = getattr(config, "_recipe", None)
    if recipe is None:
        return
    post_cfg = getattr(recipe, "post", None)
    if post_cfg is None or not post_cfg.collect_labels:
        return

    from scripts.learning.label_extractor import LabelExtractor

    # Find the most recent decisions_*.json in the output dir
    sidecar_path = None
    for p in sorted(out_dir.glob("decisions_*.json"), reverse=True):
        sidecar_path = p
        break
    if sidecar_path is None:
        if log:
            log.info("No decisions sidecar found; skipping label collection.")
        return

    extractor = LabelExtractor()
    try:
        labels = extractor.from_decisions_file(sidecar_path)
    except Exception as e:
        if log:
            log.warning("Label extraction failed: %s", e)
        return

    if not labels:
        if log:
            log.info("No labels extracted from %s", sidecar_path)
        return

    labels_path = Path(post_cfg.labels_path)
    labels_path.parent.mkdir(parents=True, exist_ok=True)

    import json as _json
    with labels_path.open("a", encoding="utf-8") as f:
        for label in labels:
            f.write(_json.dumps({
                "pensioner_id": label.pensioner_id,
                "human_review_decision": label.human_review_decision,
                "extracted_at": label.extracted_at,
                "source_policy_version": label.source_policy_version,
            }) + "\n")

    if log:
        log.info(
            "Collected %d labels from %s → %s",
            len(labels), sidecar_path.name, labels_path,
        )


def cli_main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point: parse args, init Playwright, run batch.

    Usage:
      # Ad-hoc (legacy flags)
      python scripts/run_unified.py \\
        --input docs/research/digitalprairie/ok_pensioners.json \\
        --cgr docs/research/cgr/ok_vets_enriched.jsonl \\
        --out data/results/run_2026_07_16/ \\
        [--limit N] [--throttle 2.5] [--shuffle]

      # Batch config (preferred)
      python scripts/run_unified.py --config output/<runname>/config.json

      # Scaffold a new run
      python scripts/run_unified.py init-batch <runname>
    """
    import argparse
    parser = argparse.ArgumentParser(description="Unified runner CLI")
    # Subcommand: init-batch
    subparsers = parser.add_subparsers(dest="subcommand")
    init_p = subparsers.add_parser(
        "init-batch",
        help="Scaffold output/<runname>/config.json for a new run",
    )
    init_p.add_argument("runname", help="Slug identifying the run")
    init_p.add_argument(
        "--root", type=Path, default=Path("output"),
        help="Parent directory (default: output/)",
    )

    # Main parser (default subcommand = run)
    parser.add_argument("--input", type=Path,
                        help="Local path to ok_pensioners.json")
    parser.add_argument("--input-csv", type=Path,
                        help="Local path to a generic CSV (dixiedata-style)")
    parser.add_argument("--cgr", type=Path, required=False,
                        help="Enriched CGR JSONL (ok_vets_enriched.jsonl). "
                             "Required unless --config is used.")
    parser.add_argument("--config", type=Path, default=None,
                        help="Path to a batch config.json (output/<runname>/config.json). "
                             "When set, --input / --cgr / --out are derived from it.")
    parser.add_argument("--pensioncard-pages", type=Path, default=None,
                        help="Path to ok_pensioners.pensioncard_pages.json (the "
                             "sidecar built by scripts/ingest/fetch_pensioncard_pages.py). "
                             "When present, each results.jsonl record carries "
                             "pensioncard_pages: [page_id, ...] so view.html can "
                             "embed the IIIF images directly. See issue #13.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output directory (will be created). "
                             "When --config is used, defaults to output/<runname>/.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only first N pensioners (for tests)")
    parser.add_argument("--throttle", type=float, default=2.5,
                        help="Seconds between FaG requests (default 2.5; "
                             "raised from 1.5 after live monitoring showed "
                             "Cloudflare 1015 rate-limit hits at the "
                             "stricter cadence)")
    parser.add_argument("--mode", type=str, default=None,
                        choices=["conservative", "standard", "aggressive"],
                        help="Search aggressiveness mode (issue #78). "
                             "Controls refinement depth and bail policy. "
                             "Defaults to mode from config.json or "
                             "'standard' when neither is set.")
    parser.add_argument(
        "--low-score-threshold", type=float,
        # Default lives in scoring_constants.LOW_SCORE_THRESHOLD so
        # dry-run + outlier_classifier + this CLI all agree.
        # Issue #28 follow-up: one source of truth.
        help="Outlier threshold (top score below = outlier). "
             "Default: scripts.pipeline.scoring_constants.LOW_SCORE_THRESHOLD",
    )
    parser.add_argument("--shuffle", action="store_true",
                        help="Process pensioners in random order")
    parser.add_argument("--start-from", type=int, default=0,
                        help="Skip the first N pensioners in the list")
    parser.add_argument("--no-fag", action="store_true",
                        help="Skip FaG search (CGR-only mode, for testing)")
    parser.add_argument("--mock-fag", type=Path, default=None,
                        help="Path to HTML fixture for mock FaG search. "
                             "Intercepts all findagrave.com/memorial/search "
                             "requests and returns the fixture instead. "
                             "Cuts smoke-test wall-clock from ~270s to ~5s. "
                             "See issue #63.")
    parser.add_argument("--fag-state-filter", type=str, default=None,
                        help="FaG locationId scope. A US state abbr "
                             "('OK', 'TX'), 'US' for country_4, or '' "
                             "to disable. When --config is used, the "
                             "config's fag_state_filter is the default "
                             "(currently 'OK'). Override here to "
                             "broaden (e.g. '' for global) or scope to "
                             "another state.")
    # Issue #21: reversibility flags
    parser.add_argument("--dry-run", action="store_true",
                        help="Exercise the non-FaG pipeline (matching, "
                             "scoring, CGR) against an existing "
                             "state.jsonl and emit a JSONL diff showing "
                             "which records would change. NEVER makes a "
                             "FaG network request. Writes "
                             "<out>/dry_run_diff.jsonl.")
    parser.add_argument("--post-process-only", action="store_true",
                        help="Skip FaG search entirely; only annotate "
                             "existing results.jsonl with pensioncard_pages "
                             "and regenerate view.html. Use after fetching "
                             "pension card pages or adjusting view config. "
                             "Requires --config or --out + --pensioncard-pages.")
    parser.add_argument("--reprocess", action="store_true",
                        help="Re-process ALL pensioners, even those already "
                             "in results.jsonl. Default: skip completed.")
    parser.add_argument("--state-replay", type=Path, default=None,
                        help="Read OLD state.jsonl from this path, "
                             "apply the non-FaG pipeline, write NEW "
                             "state.jsonl in --out. Useful for A/B "
                             "testing strategy changes against "
                             "historical state without re-running FaG.")
    parser.add_argument("--rollback-to", type=str, default=None,
                        help="Restore state.jsonl from a named "
                             "checkpoint snapshot. Use 'latest' for "
                             "the most recent. Auto-checkpoints are "
                             "written every --checkpoint-every records "
                             "(default 1000).")
    parser.add_argument("--checkpoint-every", type=int, default=1000,
                        help="Write a state.jsonl checkpoint snapshot "
                             "every N records (default 1000). "
                             "Snapshots enable --rollback-to.")
    parser.add_argument("--checkpoint-label", type=str, default=None,
                        help="Optional label for the next manual "
                             "checkpoint snapshot written via "
                             "--write-checkpoint.")
    parser.add_argument("--write-checkpoint", action="store_true",
                        help="Write a checkpoint snapshot of the "
                             "current state.jsonl and exit (no "
                             "pipeline run). Use --checkpoint-label "
                             "to name it.")
    parser.add_argument("--list-checkpoints", action="store_true",
                        help="List all checkpoint snapshots for the "
                             "current run and exit.")
    parser.add_argument("--blackboard-db", type=Path, default=None,
                        help="Path to Blackboard SQLite database "
                             "(default: <out_dir>/blackboard.db).")
    parser.add_argument("--view-html-source", type=Path, default=None,
                        help="Source view.html to copy into the run directory "
                             "(default: scripts/view/v2.html). "
                             "Use scripts/view.html for the legacy v1 layout.")
    args = parser.parse_args(argv)

    # Issue #28 follow-up: if the user didn't pass
    # --low-score-threshold, default to the canonical constant.
    # argparse default=0.40 was a literal; we now read it from
    # scoring_constants to keep CLI in sync with dry-run.
    from scripts.pipeline.scoring_constants import LOW_SCORE_THRESHOLD
    if args.low_score_threshold is None:
        args.low_score_threshold = LOW_SCORE_THRESHOLD

    # ============================================================
    # Subcommand dispatch: init-batch
    # ============================================================
    if args.subcommand == "init-batch":
        from scripts.batch_config import init_batch as _init_batch, ConfigError
        try:
            created = _init_batch(args.runname, root=args.root)
        except ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"Initialized run: {created}")
        return 0

    # ============================================================
    # --config: load batch config and merge into args
    # ============================================================
    if args.config is not None:
        from scripts.batch_config import (
            load_config as _load_config,
            validate_config_against_dir as _validate_cfg_dir,
            ConfigError,
        )
        try:
            batch_cfg = _load_config(args.config)
        except ConfigError as e:
            print(f"error loading config: {e}", file=sys.stderr)
            return 1
        # Derive --out from config if not provided
        if args.out is None:
            args.out = args.config.parent
        # Validate runname matches out_dir basename
        try:
            _validate_cfg_dir(batch_cfg, args.out)
        except ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        # Apply config to args (CLI overrides config)
        if args.input is None and args.input_csv is None:
            args.input = batch_cfg.input_path
        if args.cgr is None:
            args.cgr = batch_cfg.cgr_path
        if args.throttle == 2.5:  # default sentinel
            args.throttle = batch_cfg.throttle
        if args.low_score_threshold is None:  # user didn't pass --low-score-threshold
            # default lives in scoring_constants; defer to batch_cfg
            # when one is loaded.
            args.low_score_threshold = batch_cfg.low_score_threshold
        if args.fag_state_filter is None:
            args.fag_state_filter = batch_cfg.fag_state_filter
        # start_row / end_row -> start_from + limit
        if args.start_from == 0:
            args.start_from = batch_cfg.start_row
        if args.limit is None and batch_cfg.end_row is not None:
            size = batch_cfg.end_row - batch_cfg.start_row
            if size > 0:
                args.limit = size
        args.batch_cfg = batch_cfg
    else:
        args.batch_cfg = None

    # --cgr is required when --config is not used
    if args.config is None and args.cgr is None:
        print("error: --cgr is required (or pass --config)", file=sys.stderr)
        return 1
    # --input OR --input-csv is required when --config is not used
    if args.config is None and args.input is None and args.input_csv is None:
        print(
            "error: provide --input (ok_pensioners.json) or --input-csv",
            file=sys.stderr,
        )
        return 1
    # --out is required when --config is not used
    if args.config is None and args.out is None:
        print("error: --out is required (or pass --config)", file=sys.stderr)
        return 1

    # Issue #21: early-exit commands. Handle their own I/O and
    # skip the entire pipeline setup. Each returns 0 on success.
    if args.list_checkpoints:
        from scripts.pipeline.checkpoint import list_checkpoints
        state_path = Path(args.out) / "results.jsonl"
        snaps = list_checkpoints(state_path)
        if not snaps:
            print(f"No checkpoints found for {state_path}")
            return 0
        print(f"Checkpoints for {state_path}:")
        for s in snaps:
            print(f"  {s.name}")
        return 0

    if args.write_checkpoint:
        from scripts.pipeline.checkpoint import write_checkpoint_snapshot
        state_path = Path(args.out) / "results.jsonl"
        if not state_path.exists():
            print(f"error: state file not found: {state_path}", file=sys.stderr)
            return 1
        snap = write_checkpoint_snapshot(state_path, label=args.checkpoint_label)
        print(f"Checkpoint written: {snap}")
        return 0

    if args.rollback_to:
        from scripts.pipeline.checkpoint import rollback_to_checkpoint
        state_path = Path(args.out) / "results.jsonl"
        if not state_path.exists():
            print(f"error: state file not found: {state_path}", file=sys.stderr)
            return 1
        try:
            rollback_to_checkpoint(state_path, label=args.rollback_to)
            print(f"Rolled back {state_path} to checkpoint {args.rollback_to!r}")
            return 0
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    # Setup logger
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    log = logging.getLogger("run_unified_main")
    log.setLevel(logging.INFO)
    # Always clear existing handlers
    for h in list(log.handlers):
        log.removeHandler(h)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    log.addHandler(stream_handler)

    log.info("Run starting at %s", now_iso())
    log.info("Output dir: %s", out_dir)
    log.info("Args: %s", vars(args))

    # Load pensioners
    pensioners = _load_pensioners(args)
    if args.shuffle:
        import random
        random.shuffle(pensioners)
    if args.start_from:
        pensioners = pensioners[args.start_from:]
    log.info("Loaded %d pensioners from input", len(pensioners))

    # Load CGR
    if not Path(args.cgr).exists():
        log.error("CGR file not found: %s", args.cgr)
        return 1
    cems = _load_cems(Path(args.cgr))
    log.info("Loaded CGR data: %d cemeteries, %d total vets",
             len(cems), sum(len(c.get("veterans", [])) for c in cems))

    # Scheduler path uses BrowserSession; no legacy fag_search_fn needed
    fag_search_fn = None

    # Run batch
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        throttle_seconds=args.throttle,
        low_score_threshold=args.low_score_threshold,
        max_cgr_candidates=20,
        limit=args.limit,
        enable_fag=not args.no_fag and not args.dry_run,
        fag_search_fn=fag_search_fn,
        write_heartbeat_every=50,
        checkpoint_every=args.checkpoint_every,
        # J5-S2: per-run Results filename + view.html source.
        # Default results.jsonl; CLI/config can override.
        results_filename=getattr(args, "results_filename", "results.jsonl"),
        view_html_source=getattr(args, "view_html_source", None) or Path("scripts/view/v2.html"),
        # J6: pensioncard pages sidecar (view.html embeds IIIF images).
        pensioncard_pages_path=getattr(args, "pensioncard_pages", None),
        # J7: CGR path for post-run dedup.
        cgr_path=Path(args.cgr) if args.cgr else None,
        blackboard_db_path=args.blackboard_db or (out_dir / "blackboard.db"),
        enforce_throttle_floor=True,
        request_gate_min_interval=args.throttle,
        mock_fag_path=args.mock_fag if args.mock_fag else None,
        search_mode=args.mode or "standard",
        reprocess=getattr(args, "reprocess", False),
    )
    # Issue #55: attach recipe for post-run label collection.
    if args.config is not None:
        cfg._recipe = batch_cfg

    # --post-process-only: annotate existing results.jsonl + regenerate
    # view.html, then exit. No FaG, no blackboard, no browser.
    if getattr(args, "post_process_only", False):
        _post_process_only(cfg, out_dir, log)
        return 0

    # Blackboard bootstrap
    # The blackboard is a per-run transient store; any stale
    # WAL/journal files from a prior aborted run will lock it.
    # Delete the old db so every run starts with a clean slate.
    # Durable data lives in results.jsonl + run_audit.jsonl.
    from scripts.blackboard.store import SqliteBlackboardStore
    from scripts.blackboard.schema import RunManifest
    from scripts.batch_config import build_manifest

    bb_path = cfg.blackboard_db_path
    _clean_stale_blackboard(bb_path, log)
    log.info("Blackboard store: %s", bb_path)
    blackboard_store = SqliteBlackboardStore(bb_path)
    blackboard_store.open()

    # Build manifest from config if available
    if args.config:
        from scripts.batch_config import load_config
        batch_cfg = load_config(args.config)
        manifest = build_manifest(batch_cfg, policy_version="1")
    else:
        import uuid as _uuid
        manifest = RunManifest(
            manifest_id=f"manifest-{_uuid.uuid4().hex[:8]}",
            run_id=out_dir.name,
            policy_version="1",
        )
    cfg.run_manifest = manifest
    cfg._blackboard_store = blackboard_store  # type: ignore[attr-defined]

    # Issue #21: --state-replay. Read OLD state, apply non-FaG
    # pipeline, write NEW state to out_dir/results.jsonl. Exits
    # before the normal pipeline starts.
    if args.state_replay:
        from scripts.pipeline.state_replay import replay_state
        new_state_path = out_dir / "results.jsonl"
        log.info(
            "state-replay: %s -> %s (threshold=%.2f)",
            args.state_replay, new_state_path, args.low_score_threshold,
        )
        n = replay_state(
            old_state_path=args.state_replay,
            new_state_path=new_state_path,
            low_score_threshold=args.low_score_threshold,
        )
        log.info("Replayed %d records", n)
        return 0

    try:
        result = run_batch_scheduler(
            pensioners=pensioners,
            cemeteries=cems,
            config=cfg,
            log=log,
        )
        log.info("Run finished: %s", json.dumps(result.to_dict(), indent=2))

        # Issue #21: --dry-run emits a JSONL diff after the pipeline
        # runs. The diff compares the just-written state.jsonl against
        # either an explicit baseline (results.jsonl.before, copied
        # manually before the run) or a fresh empty baseline (every
        # record is 'new' = changed).
        if args.dry_run:
            from scripts.pipeline.dry_run import (
                predict_outcome_from_state,
                write_dry_run_diff,
            )
            from scripts.state.repository import JsonlStateRepository
            predictions = [
                predict_outcome_from_state(r, args.low_score_threshold)
                for r in JsonlStateRepository(out_dir / "results.jsonl").iter_all()
            ]
            baseline = out_dir / "results.jsonl.before"
            if not baseline.exists():
                # Synthesize an empty baseline so every record counts
                # as 'new'. write_dry_run_diff handles missing files.
                baseline = out_dir / "results.jsonl.before.missing"
            diff_path = out_dir / "dry_run_diff.jsonl"
            n_changed = write_dry_run_diff(
                out_path=diff_path,
                current_state_path=baseline,
                predictions=predictions,
            )
            log.info(
                "dry-run: %d/%d records would change (diff: %s)",
                n_changed, len(predictions), diff_path,
            )

        return 0
    except KeyboardInterrupt:
        log.warning("Interrupted by user. State has been flushed.")
        try:
            if args.config is not None:
                write_resume_artifact(
                    out_dir=out_dir,
                    config_path=args.config,
                    log=log,
                )
                log.info("Resume artifact written after interrupt.")
        except Exception as e:
            log.error("Resume artifact write failed after interrupt: %s", e)
        return 130
    finally:
        # Close Blackboard store if scheduler was used
        bb_store = getattr(cfg, "_blackboard_store", None)
        if bb_store is not None:
            try:
                bb_store.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(cli_main())