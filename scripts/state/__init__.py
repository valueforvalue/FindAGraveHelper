"""scripts.state: typed boundary DTOs for the state.jsonl wire format.

T018 of the refactor. The wire format stays JSONL (one object per
line, flushed per-pensioner per L3); this subpackage provides typed
fronts so consumers can reason about field shapes without re-parsing
the cross-layer-contract.md docstring.

Public surface (scripts/state/schema.py):
  - PensionerRecord: one row in state.jsonl
  - CandidateRecord: one FaG candidate inside fag_records
  - BothMatchRecord: the CGR+FaG corroboration verdict
  - from_dict_* adapters: dict -> dataclass
  - SCHEMA_VERSION: bump on breaking changes

Why dataclasses, not pydantic:
- No new runtime dependency (dataclasses is stdlib in 3.7+).
- State records are flat dicts on the wire; pydantic's nesting +
  coercion isn't needed.
- Tests assert the schema with plain `assert` calls, no fixtures.

Backwards-safe: missing fields default to "" / [] / None. Unknown
fields pass through to_dict() so adding a new field to the writer
doesn't silently strip it from the reader.
"""