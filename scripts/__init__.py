"""scripts/: Find a Grave Helper Python harness.

T021 of the refactor restructured this package into subpackages:

  scripts.fag/          - Find a Grave search + browser integration
  scripts.cgr/          - Confederate Graves Registry integration
  scripts.matching/     - generic record-linkage primitives
  scripts.pipeline/     - per-pensioner pipeline + batch orchestration
  scripts.state/        - state.jsonl wire format + integrity checks
  scripts.ingest/       - input scrapers (digital prairie, etc.)
  scripts.analysis/     - throwaway analysis scripts
  scripts.search/       - FaG search-strategy ladder (T017 split)
  scripts.blackboard/   - Local-First Blackboard (since 2026-07-17)
  scripts.learning/     - self-learning loop (since 2026-07-20)
  scripts._archive/     - empty archive scaffold (T020 audit)

The flat `scripts/*.py` files at the root are canonical
entrypoints (not back-compat shims):

  scripts.run_unified.py       - CLI entrypoint (Blackboard default)
  scripts.search_fag.py        - legacy FaG search entry (importable)
  scripts.batch_config.py      - RunRecipe dataclass
  scripts.state_normalize.py   - normalize StateRecord for v2 view
  scripts.spouse_cross_ref.py  - prototype (see _archive/ARCHIVED.md)
  scripts.soak_memory.py       - manual Playwright leak smoke
  scripts.smoke_diff.py        - legacy-vs-scheduler output diff
  scripts.view.html            - legacy v1 review UI
  scripts.view/v2.html         - default v2 review UI (Alpine.js)

Cross-package public facade re-exported here so existing callers
that `import scripts.X` keep working without changes:

  scripts.run_unified.run_batch
  scripts.search_fag.search_one_pensioner
  scripts.state_normalize.normalize_state_record
  scripts.state.report_generator.build_report

State writes route through `scripts.state.repository.JsonlStateRepository`
— never write to state.jsonl directly. The Repository enforces
L3 (per-pensioner flush), L5 (newline-delimited JSON), and L10
(`os.fsync` after each write).
"""