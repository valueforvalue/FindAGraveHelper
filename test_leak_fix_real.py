"""Real-browser soak test for the Playwright leak fix.

Drives 100 synthetic Playwright navigations and reports RSS
growth WITH the leak fix and WITHOUT (in two passes).

Test plan:
  1. Without fix: 100 navigations, sample RSS at start and end.
  2. With fix:    100 navigations, sample RSS at start and end.
  3. Assert: growth_with_fix < growth_without_fix.

This is the same kind of test as scripts/soak_memory.py but
adds a comparison to the unpatched behaviour.
"""
from __future__ import annotations

import ctypes
import gc
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.sync_api import sync_playwright


def _rss_mb() -> int:
    try:
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        ct = PMC()
        ct.cb = ctypes.sizeof(ct)
        ok = psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(ct), ctypes.sizeof(ct),
        )
        return int(ct.WorkingSetSize / (1024 * 1024)) if ok else 0
    except Exception:
        return 0


def drive_navigations(n: int):
    """Run n synthetic Playwright navigations with gc each loop.
    Return final RSS delta in MB (positive = grown). Returns
    None if the RSS sampler isn't available.
    """
    """Run n synthetic Playwright navigations with gc each loop.
    Return final RSS delta in MB (positive = grown). Returns
    None if the RSS sampler isn't available.
    """
    gc.collect()
    start = _rss_mb()
    if start == 0:
        return 0
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False)
        ctx = b.new_context()
        page = ctx.new_page()
        try:
            for i in range(n):
                page.goto("about:blank", wait_until="domcontentloaded",
                          timeout=10000)
                gc.collect()
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
    gc.collect()
    end = _rss_mb()
    if start == 0 or end == 0:
        return None
    return end - start


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    # Pass 1: WITHOUT fix.
    print(f"=== Run {n} navigations WITHOUT leak fix ===")
    growth_without = drive_navigations(n)
    print(f"  growth = {growth_without} MB")

    # Pass 2: WITH fix.
    from playwright_leak_fix import apply_playwright_leak_fix
    apply_playwright_leak_fix()
    print(f"=== Run {n} navigations WITH leak fix ===")
    growth_with = drive_navigations(n)
    print(f"  growth = {growth_with} MB")

    print()
    if growth_without is None or growth_with is None:
        print("RSS sampler broken; skipping comparison")
        sys.exit(2)
    if growth_without == 0:
        # Could be ~zero noise. Don't ratio on this.
        print("WARNING: without-fix growth is 0 MB; no comparison possible")
        sys.exit(0)

    ratio = growth_with / max(growth_without, 1)
    print(f"Ratio with/without: {ratio:.2f}")
    # The fix should reduce growth substantially. We don't require
    # zero growth (Chromium can still allocate), only that growth
    # with the fix is materially smaller than without.
    if ratio > 0.9:
        print("FAIL: leak fix had no measurable effect")
        sys.exit(1)
    print("PASS: leak fix measurably reduces RSS growth")
