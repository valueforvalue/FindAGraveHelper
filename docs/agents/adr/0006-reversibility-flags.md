# ADR 0006: Reversibility flags for the unified pipeline

- **Status:** accepted
- **Date:** 2026-07-17
- **Closes:** issue #21

## Context

The Find a Grave Helper pipeline has a long history of wedged runs
that required manual state-file surgery to recover from:

- `docs/learnings/2026-07-16-run-1-learnings.md`: 30-min Cloudflare
  backoff after a throttle bypass. The only recovery option was to
  delete state.jsonl and start over (~40 min of lost work).
- `docs/learnings/2026-07-16-run-2-learnings.md`: Playwright
  memory leak wedged the browser after ~1,000 records. Recovery
  was a manual script edit + restart.
- Per pragmatic-programmer §6 Reversibility: "the cost of change
  should be proportional to the scope of change". Today, a wedged
  run costs the operator ~40 min regardless of how small the fix is.

## Decision

Add three CLI flags to `scripts/run_unified.py`:

1. **`--dry-run`**: exercise non-FaG pipeline stages against
   existing state.jsonl. No network. Output: JSONL diff file.
2. **`--state-replay PATH`**: apply new pipeline to OLD state,
   write NEW state in a separate output dir.
3. **`--rollback-to LABEL`**: restore state.jsonl from a named
   snapshot. 'latest' = most recent snapshot.

Supporting flags:

- **`--checkpoint-every N`**: auto-snapshot every N records
  during a live run. Default 1000.
- **`--write-checkpoint`** + **`--checkpoint-label`**: manual
  snapshot of current state.
- **`--list-checkpoints`**: list available snapshots.

## Alternatives considered

**A. Git-based rollback (commit state.jsonl after each batch).**
Rejected: state.jsonl can be 100MB+ per run. Git doesn't scale,
and committing data files mixes review concerns.

**B. SQLite with WAL mode as the state backend.**
Rejected: bigger blast radius (changes the wire format, breaks
view.html reader). Per #22's orthogonality work, the Repository
Protocol already abstracts the backend — a future migration is
possible without breaking callers.

**C. Just `--dry-run` (skip replay + rollback).**
Rejected: dry-run alone doesn't help if a run already produced
bad data. Need both forward (replay) and backward (rollback) tools.

## Consequences

**Positive:**

- Worst-case data loss drops from "the whole run" to "~N records"
  (the --checkpoint-every cadence).
- Strategy A/B testing no longer requires running FaG.
- Recovery from a wedged run is < 5 min for typical cases.

**Negative:**

- Each snapshot is a full copy of state.jsonl (~25MB at
  7,558 records). With 7,558 / 1000 = 8 auto-checkpoints per run,
  disk usage doubles. Mitigation: documented in the flag help.
- The `--state-replay` semantics rely on the historical state
  having populated `fag_records`. If the old state was written
  before the current schema, replay may produce unexpected results.

## Rollback plan

If the flags prove problematic, they're additive — removing them
is just deleting the argparse additions + the three new modules.
No existing behavior changes.

## Verification

- 29 new tests (12 dry-run + 8 state-replay + 9 checkpoint-rollback).
- Full suite: 966 passed (was 937 baseline).
- Each flag independently tested in `tests/`.
- `--help` shows all 6 new flags with descriptions.

## References

- `CONTEXT.md` §L1, L2, L3: the laws these flags help recover from
- `docs/learnings/2026-07-16-run-1-learnings.md`
- `docs/learnings/2026-07-16-run-2-learnings.md`
- Pragmatic programmer skill §6 Reversibility
- Issue #21 body (proposed approach)