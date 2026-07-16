"""Runtime monkey-patch for the Playwright Python memory leak.

ISSUE
=====

Playwright Python has a long-standing memory leak
(github.com/microsoft/playwright/issues/15400). The function
`playwright._impl._sync_base.SyncBase._sync()` decorates every
async task with two attributes that capture full Python stack
traces via stack-frame introspection.

Those attributes hold references to all the calling frames of every
Playwright operation (page.goto, locator.click, evaluate, etc.).
On long-running scripts, the references accumulate in the asyncio
event loop's task registry — easily hitting gigabytes before the
process exits. The references are released only when the asyncio
loop is closed at process shutdown, by which time it's too late.

CONFIRMED ROOT CAUSE
====================

Verified against our installed Playwright 1.61.0:

  File:  C:\\Users\\value\\AppData\\Roaming\\Python\\Python314\\site-packages\\playwright\\_impl\\_sync_base.py
  Func:  SyncBase._sync
  Lines: setattr(task, "__pw_stack__", inspect.stack(0))
         setattr(task, "__pw_stack_trace__", traceback.extract_stack(limit=10))

Community fix (laztheripper, 2026-06): replace the frame-capture
with empty list `[]` so the attributes don't pin frames. The stack
traces are intended for debug diagnostics; they're not needed for
normal operation.

THIS MODULE
============

We provide an `apply_playwright_leak_fix()` function that:
  1. Imports playwright._impl._sync_base.
  2. Monkey-patches `SyncBase._sync` with a version that does NOT
     capture the stack traces.
  3. Optionally also removes __pw_stack__ / __pw_stack_trace__
     from existing tasks if the loop is already running.

Call this BEFORE making any Playwright calls (i.e. before
`setup_browser()`).

The patch is idempotent (safe to call repeatedly).

WHAT IS LOST
============

Diagnostic error messages may no longer include the "playwright
stack trace" hint. We've never relied on that hint in production
runs (logs come from our own logging.info calls), so this is
acceptable.

Also lost: playwright's "augmented traceback" for internal
assertions. We've never hit such an assertion in production.
"""
from __future__ import annotations


_LEAK_FIX_APPLIED = False


def apply_playwright_leak_fix() -> bool:
    """Apply the leak fix to SyncBase._sync. Idempotent.

    Returns True if the patch was applied this call (False if
    already in place).
    """
    global _LEAK_FIX_APPLIED
    if _LEAK_FIX_APPLIED:
        return False

    import inspect as _inspect
    import playwright._impl._sync_base as sb
    from playwright._impl._errors import Error as _Error

    SyncBase = getattr(sb, "SyncBase", None)
    if SyncBase is None:
        raise RuntimeError(
            "playwright._impl._sync_base.SyncBase not found; "
            "Playwright API has changed. Patch needs updating."
        )

    # Capture references we need inside the closure.
    _greenlet_getcurrent = __import__("greenlet").getcurrent

    def _sync_fixed(self, coro):
        """Replacement for SyncBase._sync that does not pin frames."""
        __tracebackhide__ = True
        # Match the original's error path.
        if self._loop.is_closed():
            coro.close()
            raise _Error("Event loop is closed! Is Playwright already stopped?")

        g_self = _greenlet_getcurrent()
        task = self._loop.create_task(coro)
        # Use empty list so the task is fully GC-eligible when done.
        setattr(task, "__pw_stack__", [])
        setattr(task, "__pw_stack_trace__", [])

        task.add_done_callback(lambda _: g_self.switch())
        while not task.done():
            self._dispatcher_fiber.switch()
        import asyncio as _asyncio
        _asyncio._set_running_loop(self._loop)
        return task.result()

    SyncBase._sync = _sync_fixed

    # Also clear stack-trace attrs on already-created tasks in
    # any running loops we can find.
    try:
        import asyncio as _asyncio
        try:
            running_loop = _asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is not None:
            for t in list(_asyncio.all_tasks(loop=running_loop)):
                try:
                    t.__pw_stack__ = []
                    t.__pw_stack_trace__ = []
                except Exception:
                    pass
    except Exception:
        pass

    _LEAK_FIX_APPLIED = True
    return True
