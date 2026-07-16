"""scripts.pipeline: per-pensioner pipeline + batch orchestration.

T019 of the refactor merges scripts/unified_pipeline.py +
scripts/unified_runner.py into this subpackage. The single
public surface is scripts/pipeline/core.py. T021 will move
this to scripts/pipeline/ as the production location.

Public facade:
  - run_pipeline_for_pensioner(pensioner, cgr_index_vets, config,
    fag_search_fn, prebuilt_cgr_index) -> PipelineResult
  - PipelineConfig, PipelineResult
  - build_cgr_blocking_index, lookup_cgr_for_pensioner,
    annotate_cgr_matches, should_skip_fag
  - write_state_line, load_cgr_index_from_jsonl
  - UnifiedConfig, UnifiedRunResult (back-compat aliases)
"""