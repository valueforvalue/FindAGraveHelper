"""Cross-platform RSS sampler for memory-growth tests.

Used by ``test_cgr_index_reuse`` (default CI suite) and the
``test_real_fag_memory*`` integration/diag suites. Returns the
current process RSS in MB, or 0.0 if no sampler path is available
on the host so callers can decide to skip vs. fail.

Order of preference:
    1. ``psutil.Process().memory_info().rss`` — identical semantics
       on every platform, already in ``requirements-ci.txt``.
    2. Linux ``/proc/self/statm`` + ``/proc/self/smaps_rollup``
       page-size fallback (works in stripped containers where
       psutil is missing).
    3. POSIX ``resource.getrusage`` (Linux: kB; macOS: bytes).
    4. Win32 ``psapi.GetProcessMemoryInfo`` via ctypes.
"""
from __future__ import annotations

import sys


def rss_mb() -> float:
    # 1) psutil
    try:
        import psutil  # type: ignore

        return float(psutil.Process().memory_info().rss) / (1024 * 1024)
    except Exception:
        pass

    # 2) Linux /proc
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/self/statm", "r") as fh:
                pages = int(fh.read().split()[1])
            page_size = rss_mb._page_size
            if page_size is None:
                page_size = 4096
                try:
                    with open("/proc/self/smaps_rollup", "r") as fh:
                        for line in fh:
                            if line.startswith("Rss:"):
                                kb = int(line.split()[1])
                                if pages > 0:
                                    page_size = (kb * 1024) // pages
                                break
                except Exception:
                    pass
                rss_mb._page_size = page_size
            return (pages * page_size) / (1024 * 1024)
    except Exception:
        pass

    # 3) POSIX rusage
    try:
        import resource  # type: ignore

        ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return ru / (1024 * 1024)
        return ru / 1024.0 / 1024.0
    except Exception:
        pass

    # 4) Win32 psapi
    try:
        if sys.platform == "win32":
            import ctypes

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


rss_mb._page_size = None  # type: ignore[attr-defined]
