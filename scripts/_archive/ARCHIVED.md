# scripts/_archive/ — empty archive

This directory is reserved for future modules that have **zero
production importers** in `scripts/` but might be referenced from
`view.html`, the userscript, or external callers.

## Status (2026-07-16)

**Empty.** T020's audit found no true orphans.

The two candidates initially flagged (`scripts/cgr_fag_link.py`
and `scripts/spouse_cross_ref.py`) are NOT orphans:

- `spouse_cross_ref.py` — Prototype for the T005 task
  ("Spouse cross-reference (full pipeline)") in TASKS.csv.
  The CONTEXT.md glossary defines "Spouse cross-reference" as
  a first-class domain concept. Module is parked, awaiting T005
  integration.

- `cgr_fag_link.py` — Prototype for the BOTH MATCH "direct_link"
  detector. `scripts/both_match.py` accepts `fag_link: dict | None`
  as a parameter (line 228). When T005 / the BOTH MATCH work is
  re-opened, this is the seed.

## When to actually move a module here

- The module has zero production imports in scripts/
- The module has zero references in docs/, AGENTS.md, CONTEXT.md,
  or TASKS.csv
- AND you can't find any plausible caller in view.html or
  the userscript

If any of those conditions is false, leave the module in place
and file an issue instead.