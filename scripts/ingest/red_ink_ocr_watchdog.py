"""Watchdog that auto-restarts the OCR script when it dies.

The OCR script (red_ink_ocr_pilot.py) has been dying silently
during this session without leaving any error trace. Its resume
support means we can safely restart it; it picks up where it
left off via the existing results JSON.

This watchdog:
1. Polls every 30 seconds for the OCR process.
2. If dead, restarts it immediately.
3. Logs every restart to a separate watchdog log.
4. Exits after N restarts OR when OCR completes (no new
   results for IDLE_CYCLES consecutive checks).

Usage:
    python scripts/ingest/red_ink_ocr_watchdog.py
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
ROOT = _SCRIPTS_DIR.parent.parent

OCR_SCRIPT = _SCRIPTS_DIR / "red_ink_ocr_pilot.py"
DEFAULT_RESULTS = Path("data/cards/red_ocr_results.json")
DEFAULT_LOG = Path("data/cards/ocr.log")
DEFAULT_WATCHDOG_LOG = Path("data/cards/ocr_watchdog.log")
DEFAULT_OUT_DIR = Path("data/cards/img")
DEFAULT_INPUT_JSON = Path(
    "docs/research/digitalprairie/ok_pensioners.json"
)

POLL_INTERVAL = 30  # seconds
IDLE_CYCLES = 10    # exit after this many checks with no new results


def count_results(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return 0


def is_ocr_alive() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist.exe", "//FI", "IMAGENAME eq python.exe"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="ignore")
    except Exception:
        return False
    # Look for python processes with substantial memory (the OCR
    # process holds 100-200MB; the bash wrapper is 16MB).
    for line in out.splitlines():
        if "python.exe" in line.lower():
            parts = line.split()
            if len(parts) >= 5:
                try:
                    mem_kb = int(parts[4].replace(",", ""))
                    if mem_kb > 50_000:  # >50MB
                        return True
                except (ValueError, IndexError):
                    pass
    return False


def start_ocr(log: logging.Logger) -> subprocess.Popen:
    cmd = [
        sys.executable, "-u", str(OCR_SCRIPT),
        "--in-dir", str(DEFAULT_OUT_DIR),
        "--input-json", str(DEFAULT_INPUT_JSON),
        "--out", str(DEFAULT_RESULTS),
        "--summary", str("data/cards/red_ocr_summary.json"),
    ]
    log.info("starting OCR: %s", " ".join(cmd))
    f = open(DEFAULT_LOG, "a", encoding="utf-8")
    return subprocess.Popen(
        cmd, stdout=f, stderr=subprocess.STDOUT,
        cwd=str(ROOT),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-restarts", type=int, default=50)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        filename=DEFAULT_WATCHDOG_LOG,
        filemode="a",
    )
    log = logging.getLogger("watchdog")
    # Also log to stdout so it's visible during interactive runs.
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(sh)

    log.info("watchdog started; pid=%d", __import__("os").getpid())
    proc = None
    idle = 0
    restarts = 0
    last_count = count_results(DEFAULT_RESULTS)
    log.info("starting state: %d results in JSON", last_count)

    while True:
        if proc is None or proc.poll() is not None:
            restarts += 1
            log.warning("OCR not running; restart %d/%d",
                        restarts, args.max_restarts)
            if restarts > args.max_restarts:
                log.error("max restarts exceeded; giving up")
                return 1
            proc = start_ocr(log)
            time.sleep(5)  # let it warm up

        time.sleep(POLL_INTERVAL)
        now_count = count_results(DEFAULT_RESULTS)
        delta = now_count - last_count
        log.info("poll: results=%d (+%d), idle=%d/%d",
                 now_count, delta, idle, IDLE_CYCLES)
        last_count = now_count
        if delta == 0:
            idle += 1
            if idle >= IDLE_CYCLES:
                log.info("idle threshold reached; OCR appears done. exiting")
                if proc and proc.poll() is None:
                    proc.terminate()
                return 0
        else:
            idle = 0


if __name__ == "__main__":
    raise SystemExit(main())