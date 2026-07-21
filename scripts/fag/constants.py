"""FaG-specific constants (issue #67).

Central source of truth for Find a Grave integration values.
Every magic number/URL scattered across the codebase should
reference these constants instead of local literals.
"""
from __future__ import annotations

# FaG search base URL. Every FaG strategy builds on this.
FAG_SEARCH_BASE_URL: str = "https://www.findagrave.com/memorial/search"

# Minimum throttle between FaG requests (L1 floor).
# Lowering below this re-introduces the Cloudflare 1015
# rate-limit risk documented in CONTEXT.md L1.
FAG_THROTTLE_FLOOR: float = 2.5

# Per-strategy throttle within a single pensioner sweep.
# Matches the L1 floor by default; can be raised for
# conservative runs or lowered in slice mode with opt-in.
FAG_STRATEGY_THROTTLE: float = 2.5
