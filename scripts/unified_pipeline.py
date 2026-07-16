"""Back-compat shim. Real implementation: scripts/pipeline/core.py (T019)."""
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