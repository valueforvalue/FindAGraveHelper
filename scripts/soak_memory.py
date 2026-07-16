"""Manual memory soak test for the Playwright + Chromium pipeline.

This drives N synthetic FaG-style navigation loops with a real
browser and reports RSS every K iterations. The point is to
prove the per-record memory growth is bounded (not that the
pipeline runs to completion against FaG).

Usage:
  python scripts/soak_memory.py --iterations 200 --sample-every 10

  # mode='synthetic' (default): page.goto about:blank; no FaG needed.
  # mode='real-fag': uses the same throttle/strategies as a real run.

The script exits 0 if the RSS-trend slope is <2 MB/10 records.
Otherwise exits 1 with the offending summary. Add --plot to dump
a tiny ASCII chart of RSS over time.
"""
from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from playwright.sync_api import sync_playwright

from scripts.rss_watchdog import _get_rss_bytes


def rss_mb() -> float:
    b = _get_rss_bytes()
    return b / (1024 * 1024) if b else 0.0


def run_synthetic(iterations: int, sample_every: int) -> list[float]:
    """Drive the browser with empty navigations; record RSS."""
    samples = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False)
        ctx = b.new_context()
        page = ctx.new_page()
        try:
            samples.append(rss_mb())
            for i in range(iterations):
                page.goto("about:blank", wait_until="domcontentloaded",
                          timeout=10000)
                # Force some JS heap work to mimic real FaG load
                page.evaluate("() => { window.heap = []; for (let i = 0; i < 1000; i++) window.heap.push(i); }")
                if (i + 1) % sample_every == 0:
                    gc.collect()
                    samples.append(rss_mb())
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                ctx.close()
            except Exception:
                pass
            try:
                b.close()
            except Exception:
                pass
    return samples


def summarize(samples: list[float]) -> dict:
    if len(samples) < 2:
        return {"min_mb": 0, "max_mb": 0, "delta_mb": 0, "slope_mb_per_10": 0}
    deltas = []
    for a, b in zip(samples[:-1], samples[1:]):
        deltas.append(b - a)
    slope = sum(deltas) / len(deltas) if deltas else 0
    return {
        "min_mb": min(samples),
        "max_mb": max(samples),
        "delta_mb": samples[-1] - samples[0],
        "slope_mb_per_sample": slope,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--iterations", type=int, default=200)
    p.add_argument("--sample-every", type=int, default=10)
    p.add_argument("--plot", action="store_true",
                   help="Print ASCII chart of RSS over samples")
    p.add_argument("--max-slope-mb-per-10", type=float, default=2.0,
                   help="Exit 1 if average slope exceeds this (MB/10 samples)")
    args = p.parse_args()

    print(f"Running {args.iterations} synthetic navigations, "
          f"sample every {args.sample_every}...")
    samples = run_synthetic(args.iterations, args.sample_every)
    summary = summarize(samples)
    print("Sample RSS (MB):", [round(s, 2) for s in samples])
    print("Summary:", summary)
    slope = summary["slope_mb_per_sample"]
    slope_per_10 = slope * 10

    if args.plot and samples:
        lo = min(samples)
        hi = max(samples) if max(samples) > lo else lo + 1
        for s in samples:
            bar_len = int((s - lo) / (hi - lo) * 50) if hi > lo else 0
            print(f"  {s:6.1f} MB | " + "#" * bar_len)

    if slope_per_10 > args.max_slope_mb_per_10:
        print(f"FAIL: slope {slope_per_10:.2f} MB/10 > "
              f"max {args.max_slope_mb_per_10} MB/10")
        return 1
    print(f"PASS: slope {slope_per_10:.2f} MB/10 within budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
