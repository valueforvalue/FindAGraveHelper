"""Back-compat shim. Real implementation: scripts/pipeline/core.py (T019).

DECISION POLICY (LOCKED 2026-07-16):

  We ALWAYS run FaG for every pensioner in
  docs/research/digitalprairie/ok_pensioners.json. The CGR blocking
  index exists only to annotate matches for human display and
  post-run CGR-side dedup work; it MUST NOT gate whether we search
  FaG.

  If you are tempted to add a "skip FaG if CGR strong" gate:
  STOP. Open an issue instead. Do not gate the FaG search.
"""
from scripts.pipeline.core import (
    PipelineConfig,
    PipelineResult,
    run_pipeline_for_pensioner,
    pipeline_result_to_unified,
    UnifiedRunResult,
)

__all__ = [
    "PipelineConfig",
    "PipelineResult",
    "run_pipeline_for_pensioner",
    "pipeline_result_to_unified",
    "UnifiedRunResult",
]