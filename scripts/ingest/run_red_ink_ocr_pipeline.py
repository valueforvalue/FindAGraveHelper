"""End-to-end runner for the red-ink OCR death-date pipeline.

Executes the three stages in sequence:

1. **Download**: ``download_pensioncard_images.py`` — fetches all
   pension card IIIF tiles from Digital Prairie to
   ``data/cards/img/``. Resumable (skips already-downloaded).
2. **OCR**: ``red_ink_ocr_pilot.py`` — masks red ink, runs
   Tesseract, parses death dates. Outputs per-image JSON.
3. **Enrich**: ``enrich_pensioners_with_death_dates.py`` — dedupes
   per pensioncard_id, writes ``death_year`` + ``death_date_iso``
   onto each pensioner record in ``ok_pensioners.json``.

Each stage is independently invokable. This runner just chains
them and prints progress. By default all three run; pass
``--stage`` to run just one.

Usage:
    python scripts/ingest/run_red_ink_ocr_pipeline.py
    python scripts/ingest/run_red_ink_ocr_pipeline.py --stage ocr
    python scripts/ingest/run_red_ink_ocr_pipeline.py --throttle 0.5
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DOWNLOAD_SCRIPT = _SCRIPTS_DIR / "download_pensioncard_images.py"
OCR_SCRIPT = _SCRIPTS_DIR / "red_ink_ocr_pilot.py"
ENRICH_SCRIPT = _SCRIPTS_DIR / "enrich_pensioners_with_death_dates.py"

STAGES = ("download", "ocr", "enrich")


def run_stage(stage: str, args: argparse.Namespace, log: logging.Logger) -> int:
    log.info("=== stage: %s ===", stage)
    if stage == "download":
        cmd = [
            sys.executable, str(DOWNLOAD_SCRIPT),
            "--input", str(args.input),
            "--out", str(args.img_dir),
            "--throttle", str(args.throttle),
        ]
    elif stage == "ocr":
        cmd = [
            sys.executable, str(OCR_SCRIPT),
            "--in-dir", str(args.img_dir),
            "--input-json", str(args.input),
            "--out", str(args.ocr_results),
            "--summary", str(args.ocr_summary),
        ]
    elif stage == "enrich":
        cmd = [
            sys.executable, str(ENRICH_SCRIPT),
            "--input", str(args.input),
            "--ocr", str(args.ocr_results),
            "--out", str(args.enriched_json),
            "--report", str(args.enrichment_report),
        ]
    else:
        log.error("unknown stage: %s", stage)
        return 2
    if args.dry_run:
        log.info("dry-run: would exec %s", " ".join(cmd))
        return 0
    log.info("exec: %s", " ".join(cmd))
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=STAGES + ("all",), default="all")
    ap.add_argument("--input", type=Path,
                    default=Path("docs/research/digitalprairie/ok_pensioners.json"))
    ap.add_argument("--img-dir", type=Path, default=Path("data/cards/img"))
    ap.add_argument("--ocr-results", type=Path,
                    default=Path("data/cards/red_ocr_results.json"))
    ap.add_argument("--ocr-summary", type=Path,
                    default=Path("data/cards/red_ocr_summary.json"))
    ap.add_argument("--enriched-json", type=Path,
                    default=Path("docs/research/digitalprairie/ok_pensioners.with_death_dates.json"))
    ap.add_argument("--enrichment-report", type=Path,
                    default=Path("data/cards/enrichment_report.json"))
    ap.add_argument("--throttle", type=float, default=1.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stop-on-error", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("red_ink_ocr")

    stages = STAGES if args.stage == "all" else (args.stage,)
    for stage in stages:
        rc = run_stage(stage, args, log)
        if rc != 0:
            log.error("stage %s failed rc=%d", stage, rc)
            if args.stop_on_error:
                return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())