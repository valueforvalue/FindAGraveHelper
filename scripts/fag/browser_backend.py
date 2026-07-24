"""Browser backend selection — issue #94 (stealth swap).

Selects the sync-Playwright-compatible stealth layer at runtime
via the `STEALTH_BACKEND` env var. Three options:

  - `patchright` (default) — sync Playwright drop-in (Vinyzu) with
    a binary-level fix for the Runtime.Enable leak that
    Cloudflare Turnstile checks. Pairs with `playwright-stealth`
    v2 (Mattwmaster58) for JS-level evasions. Per the
    competitive-audit recommendation (backlog item #2), this
    closes the only long-frozen dep in the stack
    (`playwright-stealth` AtuboDad, dormant Sep 2023).

  - `playwright_stealth` — legacy path. Today's behavior; keep
    as a back-compat option for operators who need it.

  - `playwright` — bare Playwright, no stealth. For local
    development + tests; do NOT use against FaG (Cloudflare
    1015 in seconds).

The default is `patchright`. Operators who want the old path
set `STEALTH_BACKEND=playwright_stealth` in their env.

`cf_verify()` is a documented no-op today. The follow-up PR
with real FaG access replaces it with a real challenge
re-fetch path (per the audit's recommendations #3).

Public API:
  - get_backend() -> BrowserBackend (reads STEALTH_BACKEND env)
  - cf_verify(url=None) -> bool
  - SUPPORTED_BACKENDS: list[str]
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger("browser_backend")


SUPPORTED_BACKENDS: list[str] = [
    "patchright",
    "playwright_stealth",
    "playwright",
]


@runtime_checkable
class BrowserBackend(Protocol):
    """A sync-Playwright-compatible browser backend with optional
    stealth.

    The factory in this module returns one of three concrete
    implementations; tests may pass a custom backend via the
    Protocol for unit testing without booting Chromium.
    """

    name: str
    description: str
    # Whether this backend layers playwright-stealth on top of
    # the underlying Playwright API.
    layer_stealth: bool
    # Whether the backend claims Cloudflare Turnstile bypass
    # (patchright does; others don't).
    cloudflare_bypass: bool

    def sync_playwright(self) -> Any:
        """Return a `sync_playwright()` context manager.

        For `patchright` and `playwright`, this is the patched or
        upstream Playwright API respectively. For
        `playwright_stealth`, the underlying API is upstream
        Playwright (the stealth is layered at context creation
        time, not at the API level).
        """
        ...


class _PatchrightBackend:
    """patchright — Vinyzu's binary-patched sync Playwright.

    Closes the Runtime.Enable leak Cloudflare Turnstile checks.
    Stealth is layered on top via `playwright-stealth` v2
    (Mattwmaster58) at context-creation time.
    """

    name: str = "patchright"
    description: str = (
        "Vinyzu's sync-Playwright drop-in with binary-level fix "
        "for the Cloudflare Turnstile Runtime.Enable check. "
        "Layers playwright-stealth v2 JS evasions on top."
    )
    layer_stealth: bool = True
    cloudflare_bypass: bool = True

    def sync_playwright(self) -> Any:
        # Lazy import: the test suite may not have patchright
        # installed (CI uses -m "not integration"; the integration
        # test that needs it is opt-in).
        try:
            from patchright.sync_api import sync_playwright
        except ImportError as exc:
            raise ImportError(
                "STEALTH_BACKEND=patchright requires `pip install "
                "patchright>=1.61,<2`. See requirements-ci.txt. "
                f"Underlying error: {exc}"
            ) from exc
        return sync_playwright()


class _PlaywrightStealthBackend:
    """Legacy path — upstream Playwright + AtuboDad / Mattwmaster58
    stealth layer.
    """

    name: str = "playwright_stealth"
    description: str = (
        "Upstream Playwright with the legacy playwright-stealth "
        "(AtuboDad / Mattwmaster58) JS evasion layer. Frozen "
        "since Sep 2023; preserved for back-compat. Consider "
        "switching to STEALTH_BACKEND=patchright."
    )
    layer_stealth: bool = True
    cloudflare_bypass: bool = False

    def sync_playwright(self) -> Any:
        from playwright.sync_api import sync_playwright
        return sync_playwright()


class _PlaywrightBackend:
    """Bare upstream Playwright, no stealth. Local dev + tests."""

    name: str = "playwright"
    description: str = (
        "Upstream Playwright with no stealth layer. Local "
        "development and unit tests only; Cloudflare 1015 within "
        "seconds against FaG."
    )
    layer_stealth: bool = False
    cloudflare_bypass: bool = False

    def sync_playwright(self) -> Any:
        from playwright.sync_api import sync_playwright
        return sync_playwright()


def get_backend() -> BrowserBackend:
    """Return the selected backend based on STEALTH_BACKEND.

    Default is `patchright` (the audit-recommended swap). Raises
    ValueError on an unknown value.
    """
    name = os.environ.get("STEALTH_BACKEND", "patchright")
    if name == "patchright":
        return _PatchrightBackend()
    if name == "playwright_stealth":
        return _PlaywrightStealthBackend()
    if name == "playwright":
        return _PlaywrightBackend()
    raise ValueError(
        f"Unknown STEALTH_BACKEND={name!r}. "
        f"Supported: {SUPPORTED_BACKENDS}"
    )


def cf_verify(url: str | None = None) -> bool:
    """Cloudflare verification stub (issue #94, follow-up).

    Today: no-op. Returns False so callers see the consistent
    "no recovery" signal. The operator PR (per the audit's
    recommendation #3) replaces this body with a real challenge
    re-fetch path: when a 403/503 lands mid-batch, the gate
    triggers a humanized re-challenge per session and retries
    the page once.

    Args:
        url: Optional URL to verify. Ignored today; reserved
            for the follow-up implementation.

    Returns:
        True if the challenge was passed; False otherwise.
    """
    log.debug(
        "cf_verify(%s) is a no-op today; install nodriver for "
        "a real implementation. See docs/research/competitive-"
        "audit.md §Axis 2.",
        url,
    )
    return False


__all__ = [
    "BrowserBackend",
    "SUPPORTED_BACKENDS",
    "cf_verify",
    "get_backend",
]