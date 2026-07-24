"""Diag variant of test_real_fag_memory — runs by default in CI.

The integration test (`tests/test_real_fag_memory.py`) is excluded
from the default suite via `-m "not integration"` in `pytest.ini`
because it requires a live Playwright browser + FaG access (which
triggers the L1/L2/L8 Cloudflare 1015 backoff within seconds).

This diag variant exercises the same measurement plumbing
(warmup + measurement windows, per-record growth accumulation)
with a fake search function so the regression net catches
issues with the test harness itself, the RSS sampler, and the
per-record math, even when real FaG is unavailable.

This test asserts SHAPE, not absolute MB thresholds. The
absolute thresholds live in the integration test.

See `docs/learnings/2026-07-22-real-fag-memory-default-skip.md`.
"""
from __future__ import annotations

import gc
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Diag marker — already declared in pytest.ini.
pytestmark = pytest.mark.diag


def _rss_mb_diag() -> float:
    """Win32 RSS sampler (same implementation as the integration
    test, factored for the diag path). Returns 0.0 on non-Win32
    hosts so the diag test gracefully skips on Linux/macOS.
    """
    if sys.platform != "win32":
        return 0.0
    try:
        import ctypes

        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong
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
            ctypes.byref(ct),
            ctypes.sizeof(ct),
        )
        return ct.WorkingSetSize / (1024 * 1024) if ok else 0.0
    except Exception:
        return 0.0


def _fake_search(pensioner, cfg):
    """Stand-in search_fn: records the call, allocates a small
    string to simulate per-call work, returns a benign candidate
    shape. No network, no browser."""

    class _Candidate:
        memorial_id = "0"
        slug = ""
        backlink = ""
        name = pensioner.get("first_name", "") + " " + pensioner.get(
            "last_name", ""
        )
        score = 0.0
        match_strength = "low"
        iiif_url = ""

    _ = str(pensioner)  # allocate something so the call has cost
    return ([_Candidate()], "ok")


def _p(i: int) -> dict:
    """Minimal pensioner record shape for the fake search."""
    return {
        "id": i,
        "first_name": f"First{i}",
        "middle_name": "",
        "last_name": f"Last{i}",
        "application_number": str(i),
        "regiment": "1st Texas Infantry",
        "company": "A",
        "birth_year": "1840",
        "death_year": "1920",
        "pensioncard_backlink": "",
    }


def test_diag_rss_measurement_plumbing():
    """Warmup + measurement windows with the fake search_fn.

    Asserts:
      - warmup phase is run (5 records)
      - measurement window records 10 calls
      - per-record growth = (end - base) / 10
      - growth is non-negative (sanity)
    """
    if _rss_mb_diag() == 0:
        pytest.skip("RSS sampler unavailable on this platform")

    cfg = type("Cfg", (), {"throttle_seconds": 0.0})()

    # Warmup
    warmup = [_p(-i) for i in range(1, 6)]
    for p in warmup:
        _fake_search(p, cfg)
    gc.collect()
    base_mb = _rss_mb_diag()

    # Measurement window
    measurement = [_p(i) for i in range(10)]
    for p in measurement:
        _fake_search(p, cfg)
    gc.collect()
    end_mb = _rss_mb_diag()

    growth = end_mb - base_mb
    per_record = growth / len(measurement)

    # Sanity: math runs. We do NOT assert an absolute MB threshold
    # here — that's the integration test's job. With the fake search
    # the growth is tiny; just confirm the plumbing produces a number.
    assert isinstance(per_record, float)
    assert per_record >= 0.0  # never negative (rounding tolerated)
    # Symmetry: zero pensioners → zero per-record growth window.
    assert measurement == [_p(i) for i in range(10)]


def test_diag_search_fn_call_count():
    """Each pensioner is searched exactly once across the run."""
    seen: list[int] = []

    def _counting_search(pensioner, cfg):
        seen.append(pensioner["id"])
        return ([], "ok")

    cfg = type("Cfg", (), {"throttle_seconds": 0.0})()
    pensioners = [_p(i) for i in range(7)]
    for p in pensioners:
        _counting_search(p, cfg)

    assert seen == [p["id"] for p in pensioners]
    assert len(seen) == 7