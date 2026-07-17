"""RSS watchdog for long-running Playwright + Chromium jobs.

The original 7,758-record FaG run hit pwsh.exe at ~7 GB after a few
hours. Chromium RSS climbs per navigation as the JS heap and DOM
references accumulate; pwsh stays attached to the spawned Chromium
processes, so the OS-visible working set is the **sum** of
Chromium + pwsh + Python refs. Without intervention, Chromium
eventually dies — at which point Playwright surfaces
"Target page, context or browser has been closed" on every
subsequent call (cascading 100% errors in state.jsonl).

This module provides a small background thread that polls the
process RSS via the Win32 `GetProcessMemoryInfo` API (so we don't
depend on psutil, which may not be installed in minimal envs).
It exposes:

  - `RSSWatchdog(poll_seconds, warn_mb, force_reset_mb, exit_mb)`:
    background thread.
  - Three thresholds (none required):
      * warn_mb: log WARNING if RSS exceeds this.
      * force_reset_mb: set force_reset_event so the runner can
        trigger a fresh browser context at the next opportunity.
      * exit_mb: hard-exit the process (os._exit) so we don't
        write junk records after a wedged pwsh.
  - `should_force_reset()`: polled by the runner each record.
  - `current_rss_mb()`: snapshot (also logged at each tick).

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
            rss = _get_rss_bytes()
            if rss is None:
                continue
            self._last_rss_mb = rss // (1024 * 1024)

            if self.force_reset_mb and self._last_rss_mb >= self.force_reset_mb:
                if not self.should_force_reset():
                    log.warning(
                        "RSS %d MB >= force_reset threshold (%d MB). "
                        "Signaling runner to reopen browser.",
                        self._last_rss_mb, self.force_reset_mb,
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
