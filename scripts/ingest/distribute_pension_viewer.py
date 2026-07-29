"""Zip the pension-card viewer + raw data into one portable archive.

Bundles everything needed to back up the red-ink OCR pipeline's
output on Google Drive / external HDD:

- ``data/cards/img/``               — ~4.8 GB of pension card JPEGs
- ``data/cards/viewer/``            — ~17 MB of HTML + JSON viewer
                                       (one ``{letter}.html`` per
                                       surname initial)
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
- ``--by-letter`` writes one zip per surname letter (A, B, C…).
  Each ``pension-viewer-bundle.{LETTER}.zip`` contains only the
  images for that letter + the matching ``{letter}.html``/
  ``{letter}.json`` page. The reviewer can grab a single letter
  (one ~50–500 MB zip) and have a fully working viewer + all
  the images for that letter. ``pension-viewer-bundle.index.zip``
  is also emitted — it contains the full viewer (every
  ``{letter}.html``, ``index.html``, ``all.json``) and NO images,
  so the reviewer can browse letters from the index page before
  pulling the specific image zips they need.

Usage:
    python scripts/ingest/distribute_pension_viewer.py
    python scripts/ingest/distribute_pension_viewer.py --out /path/to/hdd/bundle.zip
    python scripts/ingest/distribute_pension_viewer.py --split 1024
    python scripts/ingest/distribute_pension_viewer.py --by-letter
    python scripts/ingest/distribute_pension_viewer.py --by-letter --letters A,B,C
    python scripts/ingest/distribute_pension_viewer.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import zipfile
from collections import defaultdict
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

# Files in the bundle that are NOT letter-specific (shared by every
# letter-zip and the slim index-zip). These go in every output so a
# single letter-zip + viewer is self-contained.
SHARED_METADATA_GLOBS = [
    "data/cards/enrichment_report.json",
    "data/cards/red_ocr_results.json",
    "data/cards/red_ocr_summary.json",
    "data/cards/download_summary.json",
    "docs/research/digitalprairie/ok_pensioners.json",
    "docs/research/digitalprairie/ok_pensioners.with_death_dates.json",
]

# Filenames inside data/cards/viewer/ that should ship in every
# letter-zip (so each letter-zip works standalone, the reviewer
# doesn't need the index zip to view a single letter).
INDEX_SHARED_VIEWER_FILES = [
    "index.html",
    "all.json",
]

# Pattern: {pensioncard_id}__{page_id}.jpg
JPG_PCID_RE = re.compile(r"(\d+)__(\d+)\.jpg$")


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


# ----------------------------------------------------------------
# --by-letter support
# ----------------------------------------------------------------

def load_pcid_to_letter(root: Path,
                        log: logging.Logger) -> dict[int, str]:
    """Build pcid -> letter from the viewer's all.json master.

    Falls back to '?' for pcids that aren't in the master (which
    means no enriched record + no image — they wouldn't be in a
    letter slice anyway).
    """
    master = root / "data" / "cards" / "viewer" / "all.json"
    if not master.exists():
        log.warning("no viewer/all.json at %s; "
                    "letter slices will use '?' for every pcid", master)
        return {}
    data = json.loads(master.read_text(encoding="utf-8"))
    by_pcid = data.get("by_pensioncard_id", {})
    out: dict[int, str] = {}
    for pcid_str, rec in by_pcid.items():
        letter = (rec.get("letter") or "?").upper()
        if not letter or not letter[0].isalpha():
            letter = "?"
        else:
            letter = letter[0]
        out[int(pcid_str)] = letter
    log.info("loaded letter mapping for %d pensioncard_ids", len(out))
    return out


def safe_letter_filename(letter: str) -> str:
    """Match build_pensioncard_viewer.py: '?' -> '_' on disk."""
    return letter if letter.isalnum() else "_"


def collect_files_for_letter(
    root: Path,
    letter: str,
    pcid_to_letter: dict[int, str],
) -> list[tuple[Path, str]]:
    """For a single letter, yield (abs_path, arcname) for:

    - the matching viewer html+json
    - all jpgs whose pcid maps to that letter
    - the shared metadata files
    - the shared viewer index files (index.html, all.json)

    Skips anything that doesn't exist on disk (with a warning).
    """
    safe = safe_letter_filename(letter)
    out: list[tuple[Path, str]] = []

    # 1) Letter-specific html + json
    for name in (f"{safe}.html", f"{safe}.json"):
        src = root / "data" / "cards" / "viewer" / name
        if src.exists():
            rel = f"data/cards/viewer/{name}"
            out.append((src, f"{ARCHIVE_TOP}/{rel}"))
        else:
            logging.warning("[%s] missing letter page: %s", letter, rel)

    # 2) Images whose pcid -> this letter
    img_dir = root / "data" / "cards" / "img"
    if img_dir.exists():
        for p in img_dir.glob("*.jpg"):
            m = JPG_PCID_RE.match(p.name)
            if not m:
                continue
            pcid = int(m.group(1))
            if pcid_to_letter.get(pcid, "?") == letter:
                rel = f"data/cards/img/{p.name}"
                out.append((p, f"{ARCHIVE_TOP}/{rel}"))
    else:
        logging.warning("[%s] img dir missing: %s", letter, img_dir)

    # 3) Shared metadata
    for rel in SHARED_METADATA_GLOBS:
        src = root / rel
        if src.exists():
            out.append((src, f"{ARCHIVE_TOP}/{rel}"))
        else:
            logging.warning("[%s] missing metadata: %s", letter, rel)

    # 4) Shared viewer index files (index.html + all.json) so the
    # letter-zip is browseable on its own without the index zip.
    for name in INDEX_SHARED_VIEWER_FILES:
        src = root / "data" / "cards" / "viewer" / name
        if src.exists():
            rel = f"data/cards/viewer/{name}"
            out.append((src, f"{ARCHIVE_TOP}/{rel}"))

    return out


def collect_index_files(root: Path) -> list[tuple[Path, str]]:
    """Slim 'index' zip: full viewer (every {letter}.html + index.html
    + all.json) + metadata, NO images."""
    out: list[tuple[Path, str]] = []
    vdir = root / "data" / "cards" / "viewer"
    if vdir.exists():
        for p in vdir.rglob("*"):
            if p.is_file():
                rel = f"data/cards/viewer/{p.relative_to(vdir).as_posix()}"
                out.append((p, f"{ARCHIVE_TOP}/{rel}"))
    for rel in SHARED_METADATA_GLOBS:
        src = root / rel
        if src.exists():
            out.append((src, f"{ARCHIVE_TOP}/{rel}"))
    return out


def write_letter_zip(
    out_path: Path,
    files: list[tuple[Path, str]],
    log: logging.Logger,
) -> int:
    """Write a single zip with crash-safe .partial rename. Returns
    the uncompressed bytes-sum of files written (skips ones that
    were already in a resumed .partial)."""
    partial = out_path.with_suffix(out_path.suffix + ".partial")
    raw_bytes = 0
    existing_arcs: set[str] = set()
    if partial.exists():
        try:
            with zipfile.ZipFile(partial, "r") as zf:
                existing_arcs = {n for n in zf.namelist()}
            log.info("resuming %s from %d entries",
                     out_path.name, len(existing_arcs))
        except zipfile.BadZipFile:
            log.warning("%s corrupt, restarting", partial.name)
            partial.unlink()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(partial,
                         "a" if partial.exists() else "w",
                         compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for src, arc in files:
            if arc in existing_arcs:
                continue
            zf.write(src, arc)
            raw_bytes += src.stat().st_size
    partial.rename(out_path)
    return raw_bytes


# ----------------------------------------------------------------
# CLI
# ----------------------------------------------------------------

def run_by_letter(args, root: Path, log: logging.Logger) -> int:
    """Emit one zip per surname letter + a slim index zip.

    Discover letters from the viewer's all.json master. Each letter
    is its own zip (~50 MB to ~500 MB raw on this corpus). Always
    emit a pension-viewer-bundle.index.zip containing the full
    viewer + metadata but NO images, so a reviewer can browse
    letters from the index page before deciding which image-zips
    to pull.
    """
    pcid_to_letter = load_pcid_to_letter(root, log)
    if not pcid_to_letter:
        log.error("no letter mapping available; aborting")
        return 2

    # Determine which letters to emit
    if args.letters:
        wanted = {L.strip().upper()
                  for L in args.letters.split(",") if L.strip()}
    else:
        wanted = None  # discover from disk below

    # Discover which letters actually have jpgs on disk
    img_dir = root / "data" / "cards" / "img"
    pcids_by_letter: dict[str, set[int]] = defaultdict(set)
    if img_dir.exists():
        for p in img_dir.glob("*.jpg"):
            m = JPG_PCID_RE.match(p.name)
            if not m:
                continue
            pcid = int(m.group(1))
            letter = pcid_to_letter.get(pcid, "?")
            if letter != "?":
                pcids_by_letter[letter].add(pcid)
    present_letters = sorted(pcids_by_letter.keys())
    if wanted is None:
        wanted = set(present_letters)
    else:
        unknown = wanted - set(present_letters)
        if unknown:
            log.info("ignoring --letters entries with no images: %s",
                     sorted(unknown))

    log.info("letters to emit: %s", sorted(wanted))

    # Filter wanted down to letters that actually exist on disk, so
    # --letters A,QQ doesn't try to collect for QQ (would warn +
    # write an empty zip).
    wanted = {L for L in wanted if L in pcids_by_letter}
    if not wanted:
        log.error("--letters filter matched no letters with images on disk; aborting")
        return 2
    log.info("letters with images on disk: %s", sorted(wanted))

    if args.dry_run:
        log.info("dry-run: would write %d letter-zips", len(wanted))
        for letter in sorted(wanted):
            files = collect_files_for_letter(root, letter, pcid_to_letter)
            total = sum(p.stat().st_size for p, _ in files)
            log.info("  %s.zip: %d files, %s raw",
                     letter, len(files), human_bytes(total))
        idx_files = collect_index_files(root)
        idx_bytes = sum(p.stat().st_size for p, _ in idx_files)
        log.info("  index.zip: %d files, %s raw",
                 len(idx_files), human_bytes(idx_bytes))
        return 0

    stem = args.out
    if stem.suffix.lower() == ".zip":
        stem = stem.with_suffix("")

    started = time.time()
    written: list[tuple[Path, int]] = []

    for letter in sorted(wanted):
        files = collect_files_for_letter(root, letter, pcid_to_letter)
        if not files:
            log.warning("[%s] no files collected, skipping", letter)
            continue
        out_path = stem.parent / f"{stem.name}.{letter}.zip"
        raw = write_letter_zip(out_path, files, log)
        written.append((out_path, raw))
        log.info("[%s] done -> %s (%d files, %s raw)",
                 letter, out_path.name, len(files),
                 human_bytes(raw))

    # Always emit the index zip last (it's quick + small)
    idx_files = collect_index_files(root)
    if idx_files:
        idx_path = stem.parent / f"{stem.name}.index.zip"
        idx_raw = write_letter_zip(idx_path, idx_files, log)
        written.append((idx_path, idx_raw))
        log.info("index done -> %s (%d files, %s raw)",
                 idx_path.name, len(idx_files), human_bytes(idx_raw))

    elapsed = time.time() - started
    n_letters = len(written) - (1 if idx_files else 0)
    log.info("BY-LETTER DONE: %d letter-zips + 1 index zip in %.1fs",
             n_letters, elapsed)
    for p, raw in written:
        log.info("  %s (%s raw, %s on disk)",
                 p.name, human_bytes(raw),
                 human_bytes(p.stat().st_size))
    log.info("open pension-viewer-bundle.index/data/cards/viewer/index.html "
             "in a browser to browse letters, or open any "
             "pension-viewer-bundle.{LETTER}/data/cards/viewer/{LETTER}.html "
             "directly.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="output zip path (without .partN suffix)")
    ap.add_argument("--split", type=int, default=0,
                    help="split into multiple zips of ~N MB each "
                         "(e.g. --split 1024 for ~1GB parts). 0 = single zip.")
    ap.add_argument("--by-letter", action="store_true",
                    help="emit one zip per surname letter "
                         "(pension-viewer-bundle.A.zip, .B.zip, ...) "
                         "plus pension-viewer-bundle.index.zip (full "
                         "viewer without images). --split is ignored.")
    ap.add_argument("--letters", type=str, default="",
                    help="comma-separated subset of letters to emit in "
                         "--by-letter mode (default: every letter that "
                         "has any images on disk).")
    ap.add_argument("--dry-run", action="store_true",
                    help="list files + total size, don't write zip")
    ap.add_argument("--exclude-logs", action="store_true",
                    help="also exclude *.log files (default: included? no, excluded)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("distribute")

    root = ROOT.resolve()

    # --by-letter: dispatch to the per-letter slicer.
    if args.by_letter:
        return run_by_letter(args, root, log)

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