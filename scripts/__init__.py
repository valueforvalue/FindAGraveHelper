"""scripts/: Find a Grave Helper Python harness.

T021 of the refactor restructured this package into subpackages:

  scripts.fag/        - Find a Grave search + browser integration
  scripts.cgr/        - Confederate Graves Registry integration
  scripts.matching/   - generic record-linkage primitives
  scripts.pipeline/   - per-pensioner pipeline + batch orchestration
  scripts.state/      - state.jsonl wire format + integrity checks
  scripts.ingest/     - input scrapers (digital prairie, etc.)
  scripts.analysis/   - throwaway analysis scripts
  scripts.search/     - FaG search-strategy ladder (T017 split)
  scripts._archive/   - empty archive scaffold (T020 audit)

Cross-package public facade re-exported here so existing callers
that `import scripts.X` keep working without changes:

  scripts.run_unified.run_batch
  scripts.search_fag.search_one_pensioner
  scripts.state_normalize.normalize_state_record
  scripts.state.report_generator.build_report

NOTE: scripts.run_unified.write_unified_line was REMOVED in the
issue #22 iteration. Use JsonlStateRepository directly:
  from scripts.state.repository import JsonlStateRepository
  JsonlStateRepository(state_path).append(record)

The flat `scripts/*.py` files at the root are back-compat shims
that re-export from the new subpackages. They will be removed
after one release cycle.
"""

# Top-level public facade re-exports (T021 acceptance).
from scripts.pipeline.run_unified import run_batch
from scripts.search_fag import search_one_pensioner  # back-compat shim -> scripts.fag.search_fag
from scripts.state_normalize import normalize_state_record  # back-compat shim -> scripts.state.normalize
from scripts.state.report_generator import build_report  # back-compat shim -> scripts.state.report_generator