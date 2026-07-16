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
    throttle_seconds: float = 2.5
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
        "backlink": result.pensioner.get("backlink", ""),
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
) -> BatchResult:
    """Run the unified pipeline on a batch of pensioners.

    For each pensioner:
      - Skip if already in state file (resume)
      - Run CGR + FaG
      - Write state.jsonl line
      - Write outliers.jsonl line if outlier

    At end: writes report.md + report.json.

    Args:
        pensioners: list of pensioner dicts
        cemeteries: list of cemetery records for CGR blocking index
        config: UnifiedRunnerConfig with fag_search_fn injected
        log: optional logger
    """
    if log is None:
        log = logging.getLogger("run_unified")

    if config.out_dir is None:
        raise ValueError("UnifiedRunnerConfig.out_dir must be set")
    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.jsonl"
    outliers_path = out_dir / "outliers.jsonl"

    # Resume support
    tracker = ResumeTracker(state_path)
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
            record = result_to_dict(pipeline_result)
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
        from scripts.rss_watchdog import RSSWatchdog
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
        from scripts.fag_browser import make_fag_search_fn
        log.info("Initializing Playwright (visible browser, takes ~10s)...")
        fag_search_fn = make_fag_search_fn(
            throttle=args.throttle,
            reset_browser_every=args.reset_browser_every,
            watchdog=watchdog,
            max_consecutive_errors=args.max_consecutive_errors,
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
    )

    try:
        result = run_batch(
            pensioners=pensioners,
            cemeteries=cems,
            config=cfg,
            log=log,
        )
        log.info("Run finished: %s", json.dumps(result.to_dict(), indent=2))
        return 0
    except KeyboardInterrupt:
        log.warning("Interrupted by user. State has been flushed; restart to resume.")
        return 130


if __name__ == "__main__":
    raise SystemExit(cli_main())