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
from typing import Callable, Optional

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
from scripts.state.report_generator import (
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
    throttle_seconds: float = 2.5
    low_score_threshold: float = 0.40
    max_cgr_candidates: int = 20
    # Limits
    limit: Optional[int] = None
    # Behavioral
    write_outliers_separately: bool = True
    write_heartbeat_every: int = 50  # every N pensioners
    # Pensioncard pages sidecar (J6). Built by
    # scripts/ingest/fetch_pensioncard_pages.py. Maps
    # pensioner_id (str) -> [page_id, ...] (the IIIF image IDs for
    # Side 1, Side 2, ...). view.html embeds the images directly.
    pensioncard_pages_path: Optional[Path] = None
    # CGR source JSONL path. Used by the post-run CGR <-> FaG
    # dedup (scripts/cgr/cgr_fag_dedup.py). When None, the dedup
    # is skipped.
    cgr_path: Optional[Path] = None
    # Browser (kept abstract; the actual FaG search is injected)
    fag_search_fn: Optional[Callable] = None
    # Per-run isolation (J5-S2)
    # Filename for per-pensioner results within out_dir. Defaults to
    # "results.jsonl" (one Results file per run, named after the
    # run). Legacy "state.jsonl" is still supported by passing it
    # explicitly — ResumeTracker + run_batch are filename-agnostic.
    results_filename: str = "results.jsonl"
    # Path to the source view.html to copy into out_dir at run start.
    # The copy is skipped if out_dir/view.html already exists
    # (preserves user edits during review).
    view_html_source: Optional[Path] = None


# ============================================================
# view.html copy (J5-S2 + J9 embed)
# ============================================================
# J9: when the runner copies view.html into the run dir, it also
# embeds the matching results.jsonl as a <script type="application/json">
# block. This makes the page work standalone when opened from
# file:// (where fetch() of sibling files is blocked by the
# browser) or from a simple http server. The view.html JS
# reads from the embedded block first, then falls back to fetch.
EMBEDDED_DATA_PLACEHOLDER = "<!--EMBEDDED_RESULTS_JSONL-->"
EMBEDDED_DD_MATCH_PLACEHOLDER = "<!--EMBEDDED_DD_MATCH_JSON-->"
EMBEDDED_SPOUSE_MATCH_PLACEHOLDER = "<!--EMBEDDED_SPOUSE_MATCH_JSON-->"


def copy_view_html_if_missing(
    source: Optional[Path],
    dest_dir: Path,
    dest_filename: str = "view.html",
    results_path: Optional[Path] = None,
    dd_match_path: Optional[Path] = None,
) -> bool:
    """Copy source → dest_dir/dest_filename iff dest doesn't exist.

    If `results_path` is provided AND the source view.html contains
    the EMBEDDED_DATA_PLACEHOLDER, the matching JSONL content is
    injected as a <script type="application/json"> block so the
    page works from file:// without needing a server.

    If `dd_match_path` is provided AND the source contains the
    EMBEDDED_DD_MATCH_PLACEHOLDER, the matching JSON sidecar is
    similarly embedded (J14).

    Returns True if a copy happened, False otherwise (skipped because
    dest exists, or source missing, or source/dest identical path).
    Never raises on missing source — the run proceeds without a
    per-run view.html.
    """
    if source is None:
        return False
    source = Path(source)
    dest_dir = Path(dest_dir)
    dest = dest_dir / dest_filename
    if dest.exists():
        return False
    if not source.exists():
        return False
    dest_dir.mkdir(parents=True, exist_ok=True)

    text = source.read_text(encoding="utf-8")
    # Embed the results.jsonl as a JSON script block (J9).
    if results_path is not None and EMBEDDED_DATA_PLACEHOLDER in text:
        if results_path.exists():
            embedded = results_path.read_text(encoding="utf-8")
            # Escape </script> inside the JSON to keep the script
            # block well-formed (the JSON itself shouldn't contain
            # it, but defense in depth).
            safe = embedded.replace("</script>", "<\\/script>")
            block = (
                f'<script type="application/json" id="embedded-results-jsonl">\n'
                f'{safe}\n'
                f'</script>\n'
            )
            text = text.replace(EMBEDDED_DATA_PLACEHOLDER, block)
        else:
            # No results yet; drop the placeholder so the page
            # still loads (the user can pick a file manually).
            text = text.replace(EMBEDDED_DATA_PLACEHOLDER, "")

    # J14: same embed pattern for the dd_match sidecar.
    if dd_match_path is not None and EMBEDDED_DD_MATCH_PLACEHOLDER in text:
        if dd_match_path.exists():
            sidecar = dd_match_path.read_text(encoding="utf-8")
            safe = sidecar.replace("</script>", "<\\/script>")
            block = (
                f'<script type="application/json" id="embedded-dd-match">\n'
                f'{safe}\n'
                f'</script>\n'
            )
            text = text.replace(EMBEDDED_DD_MATCH_PLACEHOLDER, block)
        else:
            # No DD sidecar yet (e.g. no DD source configured).
            text = text.replace(EMBEDDED_DD_MATCH_PLACEHOLDER, "")

    # J15-S2: spouse_match sidecar (gold 'Spouse match' badge data).
    spouse_match_path = dest_dir / "spouse_match.json"
    if spouse_match_path is not None and EMBEDDED_SPOUSE_MATCH_PLACEHOLDER in text:
        if spouse_match_path.exists():
            sidecar = spouse_match_path.read_text(encoding="utf-8")
            safe = sidecar.replace("</script>", "<\\/script>")
            block = (
                f'<script type="application/json" id="embedded-spouse-match">\n'
                f'{safe}\n'
                f'</script>\n'
            )
            text = text.replace(EMBEDDED_SPOUSE_MATCH_PLACEHOLDER, block)
        else:
            text = text.replace(EMBEDDED_SPOUSE_MATCH_PLACEHOLDER, "")

    dest.write_text(text, encoding="utf-8")
    return True


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
    return record


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


def run_batch(
    pensioners: list[dict],
    cemeteries: list[dict],
    config: UnifiedRunnerConfig,
    log: Optional[logging.Logger] = None,
    config_path_for_resume: Optional[Path] = None,
) -> BatchResult:
    """Run the unified pipeline on a batch of pensioners.

    For each pensioner:
      - Skip if already in state file (resume)
      - Run CGR + FaG
      - Write state.jsonl line
      - Write outliers.jsonl line if outlier

    At end: writes report.md + report.json. If
    config_path_for_resume is provided, also writes the
    resume.sh artifact (J5-S3) so the run can be picked up
    from the same point on the next invocation.

    Args:
        pensioners: list of pensioner dicts
        cemeteries: list of cemetery records for CGR blocking index
        config: UnifiedRunnerConfig with fag_search_fn injected
        log: optional logger
        config_path_for_resume: path to output/<runname>/config.json;
            used to build the resume.sh artifact. If None, no artifact
            is written (legacy callers).
    """
    if log is None:
        log = logging.getLogger("run_unified")

    if config.out_dir is None:
        raise ValueError("UnifiedRunnerConfig.out_dir must be set")
    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Per-run Results file (J5-S2). Default results.jsonl; legacy
    # state.jsonl supported by passing it explicitly.
    state_path = out_dir / config.results_filename
    outliers_path = out_dir / "outliers.jsonl"

    # view.html copy (J5-S2 + J9 embed). No-op if source missing or
    # dest exists. When embedding, also pass the just-opened state_path
    # so the matching results.jsonl is injected into the page.
    if config.view_html_source is not None:
        # state_path is the per-run results file (results.jsonl
        # by default after S2; state.jsonl if --results-filename
        # was set to that). Pass it for embedding.
        copy_view_html_if_missing(
            config.view_html_source,
            out_dir,
            results_path=state_path,
        )

    # Resume support
    tracker = ResumeTracker(state_path)

    # Pensioncard pages sidecar (J6). Loaded once at start; per-record
    # lookup happens in the pensioner loop. Missing file = no
    # enrichment (view.html falls back to no embedded image).
    pensioncard_pages_cache: dict = {}
    if config.pensioncard_pages_path and config.pensioncard_pages_path.exists():
        try:
            pensioncard_pages_cache = json.loads(
                config.pensioncard_pages_path.read_text(encoding="utf-8")
            )
            log.info(
                "Loaded pensioncard_pages cache: %d entries from %s",
                len(pensioncard_pages_cache), config.pensioncard_pages_path,
            )
        except (json.JSONDecodeError, OSError) as e:
            log.warning("pensioncard_pages cache load failed: %s", e)
    if tracker.count() > 0:
        log.info(
            "Resume: %d pensioners already in state file %s",
            tracker.count(), state_path,
        )

    # Apply limit (after resume, if any)
    # First: filter out completed pensioners
    not_done = [p for p in pensioners if not tracker.is_done(p["id"])]
    if config.limit:
        remaining = not_done[:config.limit]
    else:
        remaining = not_done

    log.info(
        "Will process %d pensioners (total=%d, already done=%d, remaining in run=%d)",
        len(remaining), len(pensioners), tracker.count(), len(remaining),
    )

    # Stats
    result = BatchResult(
        total=len(pensioners),
        started_at=time.time(),
        processed=0,
    )

    # Build CGR blocking index ONCE for the whole batch. Without this,
    # the pipeline rebuilds a 2,593-vet phonetic index per pensioner
    # which allocates MB-sized dicts on every call and prevents the
    # OS from reclaiming the pages — observed RSS growth was ~85 MB/min
    # over a 7709-record run, regardless of FaG activity.
    prebuilt_cgr_index = build_cgr_blocking_index(cemeteries)
    if len(remaining) > 100:
        log.info(
            "CGR blocking index pre-built once: %d vet IDs across %d blocks",
            len(prebuilt_cgr_index[1]),
            len(prebuilt_cgr_index[0]),
        )

    pipeline_cfg = PipelineConfig(throttle_seconds=config.throttle_seconds)
    outlier_cfg = OutlierConfig(low_score_threshold=config.low_score_threshold)
    last_heartbeat = result.started_at

    for i, pensioner in enumerate(remaining):
        pid = pensioner.get("id")
        # Per-pensioner try/except so one bad record doesn't crash the batch
        try:
            pipeline_result = run_pipeline_for_pensioner(
                pensioner=pensioner,
                cgr_index_vets=cemeteries,
                config=pipeline_cfg,
                fag_search_fn=config.fag_search_fn,
                prebuilt_cgr_index=prebuilt_cgr_index,
            )
            record = result_to_dict(
                pipeline_result,
                pensioncard_pages_cache=pensioncard_pages_cache,
            )
            # Track stats
            result.processed += 1
            if pipeline_result.cgr_records and pipeline_result.fag_records:
                if pipeline_result.both_match:
                    result.both_match_total += 1
                    method = pipeline_result.both_match.get("method", "")
                    if method == "direct_link":
                        result.both_match_direct += 1
                    elif method == "corroboration":
                        result.both_match_corroborated += 1
            if record.get("fag_status") == "auto_accept":
                result.auto_accepts += 1
            # Write unified line
            write_unified_line(state_path, record)
            # Write outlier line if applicable
            if is_outlier(record, outlier_cfg):
                write_outliers_line(outliers_path, record)
                result.outliers_count += 1
            log.debug(
                "Processed pensioner #%d (%s %s): fag_status=%s",
                pid, pensioner.get("first_name"), pensioner.get("last_name"),
                record.get("fag_status"),
            )
        except Exception as e:
            log.error(
                "Failed pensioner #%d: %s\n%s",
                pid, e, traceback.format_exc()[:500],
            )
            result.errors += 1
            # Still flush a record for this pensioner so it's "done"
            try:
                err_record = {
                    "pensioner_id": pid,
                    "pensioner_name": " ".join([
                        str(pensioner.get("first_name", "")),
                        str(pensioner.get("last_name", "")),
                    ]).strip(),
                    "fag_status": "error",
                    "cgr_status": "error",
                    "error": str(e)[:200],
                    "best_score": 0.0,
                    "cgr_records": [],
                    "fag_records": [],
                    "ranked_candidates": [],
                    "status": "error",
                    "timestamp": now_iso(),
                }
                write_unified_line(state_path, err_record)
            except Exception:
                pass

        # Heartbeat every N records OR every minute
        now = time.time()
        if (i + 1) % config.write_heartbeat_every == 0 or (now - last_heartbeat) > 60:
            heartbeat_logger(
                log, state_path=state_path,
                total=len(remaining), processed=i + 1,
                started_at=result.started_at, now=now,
            )
            last_heartbeat = now

    result.finished_at = time.time()
    log.info(
        "Batch complete: %d/%d processed, %d outliers, %d errors, "
        "%d BOTH MATCH (%d direct, %d corroborated). Elapsed: %.1f min",
        result.processed, len(remaining), result.outliers_count, result.errors,
        result.both_match_total, result.both_match_direct, result.both_match_corroborated,
        result.elapsed_seconds / 60,
    )

    # Final report
    try:
        all_records = []
        if state_path.exists():
            with state_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        all_records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        if all_records:
            stats = build_report(all_records)
            ts = now_iso().replace(":", "").replace("-", "")[:15]
            write_report(stats, all_records, out_dir, timestamp=ts)
            log.info("Report written to %s", out_dir)
    except Exception as e:
        log.error("Report generation failed: %s", e)

    # CGR <-> FaG dedup (J7). After the report, before the resume
    # artifact, so the dedup reflects the final state. Annotates
    # each results.jsonl record in place and writes a summary to
    # cgr_fag_dedup.json in the run dir.
    if config.cgr_path is not None:
        try:
            from scripts.cgr.cgr_fag_dedup import run_dedup
            dedup_report = run_dedup(
                results_path=state_path,
                cgr_path=Path(config.cgr_path),
                output_path=out_dir / "cgr_fag_dedup.json",
                cgr_blocking_index=prebuilt_cgr_index,
            )
            counts = dedup_report.get("stats", {}).get(
                "pensioner_count_by_status", {}
            )
            log.info(
                "CGR dedup: %s",
                ", ".join(f"{k}={v}" for k, v in counts.items()),
            )
        except Exception as e:
            log.error("CGR dedup failed: %s", e)

    # J14: dixiedata post-pipeline comparison. For each pensioner,
    # check if the top-ranked FaG candidate's memorial_id is
    # already tracked in the user's dixiedata DB. Marks matching
    # records with `dd_match: {...}` so view.html can show a
    # 'DD tracked' badge and a filter to hide them. Read-only on
    # dixiedata; never mutates it. Skipped silently when no DD
    # source is configured (env vars or common default paths).
    try:
        from scripts.cgr.dixiedata_match import annotate_results_with_dd, load_dd_index
        # Read env vars; empty string -> skip
        raw_zip = os.environ.get("DIXIEDATA_ZIP_BACKUP", "").strip()
        raw_db = os.environ.get("DIXIEDATA_DB", "").strip()
        dd_zip = Path(raw_zip) if raw_zip else None
        dd_db = Path(raw_db) if raw_db else None
        dd_index = load_dd_index(db_path=dd_db, zip_path=dd_zip)
        if dd_index:
            dd_stats = annotate_results_with_dd(
                results_path=state_path,
                dd_index=dd_index,
                match_strength="weak",
            )
            dd_sidecar = out_dir / "dd_match.json"
            dd_stats["dd_index_size"] = len(dd_index)
            dd_stats["dd_zip_backup"] = raw_zip
            dd_stats["dd_db"] = raw_db
            dd_sidecar.write_text(json.dumps(dd_stats, indent=2), encoding="utf-8")
            log.info(
                "DD match: %d/%d pensioners already in dixiedata (sidecar=%s)",
                dd_stats["matched"], dd_stats["total"], dd_sidecar,
            )
        else:
            log.info(
                "DD match: skipped (DIXIEDATA_DB / DIXIEDATA_ZIP_BACKUP not set or paths invalid)"
            )
    except Exception as e:
        log.warning("DD match skipped: %s", e)

    # J15-S2: post-pipeline spouse scrape (opt-in via FAG_SCRAPE_SPOUSE=1).
    # Walks the just-written results.jsonl, fetches the top-N candidate's
    # memorial page, parses Family Members > Spouse, compares with the
    # pensioner's known spouse, writes spouse_match per record. Read-only
    # on FaG + the existing results file.
    #
    # The scrape is invoked as a SUBPROCESS so it gets a fresh asyncio
    # event loop. The per-pensioner search loop above already opened
    # and closed a sync_playwright session; reusing sync_playwright
    # in the same Python process for this second step fails with
    # "It looks like you are using Playwright Sync API inside the
    # asyncio loop."
    if os.environ.get("FAG_SCRAPE_SPOUSE", "").strip() in ("1", "true", "yes"):
        try:
            sp_sidecar = out_dir / "spouse_match.json"
            # Use the same Python interpreter that's running us.
            py = sys.executable
            # top_n is configurable via env var SPOUSE_SCRAPE_TOP_N
            # (default 1; set to 3 for rank-2/3 widening per issue #14).
            top_n_str = os.environ.get("SPOUSE_SCRAPE_TOP_N", "1").strip()
            try:
                top_n = int(top_n_str)
            except ValueError:
                top_n = 1
            if top_n < 1:
                top_n = 1
            cmd = [
                py, "-m", "scripts.cgr.spouse_compare",
                "--results", str(state_path),
                "--sidecar-out", str(sp_sidecar),
                "--top-n", str(top_n),
                "--throttle", str(config.throttle_seconds),
            ]
            log.info("Spouse scrape: launching subprocess (top_n=%d) %s",
                     top_n, " ".join(cmd))
            rc = subprocess.call(cmd)
            log.info("Spouse scrape subprocess exit code: %s", rc)
            if sp_sidecar.exists():
                try:
                    sp_stats = json.loads(sp_sidecar.read_text(encoding="utf-8"))
                    log.info(
                        "Spouse scrape: %d/%d pensioners matched "
                        "(%s) — sidecar=%s",
                        sp_stats.get("matched", 0),
                        sp_stats.get("total_with_spouse", 0),
                        sp_stats.get("matched_strength_breakdown", {}),
                        sp_sidecar,
                    )
                except Exception:
                    log.warning("Spouse sidecar JSON unreadable")
        except Exception as e:
            log.warning("Spouse scrape skipped: %s", e)
    else:
        log.info(
            "Spouse scrape: skipped (FAG_SCRAPE_SPOUSE not set; "
            "set to 1 to enable)"
        )

    # J5-S3: resume.sh artifact. Written after the report so the
    # final state is captured by the next resume.
    if config_path_for_resume is not None:
        try:
            resume_path = write_resume_artifact(
                out_dir=out_dir,
                config_path=config_path_for_resume,
                log=log,
            )
            log.info("Resume artifact: %s", resume_path)
        except Exception as e:
            log.error("Resume artifact write failed: %s", e)

    # J14: copy view.html again, this time with the dd_match.json
    # sidecar embedded (the initial copy at the start of run_batch
    # happened BEFORE dd_match.json existed; that first copy
    # embedded results.jsonl only). We don't overwrite an existing
    # customized view.html; we only do the second copy when the
    # embedded-block variant is missing.
    try:
        dd_sidecar_path = out_dir / "dd_match.json"
        # Only do the second copy if the first copy exists AND we
        # have a sidecar AND the sidecar wasn't embedded (the
        # first copy would have left the placeholder empty). The
        # easy heuristic: look for the embedded-dd-match id in the
        # current view.html; if not present, do a sidecar embed pass.
        # Also, embed results.jsonl on the second pass when the
        # first copy happened before results.jsonl existed (the
        # placeholder was already replaced with empty content, so
        # we instead inject the script block directly at the
        # placeholder location).
        view_path = out_dir / "view.html"
        if view_path.exists():
            text = view_path.read_text(encoding="utf-8")
            mutated = False
            # J9: results.jsonl may not have been embedded if the
            # first copy happened too early. Check for the actual
            # <script> tag, not the placeholder (the first copy
            # replaces the placeholder with either a real script
            # block, or an empty string when results.jsonl didn't
            # exist yet). Detect "embedded-results-jsonl" id.
            # NOTE: the source template has the literal string
            # 'id="embedded-results-jsonl"' inside JS comments,
            # which would make a naive substring check return True
            # even when no <script> tag exists. Use a regex that
            # matches an actual <script ...> tag.
            import re
            # The source template has the literal string
            # 'id="embedded-..."' inside HTML AND JS comments
            # (in the docstring at lines ~316 and ~1524). A naive
            # substring check would return True even when no
            # <script> tag exists. Require BOTH a `<script
            # type="application/json"` start tag AND an actual
            # JSON opening brace `{` immediately after. Real embed
            # blocks look like:
            #   <script type="application/json" id="...">{ ... }
            # Comments never have both adjacent.
            results_embedded_re = re.compile(
                r'<script\s+type="application/json"\s+id="embedded-results-jsonl"'
                r'>\s*\{',
            )
            dd_embedded_re = re.compile(
                r'<script\s+type="application/json"\s+id="embedded-dd-match"'
                r'>\s*\{',
            )
            spouse_embedded_re = re.compile(
                r'<script\s+type="application/json"\s+id="embedded-spouse-match"'
                r'>\s*\{',
            )
            if state_path.exists() and not results_embedded_re.search(text):
                # Insert the script block right where the J9
                # placeholder used to be (preserve any preceding
                # comments). Just append at the end of <head>.
                embedded = state_path.read_text(encoding="utf-8")
                safe = embedded.replace("</script>", "<\\/script>")
                block = (
                    f'<script type="application/json" id="embedded-results-jsonl">\n'
                    f'{safe}\n'
                    f'</script>\n'
                )
                # Insert before </head>
                if "</head>" in text:
                    text = text.replace("</head>", block + "</head>")
                else:
                    text += block
                mutated = True
            if dd_sidecar_path.exists() and not dd_embedded_re.search(text):
                embedded = dd_sidecar_path.read_text(encoding="utf-8")
                safe = embedded.replace("</script>", "<\\/script>")
                block = (
                    f'<script type="application/json" id="embedded-dd-match">\n'
                    f'{safe}\n'
                    f'</script>\n'
                )
                if "</head>" in text:
                    text = text.replace("</head>", block + "</head>")
                else:
                    text += block
                mutated = True
            # J15-S2: spouse_match sidecar embed
            sp_sidecar_path = out_dir / "spouse_match.json"
            if sp_sidecar_path.exists() and not spouse_embedded_re.search(text):
                embedded = sp_sidecar_path.read_text(encoding="utf-8")
                safe = embedded.replace("</script>", "<\\/script>")
                block = (
                    f'<script type="application/json" id="embedded-spouse-match">\n'
                    f'{safe}\n'
                    f'</script>\n'
                )
                if "</head>" in text:
                    text = text.replace("</head>", block + "</head>")
                else:
                    text += block
                mutated = True
            if mutated:
                view_path.write_text(text, encoding="utf-8")
                log.info("Embedded missing sidecars in view.html (second pass)")
    except Exception as e:
        log.warning("Second-pass view.html embed failed: %s", e)

    return result


# ============================================================
# CLI main() — for the real 7,758 run
# ============================================================
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
    parser.add_argument("--low-score-threshold", type=float, default=0.40,
                        help="Outlier threshold (top score below = outlier)")
    parser.add_argument("--shuffle", action="store_true",
                        help="Process pensioners in random order")
    parser.add_argument("--start-from", type=int, default=0,
                        help="Skip the first N pensioners in the list")
    parser.add_argument("--no-fag", action="store_true",
                        help="Skip FaG search (CGR-only mode, for testing)")
    parser.add_argument("--heartbeat-every", type=int, default=50,
                        help="Heartbeat every N pensioners (default 50)")
    parser.add_argument("--no-rss-watchdog", action="store_true",
                        help="Disable the RSS watchdog (default: enabled)")
    parser.add_argument("--rss-warn-mb", type=int, default=2048,
                        help="RSS warn threshold in MB (default 2048; 0 to disable)")
    parser.add_argument("--rss-force-reset-mb", type=int, default=4096,
                        help="Force browser-reset threshold in MB "
                             "(default 4096; 0 to disable)")
    parser.add_argument("--rss-exit-mb", type=int, default=6144,
                        help="Hard-exit threshold in MB "
                             "(default 6144; 0 to disable)")
    parser.add_argument("--max-consecutive-errors", type=int, default=10,
                        help="Stop the run after this many in-a-row "
                             "FaG errors (default 10; 0 to disable)")
    parser.add_argument("--reset-browser-every", type=int, default=250,
                        help="Periodically reopen the browser every N "
                             "records to bound Chromium RSS growth "
                             "(default 250; 500 was the old default "
                             "before the memory leak investigation)")
    parser.add_argument("--fag-state-filter", type=str, default=None,
                        help="FaG locationId scope. A US state abbr "
                             "('OK', 'TX'), 'US' for country_4, or '' "
                             "to disable. When --config is used, the "
                             "config's fag_state_filter is the default "
                             "(currently 'OK'). Override here to "
                             "broaden (e.g. '' for global) or scope to "
                             "another state.")
    args = parser.parse_args(argv)

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
        if args.low_score_threshold == 0.40:  # default sentinel
            args.low_score_threshold = batch_cfg.low_score_threshold
        if args.fag_state_filter is None:
            args.fag_state_filter = batch_cfg.fag_state_filter
        # start_row / end_row → start_from + limit
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

    # Optional RSS watchdog (independent of Playwright; safe to skip)
    watchdog = None
    if not args.no_rss_watchdog:
        from scripts.fag.rss_watchdog import RSSWatchdog
        watchdog = RSSWatchdog(
            poll_seconds=30.0,
            warn_mb=args.rss_warn_mb,
            force_reset_mb=args.rss_force_reset_mb,
            exit_mb=args.rss_exit_mb,
        )
        watchdog.start()

    # Build FaG search function (or None)
    fag_search_fn = None
    if not args.no_fag:
        # Inline-import to avoid loading Playwright when not needed
        from scripts.fag.fag_browser import make_fag_search_fn
        log.info("Initializing Playwright (visible browser, takes ~10s)...")
        # FaG locationId scope: from --fag-state-filter CLI flag,
        # or from batch_cfg.fag_state_filter if a config was loaded.
        # Default "OK" scopes to Oklahoma per the project goal
        # (AGENTS.md "find Confederate soldiers associated with
        # Oklahoma").
        fag_state_filter = getattr(args, "fag_state_filter", "OK")
        if fag_state_filter == "":
            fag_state_filter = None  # let search_one_pensioner default
        fag_search_fn = make_fag_search_fn(
            throttle=args.throttle,
            reset_browser_every=args.reset_browser_every,
            watchdog=watchdog,
            max_consecutive_errors=args.max_consecutive_errors,
            state_filter=fag_state_filter,
        )
        log.info("Playwright ready.")

    # Run batch
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        throttle_seconds=args.throttle,
        low_score_threshold=args.low_score_threshold,
        max_cgr_candidates=20,
        limit=args.limit,
        fag_search_fn=fag_search_fn,
        write_heartbeat_every=args.heartbeat_every,
        # J5-S2: per-run Results filename + view.html source.
        # Default results.jsonl; CLI/config can override.
        results_filename=getattr(args, "results_filename", "results.jsonl"),
        view_html_source=getattr(args, "view_html_source", Path("scripts/view.html")),
        # J6: pensioncard pages sidecar (view.html embeds IIIF images).
        pensioncard_pages_path=getattr(args, "pensioncard_pages", None),
        # J7: CGR path for post-run dedup.
        cgr_path=Path(args.cgr) if args.cgr else None,
    )

    try:
        result = run_batch(
            pensioners=pensioners,
            cemeteries=cems,
            config=cfg,
            log=log,
            # J5-S3: pass config path so resume.sh gets written
            config_path_for_resume=args.config,
        )
        log.info("Run finished: %s", json.dumps(result.to_dict(), indent=2))
        return 0
    except KeyboardInterrupt:
        log.warning("Interrupted by user. State has been flushed.")
        # J5-S3: still write resume.sh on interrupt so the user can pick
        # up from the same point. ResumeTracker skips already-done.
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


if __name__ == "__main__":
    raise SystemExit(cli_main())