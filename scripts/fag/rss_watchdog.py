"""RSS watchdog for long-running Playwright + Chromium jobs.

Measures Python process RSS PLUS all child process RSS (Chromium,
pwsh, etc.) using Win32 Toolhelp32 on Windows or /proc on Linux.
Reports the aggregate tree RSS so thresholds reflect the total
OS-visible working set, not just the Python process alone.

The original 7,758-record FaG run hit pwsh.exe at ~7 GB after a few
hours. Chromium RSS climbs per navigation as the JS heap and DOM
references accumulate; pwsh stays attached to the spawned Chromium
processes, so the OS-visible working set is the **sum** of
Chromium + pwsh + Python refs. Without intervention, Chromium
eventually dies — at which point Playwright surfaces
"Target page, context or browser has been closed" on every
subsequent call (cascading 100% errors in state.jsonl).

This module provides a small background thread that polls the
process-tree RSS via the Win32 API (so we don't depend on psutil,
which may not be installed in minimal envs). It exposes:

  - `RSSWatchdog(poll_seconds, warn_mb, force_reset_mb, exit_mb)`:
    background thread.
  - Three thresholds (none required):
      * warn_mb: log WARNING if RSS exceeds this.
      * force_reset_mb: set force_reset_event so the runner can
        trigger a fresh browser context at the next opportunity.
      * exit_mb: hard-exit the process (os._exit) so we don't
        write junk records after a wedged pwsh.
  - `should_force_reset()`: polled by the runner each record.
  - `current_rss_mb()`: snapshot of total tree RSS (also logged at
    each tick).

Usage:

  from scripts.fag.rss_watchdog import RSSWatchdog
  wd = RSSWatchdog(poll_seconds=30, warn_mb=2048,
                   force_reset_mb=4096, exit_mb=6144)
  wd.start()
  try:
      ... long runner here ...
  finally:
      wd.stop()

The watchdog is best-effort: if the Win32 call fails for any
reason, we fall back to a sentinel that always reports a low RSS
(nothing to do) — i.e. the watchdog becomes a no-op.
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
from typing import Optional

log = logging.getLogger("rss_watchdog")


# ============================================================
# Win32 binding for GetProcessMemoryInfo (avoids psutil dependency)
# ============================================================
_PMC = None  # populated lazily by _get_rss_bytes()
_kernel32 = None
_psapi = None


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
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


def _ensure_binding():
    """Set up the ctypes binding for GetProcessMemoryInfo once."""
    global _kernel32, _psapi
    if _kernel32 is not None and _psapi is not None:
        return True
    try:
        _kernel32 = ctypes.windll.kernel32
        _psapi = ctypes.windll.psapi
        _psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        _psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        return True
    except Exception as e:
        log.debug("Win32 binding failed: %s", e)
        return False


def _get_rss_bytes() -> Optional[int]:
    """Return this process's RSS (working set size) in bytes, or None."""
    if not _ensure_binding():
        return None
    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    h = _kernel32.GetCurrentProcess()
    ok = _psapi.GetProcessMemoryInfo(
        h, ctypes.byref(counters), ctypes.sizeof(counters)
    )
    if not ok:
        return None
    return int(counters.WorkingSetSize)


def _get_process_rss(process_handle: int) -> int:
    """Return RSS (WorkingSetSize) for a given process handle, or 0."""
    if not _ensure_binding():
        return 0
    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    ok = _psapi.GetProcessMemoryInfo(
        process_handle, ctypes.byref(counters), ctypes.sizeof(counters)
    )
    if not ok:
        return 0
    return int(counters.WorkingSetSize)


def _get_tree_rss_bytes() -> tuple[int, int]:
    """Return (python_rss, total_tree_rss) in bytes.

    Python RSS + sum of all child process RSS. On Windows, enumerates
    child PIDs via Toolhelp32 snapshot. On Linux, reads /proc/<pid>/statm.
    """
    python_rss = _get_rss_bytes() or 0

    if os.name == "nt":
        child_rss = _get_child_rss_windows()
    else:
        child_rss = _get_child_rss_linux()

    return python_rss, python_rss + child_rss


def _get_child_rss_windows() -> int:
    """Sum RSS of all child processes on Windows."""
    import ctypes.wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    current_pid = os.getpid()

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_char * 260),
        ]

    try:
        snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPPROCESS, 0
        )
        if snapshot == INVALID_HANDLE_VALUE:
            return 0

        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

        child_rss = 0
        if ctypes.windll.kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                if entry.th32ParentProcessID == current_pid:
                    try:
                        h = ctypes.windll.kernel32.OpenProcess(
                            0x0400 | 0x0010,  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
                            False,
                            entry.th32ProcessID,
                        )
                        if h:
                            child_rss += _get_process_rss(h)
                            ctypes.windll.kernel32.CloseHandle(h)
                    except Exception:
                        pass
                if not ctypes.windll.kernel32.Process32Next(
                    snapshot, ctypes.byref(entry)
                ):
                    break

        ctypes.windll.kernel32.CloseHandle(snapshot)
        return child_rss
    except Exception:
        return 0


def _get_child_rss_linux() -> int:
    """Sum RSS of all child processes on Linux via /proc."""
    import glob

    current_pid = os.getpid()
    child_rss = 0

    try:
        for stat_path in glob.glob(f"/proc/[0-9]*/stat"):
            try:
                pid_dir = stat_path.rsplit("/", 1)[0]
                pid = int(pid_dir.split("/")[-1])
            except (ValueError, IndexError):
                continue

            # Check parent PID from /proc/<pid>/stat
            try:
                with open(stat_path) as f:
                    stat = f.read().split()
                    ppid = int(stat[3]) if len(stat) > 3 else 0
            except Exception:
                continue

            if ppid == current_pid:
                # Read RSS from /proc/<pid>/statm (field 1 = resident pages)
                statm_path = f"/proc/{pid}/statm"
                try:
                    with open(statm_path) as f:
                        pages = int(f.read().split()[1])
                        child_rss += pages * 4096  # page size
                except Exception:
                    pass
    except Exception:
        pass

    return child_rss


# ============================================================
# Watchdog
# ============================================================
class RSSWatchdog:
    """Background thread that polls RSS and signals runner on overflow.

    Args:
        poll_seconds: how often to check (default 30)
        warn_mb: log warning at this RSS (default 2048)
        force_reset_mb: set force_reset_event at this RSS (default 4096)
        exit_mb: hard exit at this RSS (default 6144); 0 disables

    All thresholds can be 0 to disable the corresponding action.
    """
    def __init__(
        self,
        poll_seconds: float = 30.0,
        warn_mb: int = 2048,
        force_reset_mb: int = 4096,
        exit_mb: int = 6144,
    ):
        self.poll_seconds = poll_seconds
        self.warn_mb = warn_mb
        self.force_reset_mb = force_reset_mb
        self.exit_mb = exit_mb
        self._force_reset_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_rss_mb: int = 0
        self._warned_once = False

    # ---- thread control ----
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="rss-watchdog", daemon=True
        )
        self._thread.start()
        log.info(
            "RSS watchdog started (poll=%.1fs, warn>%dMB, "
            "force_reset>%dMB, exit>%dMB)",
            self.poll_seconds, self.warn_mb,
            self.force_reset_mb, self.exit_mb,
        )

    def stop(self) -> None:
        self._stop_event.set()

    # ---- runner-facing API ----
    def should_force_reset(self) -> bool:
        return self._force_reset_event.is_set()

    def clear_force_reset(self) -> None:
        self._force_reset_event.clear()

    def current_rss_mb(self) -> int:
        """Latest polled RSS (or 0 if never polled yet)."""
        return self._last_rss_mb

    # ---- internals ----
    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_seconds):
            python_rss, total_rss = _get_tree_rss_bytes()
            if python_rss == 0 and total_rss == 0:
                continue
            self._last_rss_mb = total_rss // (1024 * 1024)

            if self.force_reset_mb and self._last_rss_mb >= self.force_reset_mb:
                if not self.should_force_reset():
                    log.warning(
                        "RSS %d MB (python=%d MB) >= force_reset threshold "
                        "(%d MB). Signaling runner to reopen browser.",
                        self._last_rss_mb,
                        python_rss // (1024 * 1024),
                        self.force_reset_mb,
                    )
                self._force_reset_event.set()
            if (
                self.warn_mb
                and self._last_rss_mb >= self.warn_mb
                and not self._warned_once
            ):
                log.warning("RSS %d MB >= warn threshold (%d MB)",
                            self._last_rss_mb, self.warn_mb)
                self._warned_once = True
            if self.exit_mb and self._last_rss_mb >= self.exit_mb:
                log.error(
                    "RSS %d MB >= exit threshold (%d MB). "
                    "Calling os._exit(1) to avoid writing junk records.",
                    self._last_rss_mb, self.exit_mb,
                )
                # Brief sleep so any flush can complete (best-effort).
                import time as _time
                _time.sleep(0.5)
                os._exit(1)


def make_default_watchdog() -> Optional[RSSWatchdog]:
    """Start a default watchdog with conservative thresholds.

    Returns None if RSSWatchdog.start failed for some reason (e.g.
    not on Windows).
    """
    wd = RSSWatchdog(
        poll_seconds=30.0,
        warn_mb=2048,
        force_reset_mb=4096,
        exit_mb=6144,
    )
    try:
        wd.start()
        return wd
    except Exception as e:
        log.debug("Default watchdog start failed: %s", e)
        return None
