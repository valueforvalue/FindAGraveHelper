"""Back-compat shim. Real implementation: scripts/pipeline/core.py (T019)."""
from scripts.pipeline.core import (
    build_cgr_blocking_index,
    lookup_cgr_for_pensioner,
    annotate_cgr_matches,
    should_skip_fag,
    UnifiedConfig,
    UnifiedRunResult,
    write_state_line,
    load_cgr_index_from_jsonl,
)

__all__ = [
    "build_cgr_blocking_index",
    "lookup_cgr_for_pensioner",
    "annotate_cgr_matches",
    "should_skip_fag",
    "UnifiedConfig",
    "UnifiedRunResult",
    "write_state_line",
    "load_cgr_index_from_jsonl",
]