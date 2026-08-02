#!/usr/bin/env bash
# Build a clean Tier-2 copy of the repo for shipping to a thumb drive.
#
# What goes in:
#   - Full git history + working tree (excluding gitignored runtime noise)
#   - .git/                               (full git dir - history, refs,
#                                         remote tracking, hooks, packed
#                                         objects; ~13 MB; ships so the
#                                         target is a true clone)
#   - data/cards/img/                    (4.8 GB - pension card JPEGs)
#   - data/cards/applications/           (2.1 GB - application form JPEGs)
#   - data/cards/red_ocr_results.json    (12 MB - OCR output)
#   - data/cards/download_summary_applications.json + red_ocr_summary.json
#                                         (audit metadata)
#   - data/cards/enrichment_report.json   (death-date enrichment sidecar)
#   - dixiedata.db                        (3.2 MB - tracked)
#   - docs/research/digitalprairie/ok_pensioners.json + .with_death_dates.json
#   - docs/research/cgr/                  (public CGR fixture)
#   - All tracked research artifacts under docs/
#   - The intentionally-tracked run_2026_07_24_g10_stealth_swap_verification/
#
# What gets EXCLUDED (regenerable):
#   - data/cards/viewer/                  (6.7 GB - rebuild via
#                                         scripts/ingest/build_pensioncard_viewer.py
#                                         on the target machine in ~1 min)
#   - data/cards/img_sampled_50/          (47 MB - smoke test sample only)
#   - data/results/run_50_test_smoke/     (1.6 MB - local smoke run output)
#   - output/                             (J5+ run outputs - regenerable)
#   - __pycache__/, *.pyc                 (regenerated on first import)
#   - data/*.log, runtime .pid files      (transient)
#   - docs/research/local-data/local_*.csv (private hand-curated data;
#                                          the operator copies those
#                                          separately if needed)
#   - docs/research/broadened-set/rosters/ (large raw rosters; reproducible)
#
# Total Tier-2 size: ~7 GB
#
# Usage:
#   bash scripts/copy_to_thumbdrive.sh /path/to/thumbdrive/faghelper-copy
#
# After the copy, on the target machine:
#   cd /path/to/thumbdrive/faghelper-copy
#   python scripts/ingest/build_pensioncard_viewer.py
#   pytest tests/

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <destination-path>" >&2
    echo "       e.g. $0 /mnt/usb/faghelper-copy" >&2
    exit 1
fi

DEST="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -d "$ROOT/.git" ]]; then
    echo "error: $ROOT is not a git repo" >&2
    exit 1
fi

echo "Source: $ROOT"
echo "Destination: $DEST"

if [[ -e "$DEST" ]]; then
    echo "error: $DEST already exists; remove it first or pick a new path" >&2
    exit 1
fi

echo "--- sanity check: no modified tracked files ---"
if ! git -C "$ROOT" diff --quiet HEAD 2>/dev/null; then
    echo "WARNING: tracked files have uncommitted changes."
    echo "Run 'git status' to review; aborting to avoid an inconsistent copy."
    exit 1
fi

# Note: untracked files (e.g. a newly-written but not-yet-committed
# copy script) are NOT a problem - they're just skipped by
# checkout-index, which only copies tracked files. We surface a
# one-line list so the operator notices.
untracked=$(git -C "$ROOT" ls-files --others --exclude-standard 2>/dev/null)
if [[ -n "$untracked" ]]; then
    echo "    (note: these untracked files are NOT copied;"
        echo "     re-run after committing if you want them in the bundle:)"
    echo "$untracked" | sed 's/^/      /'
fi

echo "--- sanity check: HEAD is pushed to origin/master ---"
LOCAL_SHA=$(git -C "$ROOT" rev-parse HEAD)
REMOTE_SHA=$(git -C "$ROOT" rev-parse origin/master 2>/dev/null || echo "")
if [[ -z "$REMOTE_SHA" ]]; then
    echo "error: no origin/master remote configured; cannot verify push" >&2
    exit 1
fi
if [[ "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
    echo "error: local HEAD ($LOCAL_SHA) != origin/master ($REMOTE_SHA)" >&2
    echo "       Push first: git push origin master" >&2
    exit 1
fi
echo "HEAD $LOCAL_SHA matches origin/master."

echo "--- creating destination ---"
mkdir -p "$DEST"

echo "--- copy .git/ (history, refs, hooks, packed objects, ~13 MB) ---"
# checkout-index deliberately skips .git; ship the real git dir so
# the target is a true working clone (git status/log/diff all work
# out of the box, no `git init` + re-push needed).
# cp -a preserves permissions, timestamps, symlinks, and keeps the
# single pack file intact (faster than 3500+ loose objects).
cp -a "$ROOT/.git" "$DEST/.git"

echo "--- copy tracked files + tracked runtime exceptions ---"
echo "    (this includes code, tests, docs, tracked research," 
echo "     dixiedata.db, and run_2026_07_24_g10_stealth_swap_verification/)"
git -C "$ROOT" checkout-index -a -f --prefix="$DEST/"

# .git/ was already copied above as a single tree.

echo "--- copy data/cards/img/ (pension cards, ~4.8 GB) ---"
if [[ -d "$ROOT/data/cards/img" ]]; then
    cp -r "$ROOT/data/cards/img" "$DEST/data/cards/img"
else
    echo "    WARNING: data/cards/img/ missing; target will need to"
    echo "    re-download via scripts/ingest/download_pensioncard_images.py"
fi

echo "--- copy data/cards/applications/ (application forms, ~2.1 GB) ---"
if [[ -d "$ROOT/data/cards/applications" ]]; then
    cp -r "$ROOT/data/cards/applications" "$DEST/data/cards/applications"
else
    echo "    WARNING: data/cards/applications/ missing; target will need to"
    echo "    re-download via scripts/ingest/download_application_images.py"
fi

echo "--- copy data/cards/red_ocr_results.json (OCR output, 12 MB) ---"
if [[ -f "$ROOT/data/cards/red_ocr_results.json" ]]; then
    cp "$ROOT/data/cards/red_ocr_results.json" "$DEST/data/cards/red_ocr_results.json"
else
    echo "    WARNING: red_ocr_results.json missing; target will need to"
    echo "    re-OCR (~19h on this corpus) or run red_ink_ocr_pilot.py"
fi

echo "--- copy committed CGR fixture ---"
if [[ -d "$ROOT/docs/research/cgr" ]]; then
    cp -r "$ROOT/docs/research/cgr" "$DEST/docs/research/cgr"
fi

echo "--- summary ---"
du -sh "$DEST" 2>&1
echo
du -sh "$DEST"/data/cards/* 2>&1 | sort -rh | head -n 6
echo
echo "Done. Next steps on the target machine:"
echo "  cd $DEST"
echo "  python scripts/ingest/build_pensioncard_viewer.py    # ~1 min, 6.7 GB"
echo "  pytest tests/                                        # ~30 sec, should be ~1,381 passed"