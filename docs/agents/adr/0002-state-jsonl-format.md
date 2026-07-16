# ADR 0002 — `state.jsonl` as the canonical wire format

## Status

`Accepted` (2026-07-16). Earned by Run #1 mid-run crash
(2026-07-16). See [`CONTEXT.md` §L3, L4, L5](../../CONTEXT.md).

## Context

The Python harness writes per-pensioner records; the
`view.html` review UI reads them. The wire format must
support:

- **Resume-safety**: a crash mid-run leaves the file
  reloadable by re-running with the same `--state` path.
  Implies per-pensioner flush, not a final write.
- **Streaming reads**: `view.html` reads the file lazily
  (currently synchronous; lazy-load is T002). One object
  per line is the only format that streams cleanly.
- **Round-trip to dixiedata**: `scripts/dd_marker_run.py`
  consumes a `decisions.csv` exported from `view.html`. The
  CSV columns must match the state.jsonl keys.

The forces in tension:

- **JSONL vs. JSON array**: array is human-friendly but
  cannot be appended mid-run. JSONL streams cleanly.
- **Pretty-print vs. compact**: pretty-print is debuggable
  but breaks the `},` splitter (we use `\n`; pretty-print
  introduces `\n` inside objects).
- **Stable key order vs. performance**: Python 3.7+
  guarantees dict insertion order, so this is free.

## Decision

The canonical wire format is **newline-delimited JSON**, one
pensioner per line. Schema is documented in
[`docs/agents/cross-layer-contract.md` §"The wire format: state.jsonl"](cross-layer-contract.md).

Hard rules (each is a `CONTEXT.md` law):

- **L3**: every record flushes (`f.flush(); os.fsync(f.fileno())`)
  before the next pensioner starts.
- **L4**: stable JSON key order. Adding/renaming keys
  requires coordinated changes in `view.html`.
- **L5**: one line per pensioner. No `[...]` wrapper. No
  pretty-print.

### Alternatives rejected

- **JSON array, written at end** — rejected, cannot resume
  after a mid-run crash.
- **SQLite** — rejected, single-operator tool, file-based
  portability matters more than query speed.
- **CSV** — rejected, the ranked candidates array is
  inherently nested; CSV flattens badly.
- **Pickle** — rejected, opaque format; `view.html` is
  browser-side and can't read Pickle.

## Consequences

**Positive:**

- Resume-safe by design (the L3 flush+fsync discipline
  guarantees that a kill -9 loses at most the in-flight
  pensioner).
- Streams cleanly to `view.html` and downstream tools.
- The CSV export is a deterministic transformation of the
  state.jsonl, easy to validate.

**Negative:**

- JSONL is not human-greppable for non-trivial queries.
- The schema-drift risk between Python writer and `view.html`
  reader is non-zero. Mitigated by the
  `tests/test_view_html.py` round-trip test.

**When to revisit:**

- `view.html` adds interactive filtering (T002). At that
  point a per-pensioner index may be cheaper than a full
  parse. Even so, the format stays JSONL.
- The `dd_marker_run.py` consumer wants richer metadata.
  Add keys; never remove or rename without coordinated
  changes.

**Related:**

- [`CONTEXT.md` §L3, L4, L5](../../CONTEXT.md)
- [`cross-layer-contract.md` §"The wire format: state.jsonl"](cross-layer-contract.md)
- [`bug-catalog.md` §"Review UI layer"](bug-catalog.md)
- Commit `01ccfdf` (FaG search scope fix; later run used
  the state.jsonl format)