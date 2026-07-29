"""Zip the pension-card viewer + raw data into one portable archive.

Bundles everything needed to back up the red-ink OCR pipeline's
output on Google Drive / external HDD:

- ``data/cards/img/``               — 4.8 GB of pension card JPEGs
- ``data/cards/viewer/``            — 17 MB of HTML + JSON viewer
- ``data/cards/enrichment_report.json``
- ``data/cards/red_ocr_results.json``
- ``data/cards/red_ocr_summary.json``
- ``docs/research/digitalprairie/ok_pensioners.json``
  (source-of-truth, UNTOUCHED — preserved so the bundle is
  self-contained for re-running the enrichment if needed)
- ``docs/research/digitalprairie/ok_pensioners.with_death_dates.json``
  (the enrichment sidecar)
- ``data/cards/download_summary.json`` (download metadata)

Excludes ``data/cards/img_sampled_50/`` because it's a subset of
``img/`` (already included). Excludes per-run logs (.log files)
because they're transient.

Crash safety:
- Writes to ``<out>.partial`` first; only renames to ``<out>`` on
  successful close. A previous crash leaves a ``.partial`` file
  behind; running again picks up where it left off.
- ``--split N`` writes multiple zips of ~N MB each instead of
  one giant zip (each part is independently extractable via
  ``unzip`` on the corresponding file). Use this if your upload
  tool has a single-file size limit.

Usage:
    python scripts/ingest/distribute_pension_viewer.py
    python scripts/ingest/distribute_pension_viewer.py --out /path/to/hdd/bundle.zip
    python scripts/ingest/distribute_pension_viewer.py --split 1024
    python scripts/ingest/distribute_pension_viewer.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import zipfile
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
ROOT = _SCRIPTS_DIR.parent.parent

# (source path relative to repo root) for everything in the bundle
INCLUDE_PATHS = [
    "data/cards/img/",
    "data/cards/viewer/",
    "data/cards/enrichment_report.json",
    "data/cards/red_ocr_results.json",
    "data/cards/red_ocr_summary.json",
    "data/cards/download_summary.json",
    "docs/research/digitalprairie/ok_pensioners.json",
    "docs/research/digitalprairie/ok_pensioners.with_death_dates.json",
]

# Top-level dir inside the zip so extraction yields a self-contained
# folder rather than dumping files at the zip root.
ARCHIVE_TOP = "pension-viewer-bundle"

DEFAULT_OUT = Path("data/pension-viewer-bundle.zip")


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def iter_files(root: Path):
    """Yield (abs_path, arcname) for everything that should be in
    the archive, excluding log files and the pilot subset.
    """
    for rel in INCLUDE_PATHS:
        src = root / rel
        if not src.exists():
            logging.warning("missing: %s (skipping)", rel)
            continue
        if src.is_file():
            yield src, f"{ARCHIVE_TOP}/{rel}"
            continue
        # Directory: walk it
        for p in src.rglob("*"):
            if p.is_file():
                arc = f"{ARCHIVE_TOP}/{p.relative_to(root).as_posix()}"
                yield p, arc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="output zip path (without .partN suffix)")
    ap.add_argument("--split", type=int, default=0,
                    help="split into multiple zips of ~N MB each "
                         "(e.g. --split 1024 for ~1GB parts). 0 = single zip.")
    ap.add_argument("--dry-run", action="store_true",
                    help="list files + total size, don't write zip")
    ap.add_argument("--exclude-logs", action="store_true",
                    help="also exclude *.log files (default: included? no, excluded)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("distribute")

    root = ROOT.resolve()

    # First pass: list & size
    files = list(iter_files(root))
    total_bytes = sum(p.stat().st_size for p, _ in files)
    log.info("found %d files, %s total",
             len(files), human_bytes(total_bytes))

    if args.dry_run:
        log.info("dry-run: would write %s -> %s",
                 human_bytes(total_bytes), args.out)
        # Show the first 20 + last 5 for a quick sanity check
        for p, arc in files[:20]:
            log.info("  %s (%s)", arc, human_bytes(p.stat().st_size))
        if len(files) > 25:
            log.info("  ... (%d more) ...", len(files) - 25)
            for p, arc in files[-5:]:
                log.info("  %s (%s)", arc, human_bytes(p.stat().st_size))
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    total_files = len(files)
    # Plan the splits if --split was given
    if args.split and args.split > 0:
        # Approximate split: aim for ~split MB per part by raw bytes
        # (the zip will be slightly smaller due to compression).
        target_bytes = args.split * 1024 * 1024
        splits = []  # list of (path, file_list)
        cur_files = []
        cur_bytes = 0
        for src, arc in files:
            sz = src.stat().st_size
            if cur_bytes > 0 and cur_bytes + sz > target_bytes:
                splits.append(cur_files)
                cur_files = []
                cur_bytes = 0
            cur_files.append((src, arc))
            cur_bytes += sz
        if cur_files:
            splits.append(cur_files)
        log.info("splitting into %d parts of ~%d MB",
                 len(splits), args.split)
        # Derive per-part paths
        stem = args.out
        # If --out has a .zip suffix, strip it for the stem
        if stem.suffix.lower() == ".zip":
            stem = stem.with_suffix("")
        part_paths = []
        for i, part_files in enumerate(splits, 1):
            part_paths.append(stem.parent / f"{stem.name}.part{i:03d}.zip")
        log.info("parts will be named: %s, %s, ... (%d total)",
                 part_paths[0].name, part_paths[1].name, len(part_paths))
    else:
        splits = [files]
        part_paths = [args.out]

    overall_written = 0
    overall_bytes = 0
    last_log = started

    for part_idx, (part_files, part_path) in enumerate(zip(splits, part_paths), 1):
        partial = part_path.with_suffix(part_path.suffix + ".partial")
        # Resume: if .partial exists, find which arcnames it has
        # already written and skip them.
        existing_arcs = set()
        if partial.exists():
            try:
                with zipfile.ZipFile(partial, "r") as zf:
                    existing_arcs = {n for n in zf.namelist()}
                log.info("[part %d/%d] resuming from %s (%d entries already)",
                         part_idx, len(splits), partial.name, len(existing_arcs))
            except zipfile.BadZipFile:
                log.warning("[part %d/%d] %s is corrupt, deleting and restarting",
                            part_idx, len(splits), partial.name)
                partial.unlink()

        log.info("[part %d/%d] writing %s -> %s",
                 part_idx, len(splits),
                 human_bytes(sum(p.stat().st_size for p, _ in part_files)),
                 part_path)
        with zipfile.ZipFile(partial, "a" if partial.exists() else "w",
                             compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for src, arc in part_files:
                if arc in existing_arcs:
                    continue
                zf.write(src, arc)
                overall_written += 1
                overall_bytes += src.stat().st_size
                now = time.time()
                if now - last_log > 30:
                    pct = overall_written / total_files * 100
                    log.info("  overall: %d/%d files (%.1f%%) ...",
                             overall_written, total_files, pct)
                    last_log = now
        # Atomic rename: .partial -> final
        partial.rename(part_path)
        log.info("[part %d/%d] done -> %s (%s)",
                 part_idx, len(splits),
                 part_path.name,
                 human_bytes(part_path.stat().st_size))

    elapsed = time.time() - started
    log.info("ALL DONE: %d files in %d part(s), %.1fs",
             overall_written, len(splits), elapsed)
    log.info("total raw: %s", human_bytes(overall_bytes))
    for p in part_paths:
        log.info("  %s (%s)", p.name, human_bytes(p.stat().st_size))
    if len(part_paths) == 1:
        log.info("extract anywhere, then open pension-viewer-bundle/"
                 "data/cards/viewer/index.html in a browser")
    else:
        log.info("extract all %d parts into the SAME directory — "
                 "they form one logical bundle", len(part_paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())