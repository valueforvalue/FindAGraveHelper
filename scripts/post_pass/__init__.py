"""Post-pass registry and shared types.

Slice 7: the `POST_PASSES` registry + `run_post_passes()` driver
live here. Adding a new post-pass = write the module + append
one tuple to the registry.
"""
from __future__ import annotations

from scripts.post_pass._registry import POST_PASSES, run_post_passes
from scripts.post_pass.types import BasePassConfig, PostPassStats

__all__ = [
    "BasePassConfig",
    "POST_PASSES",
    "PostPassStats",
    "run_post_passes",
]