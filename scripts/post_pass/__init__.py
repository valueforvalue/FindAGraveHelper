"""Post-pass registry and shared types.

Slice 1 of docs/designs/post-pass-extraction.md. The full registry
(`POST_PASSES`) is built up across Slices 2–7; for now this module
exposes the types and the first pass.
"""
from __future__ import annotations

from scripts.post_pass.types import (
    BasePassConfig,
    PostPassStats,
)

__all__ = ["BasePassConfig", "PostPassStats"]