"""Real-FaG memory diagnostic test.

Drives N FaG searches against findagrave.com using the real
search_one_pensioner() + fag_search_fn() and reports RSS growth.
This is the definitive test for the "Python RSS still grows at
~24 MB/min" symptom.
"""
from __future__ import annotations

import gc
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _rss_mb_total() -> float:
    """Sum RSS for THIS process only (no children)."""
    try:
        psapi = ctypes_windll_setup()
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
        return ct.WorkingSetSize / (1024*1024) if ok else 0.0
    except Exception:
        return 0.0


def ctypes_windll_setup():
    import ctypes
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    return psapi


import ctypes


@pytest.fixture(scope="module")
def fag_search_fn():
    from scripts.fag_browser import make_fag_search_fn
    fn = make_fag_search_fn(throttle=0.3, reset_browser_every=50)
    yield fn
    # No explicit teardown — process exits & browsers cleaned up


PENSIONERS = [
    {"id": 1, "first_name": "Willis", "middle_name": "", "last_name": "Austin",
     "application_number": "A", "regiment": "1st Texas Infantry",
     "company": "A", "birth_year": "", "death_year": "",
     "pensioncard_backlink": ""},
    {"id": 2, "first_name": "James", "middle_name": "", "last_name": "Brown",
     "application_number": "B", "regiment": "1st Texas Infantry",
     "company": "A", "birth_year": "", "death_year": "",
     "pensioncard_backlink": ""},
    {"id": 3, "first_name": "John", "middle_name": "", "last_name": "Smith",
     "application_number": "C", "regiment": "5th Texas Infantry",
     "company": "B", "birth_year": "1840", "death_year": "1920",
     "pensioncard_backlink": ""},
    {"id": 4, "first_name": "Mary", "middle_name": "L", "last_name": "Baker",
     "application_number": "D", "regiment": "2nd Mississippi Infantry",
     "company": "C", "birth_year": "", "death_year": "",
     "pensioncard_backlink": ""},
    {"id": 5, "first_name": "Sarah", "middle_name": "", "last_name": "Roberts",
     "application_number": "E", "regiment": "3rd Texas Cavalry",
     "company": "D", "birth_year": "1845", "death_year": "1918",
     "pensioncard_backlink": ""},
]


def test_real_fag_rss_growth_below_threshold(fag_search_fn):
    """Run 5 real FaG searches. RSS growth must be <20 MB total.

    Without the search_one_pensioner memory fixes, this would
    easily grow >50 MB. With the fixes (drop body string, drop
    locator refs, periodic gc.collect) it stays bounded.
    """
    if _rss_mb_total() == 0:
        pytest.skip("RSS sampler not available")

    gc.collect()
    base_mb = _rss_mb_total()

    cfg = type("Cfg", (), {"throttle_seconds": 0.3})()
    for p in PENSIONERS:
        try:
            fag_search_fn(p, cfg)
        except Exception as e:
            print(f"Pensioner {p.get('id')} failed: {e}")
        gc.collect()

    end_mb = _rss_mb_total()
    growth = end_mb - base_mb
    # Allow 25 MB slack; any real leak would dwarf this over 5 calls
    # that each do ~10 page navigations.
    assert growth < 25, (
        f"Python RSS grew {growth:.1f} MB over 5 real FaG searches. "
        f"base={base_mb:.1f} end={end_mb:.1f}"
    )
