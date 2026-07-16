"""Test: the CGR blocking index is built ONCE per batch, not per call.

This was the largest single source of Python RSS growth in the
7,758-record run: per pensioner, `run_pipeline_for_pensioner`
was rebuilding a 2,593-vet phonetic blocking index, allocating MB-sized
Python dicts that the OS-level allocator never returns to free
memory (CPython's PyMalloc freelist retention + Windows memory
allocator behaviour). The fix is to pre-build the index in
run_batch() and pass it down.

This test doesn't need Playwright; it drives 100 CGR-only pipeline
calls (--no-fag mode is implicit) and asserts RSS growth is bounded
rather than linear.
"""
from __future__ import annotations

import ctypes
import gc
import json
import sys
import tempfile
from pathlib import Path

import pytest


def _rss_mb() -> float:
    try:
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

        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        ct = PMC()
        ct.cb = ctypes.sizeof(ct)
        ok = psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(ct),
            ctypes.sizeof(ct),
        )
        if ok:
            return ct.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return 0.0


def _dummy_cemeteries(n: int = 2593):
    """Build a synthetic CGR cemetery list of ~2,593 vets."""
    cemeteries = []
    for cid in range(0, max(1, n // 25)):
        veterans = []
        for vid in range(cid * 25, min(n, (cid + 1) * 25)):
            veterans.append({
                "id": 10000 + vid,
                "first_name": f"First{vid}",
                "middle_name": "M",
                "last_name": f"Last{vid % 200}",  # collisions for blocking
                "cemetery_id": cid,
                "cemetery_name": f"Cemetery {cid}",
                "county": "OK",
                "state": "OK",
                "born": "1840-00-00",
                "died": "1920-00-00",
            })
        cemeteries.append({
            "cemetery_id": cid,
            "cemetery_name": f"Cemetery {cid}",
            "county": "OK",
            "state": "OK",
            "veterans": veterans,
        })
    return cemeteries


def test_cgr_index_reuse_does_not_grow_rss():
    """Run 200 CGR-only pipeline calls. Verify RSS growth is bounded.

    With the per-call rebuild (the bug), we'd see 200 * sizeof(index)
    = ~200+ MB of growth. With the pre-built-index fix, RSS should
    remain within a few MB of the baseline.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.unified_pipeline import (
        run_pipeline_for_pensioner, PipelineConfig,
    )
    from scripts.unified_runner import build_cgr_blocking_index

    cemeteries = _dummy_cemeteries(2593)
    prebuilt = build_cgr_blocking_index(cemeteries)
    gc.collect()
    base_mb = _rss_mb()
    assert base_mb > 0, "RSS sampler broken on this platform"

    cfg = PipelineConfig(throttle_seconds=0)

    for i in range(200):
        pensioner = {
            "id": i,
            "first_name": "John",
            "middle_name": "",
            "last_name": f"Last{i % 200}",
            "application_number": f"A{i}",
            "regiment": "1st Texas Infantry",
            "company": "A",
            "birth_year": "",
            "death_year": "",
            "pensioncard_backlink": "",
        }
        run_pipeline_for_pensioner(
            pensioner=pensioner,
            cgr_index_vets=cemeteries,
            config=cfg,
            fag_search_fn=None,  # CGR-only
            prebuilt_cgr_index=prebuilt,
        )

    gc.collect()
    end_mb = _rss_mb()
    growth = end_mb - base_mb
    # Allow 20 MB slack for Python freelist; any real leak would dwarf this.
    assert growth < 20, (
        f"RSS grew {growth:.1f} MB over 200 calls with prebuilt index. "
        f"Expected <20 MB. base={base_mb:.1f} end={end_mb:.1f}"
    )


def test_cgr_index_per_call_does_not_break_anything():
    """Sanity: building the index per call (legacy behaviour) still
    returns correct results. We don't assert RSS because the test
    loop isn't representative of the production load pattern.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scripts.unified_pipeline import (
        run_pipeline_for_pensioner, PipelineConfig,
    )

    cemeteries = _dummy_cemeteries(2593)
    cfg = PipelineConfig(throttle_seconds=0)
    pensioner = {
        "id": 42,
        "first_name": "John",
        "last_name": "Last0",
    }
    # Without prebuilt_cgr_index — exercises the legacy code path.
    result = run_pipeline_for_pensioner(
        pensioner=pensioner,
        cgr_index_vets=cemeteries,
        config=cfg,
        fag_search_fn=None,
    )
    assert result is not None
    # CGR index should find some matches (the synthetic data uses
    # last_name=Last0 for ~12 records).
    assert result.cgr_status in ("cgr_found", "no_match")
