# checkpoint.py audit (T024)

## Question

Is `scripts/checkpoint.py` dead code? The structural audit (background
agent, 2026-07-16) flagged it as a candidate orphan — no static `import
scripts.checkpoint` was found, only a runtime suspicion of calls from
`scripts/leftover_investigation.py`.

## Method

`grep` across `scripts/` and `tests/` for `checkpoint.`,
`write_checkpoint`, `read_checkpoint`, `record_failure`, `is_resumable`.

## Findings

| Symbol | Defined | Production callers | Test callers |
|---|---|---|---|
| `write_checkpoint` | `scripts/checkpoint.py:22` | `scripts/search_fag.py:1601` | `tests/test_checkpoint.py`, `tests/test_loop_crash_safety.py` |
| `read_checkpoint` | `scripts/checkpoint.py:51` | `scripts/search_fag.py` (via `is_resumable` and direct read) | `tests/test_checkpoint.py`, `tests/test_loop_crash_safety.py` |
| `record_failure` | `scripts/checkpoint.py:66` | `scripts/search_fag.py:1611` | `tests/test_checkpoint.py`, `tests/test_loop_crash_safety.py` |
| `is_resumable` | `scripts/checkpoint.py:61` | `scripts/search_fag.py` (via `is_resumable(...)` call) | `tests/test_checkpoint.py` |

54 matches across 4 files.

> **Note (2026-07-17):** `scripts/checkpoint.py` was a back-compat
> shim for `scripts.fag.search` consumption; the canonical home
> is `scripts.pipeline.checkpoint` (post-T021 subpackage split).
> The shim was deleted as part of issue #19. The bare import
> pattern noted below (`from checkpoint import …`) was fixed
> by `scripts/search_fag.py` using the canonical
> `from scripts.pipeline.checkpoint import` path.

## Verdict

**Live, not dead.** All four exported symbols are called by
`scripts/search_fag.py` in its batch loop. The audit's "no static
import" reading was a false positive caused by:

```python
# scripts/search_fag.py:65
from checkpoint import write_checkpoint, read_checkpoint, record_failure
```

This bare import (no `scripts.` prefix) relies on `sys.path` having
`scripts/` on it. It works because the project's entry points
(`run_unified.py`, `leftover_investigation.py`, etc.) add `scripts/` to
the path. It's fragile — the audit's static parser couldn't see it as
a `scripts.checkpoint` edge. **T017 (split search_fag.py) should fix
this to `from scripts.pipeline.checkpoint import …`.**

## Side effect on T020

T020 (archive orphan libraries) does **not** need to consider
`checkpoint.py`. The four true orphans remain:

- `scripts/cgr_fag_link.py` (zero importers)
- `scripts/nickname_match.py` (test-only importers)
- `scripts/regiment_keyword.py` (test-only importers)
- `scripts/spouse_cross_ref.py` (test-only importers)

Each gets confirmed via a production-caller grep before archive.

## Status

✅ T024 complete. Verdict: keep `checkpoint.py`; fix its import path
during T017.