"""Real-FaG memory diagnostic — measures steady-state RSS growth.

The previous version measured growth over 5 records from cold start;
Chromium startup alone allocates ~70 MB before any pensioner is
processed, which contaminated the measurement. This version:

  - Runs 5 warmup pensioners first (excluded from RSS measurement).
  - Then runs 10 measurement pensioners.
  - Asserts growth over the 10 measurement steps is bounded.

With all the v2 fixes (state_names hoist, Stealth to context,
locator disposal, body text replacement, ElementHandle dispose,
gc.collect, CGR index reuse, reset_every=250), the per-record
steady-state growth should be in the low-MB range, not the 7+ MB
per record observed before this round.
"""
from __future__ import annotations

import ctypes
import gc
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _rss_mb():
    """Total RSS for THIS process (Win32 binding)."""
    try:
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
            ctypes.byref(ct), ctypes.sizeof(ct),
        )
        return ct.WorkingSetSize / (1024 * 1024) if ok else 0.0
    except Exception:
        return 0.0


WARMUP_PENSIONERS = [
    {"id": -1, "first_name": "John", "middle_name": "", "last_name": "Doe",
     "application_number": "W", "regiment": "1st Texas Infantry",
     "company": "A", "birth_year": "1840", "death_year": "1920",
     "pensioncard_backlink": ""},
    {"id": -2, "first_name": "Jane", "middle_name": "", "last_name": "Doe",
     "application_number": "W", "regiment": "2nd Mississippi Infantry",
     "company": "B", "birth_year": "1845", "death_year": "1925",
     "pensioncard_backlink": ""},
    {"id": -3, "first_name": "Bob", "middle_name": "", "last_name": "Smith",
     "application_number": "W", "regiment": "3rd Texas Cavalry",
     "company": "C", "birth_year": "1850", "death_year": "1930",
     "pensioncard_backlink": ""},
    {"id": -4, "first_name": "Alice", "middle_name": "", "last_name": "Johnson",
     "application_number": "W", "regiment": "5th Tennessee Infantry",
     "company": "D", "birth_year": "1835", "death_year": "1915",
     "pensioncard_backlink": ""},
    {"id": -5, "first_name": "Tom", "middle_name": "", "last_name": "Williams",
     "application_number": "W", "regiment": "10th Alabama Infantry",
     "company": "E", "birth_year": "1840", "death_year": "1920",
     "pensioncard_backlink": ""},
]


def _p(i):
    return {
        "id": i, "first_name": f"First{i}", "middle_name": "",
        "last_name": f"Last{i}",
        "application_number": str(i),
        "regiment": "1st Texas Infantry",
        "company": "A", "birth_year": "1840", "death_year": "1920",
        "pensioncard_backlink": "",
    }


MEASUREMENT_PENSIONERS = [_p(i) for i in range(10)]


@pytest.fixture(scope="module")
def fag_search_fn():
    from scripts.fag_browser import make_fag_search_fn
    # Use small reset_browser_every for tests so the periodic reset
    # path is exercised — but the test is mostly about per-call growth.
    fn = make_fag_search_fn(throttle=0.2, reset_browser_every=4)
    yield fn


def test_steady_state_rss_growth_per_record(fag_search_fn):
    """Drive warmup pensioners, then 10 measurement pensioners.
    Assert average per-record RSS growth is bounded.
    """
    if _rss_mb() == 0:
        pytest.skip("RSS sampler not available")

    cfg = type("Cfg", (), {"throttle_seconds": 0.2})()

    # Warmup: allocate any one-time setup costs
    for p in WARMUP_PENSIONERS:
        try:
            fag_search_fn(p, cfg)
        except Exception:
            pass
    gc.collect()
    base_mb = _rss_mb()

    # Measurement: 10 records. RSS growth here is the per-call cost
    # after warmup; cold-start effects are excluded.
    for p in MEASUREMENT_PENSIONERS:
        try:
            fag_search_fn(p, cfg)
        except Exception as e:
            print(f"pensioner {p['id']} failed: {e}")
        gc.collect()

    end_mb = _rss_mb()
    growth = end_mb - base_mb
    per_record = growth / len(MEASUREMENT_PENSIONERS)
    # Per-record target after all fixes: <3 MB. With Chromium
    # cold-start effects excluded by warmup, this isolates Python-side
    # growth. Allow 5 MB as the upper bound; this will be tightened
    # as more fixes land.
    assert per_record < 5.0, (
        f"Per-record RSS growth {per_record:.2f} MB exceeds 5 MB limit. "
        f"Total growth: {growth:.2f} MB over {len(MEASUREMENT_PENSIONERS)} "
        f"records. base={base_mb:.1f} end={end_mb:.1f}."
    )
