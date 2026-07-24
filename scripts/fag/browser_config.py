"""BrowserConfig: single source of truth for BrowserSession knobs (Slice 9).

Replaces the seven forward-passed kwargs in `UnifiedRunnerConfig`
(`throttle`, `reset_every`, `headless`, `state_filter`,
`auto_relax`, `max_consecutive_errors`, `enforce_throttle_floor`)
with one frozen dataclass. The L1 throttle floor logic stays in
`BrowserSession.__init__` (where the value error lives).

Additive change: `BrowserSession` still accepts all kwargs
directly for back-compat with the 5 existing callers. New code
uses `BrowserSession.from_config(BrowserConfig)`.

`UnifiedRunnerConfig` gains a `browser_config: BrowserConfig`
field; the seven old fields stay with deprecation shims (PEP 562
`__getattr__`) so existing test signatures keep compiling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BrowserConfig:
    """All tunable knobs for BrowserSession.

    Defaults match BrowserSession.__init__'s historical defaults
    so that `BrowserConfig()` reproduces the pre-Slice-9 behavior.

    L1 floor: `throttle` < 2.5s re-introduces Cloudflare 1015 risk;
    `enforce_throttle_floor=False` is required to relax it.
    """

    throttle: float = 2.5
    reset_every: int = 250
    headless: bool = False
    state_filter: str = "OK"
    auto_relax: bool = False
    max_consecutive_errors: int = 10
    user_agent: Optional[str] = None
    enforce_throttle_floor: bool = True

    @classmethod
    def from_unified(cls, parent: object) -> "BrowserConfig":
        """Build BrowserConfig from a UnifiedRunnerConfig.

        Reads each field via `getattr(parent, name, default)` so
        older configs that don't yet carry the dataclass still
        produce a valid BrowserConfig.
        """
        return cls(
            throttle=getattr(parent, "throttle_seconds", 2.5),
            reset_every=getattr(parent, "browser_reset_every", 250),
            headless=getattr(parent, "headless", False),
            state_filter=getattr(parent, "browser_state_filter", "OK"),
            auto_relax=getattr(parent, "auto_relax", False),
            max_consecutive_errors=getattr(
                parent, "max_consecutive_errors", 10
            ),
            user_agent=None,
            enforce_throttle_floor=getattr(
                parent, "enforce_throttle_floor", True
            ),
        )