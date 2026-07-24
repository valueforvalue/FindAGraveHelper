# Learning: Why `test_real_fag_memory.py` is excluded from the default suite

> **Earned by:** Slice 1 cleanup (issue #92). Documents the by-design
> `pytest.mark.integration` exclusion on
> `tests/test_real_fag_memory.py` and the diag variant that
> replaced it for default CI.

## What happened

After the post-pass extraction + runner cleanup (PRs #85–#90,
audit in `docs/research/runner-audit.md`), the suite reported
"1 deselected" alongside the ground-truth skip. That deselect was
`tests/test_real_fag_memory.py::test_steady_state_rss_growth_per_record`,
which is marked `pytest.mark.integration` and excluded by the
default `addopts = -m "not integration"` filter in `pytest.ini`.

The exclusion is intentional and correct under the project's hard
constraints. This file documents why, so the next contributor
doesn't try to "fix" it by removing the marker.

## Why the integration test is excluded by default

`test_steady_state_rss_growth_per_record` exercises the full
Playwright + `BrowserSession` + FaG search path to measure
per-record RSS growth. Three constraints make that unsafe in
default CI:

- **L1 (CONTEXT.md):** The 2.5 s throttle floor is non-negotiable.
  The test uses 0.2 s throttle to fit the 10-record measurement
  window into reasonable wall-clock time — exactly the opt-in path
  `BrowserSession.__init__` warns against (issue #61 operator
  opt-in via `enforce_throttle_floor=False`).
- **L2 (CONTEXT.md):** The test requires the Playwright + stealth
  + warmup dance to function. CI containers often lack the
  Chromium binary; Playwright would either skip silently (false
  green) or crash (false red).
- **L8 (CONTEXT.md):** FaG requires Playwright + stealth; the
  test would touch `findagrave.com` for real. The first sustained
  burst of requests from a CI IP triggers Cloudflare 1015 within
  seconds (per Run #1 learnings, 2026-07-16). The 30-minute
  backoff would then wedge the runner.

Combined: the integration test cannot run safely in a CI
environment, and a "successful" default-suite run that hides this
fact would erode trust in the regression net.

## What the diag variant covers

`tests/test_real_fag_memory_diag.py` (added in this commit) runs
by default under `pytest.mark.diag` — the `diag` marker is NOT
excluded by `addopts = -m "not integration"`. It exercises:

- **Warmup + measurement plumbing:** `_rss_mb_diag()` + the 5
  warmup / 10 measurement phase split. Confirms the RSS sampler
  works on the host platform and the measurement math runs.
- **Per-call accumulation:** each pensioner record is searched
  exactly once across the run.

It does NOT assert absolute MB thresholds (those require real
Chromium and the live memory-leak surface). It catches regressions
in the harness itself, the RSS sampler, and the per-record
math, without touching the network.

## Operator path to the integration test

```bash
# Run only the integration test:
pytest -m integration tests/test_real_fag_memory.py -v

# Run integration + diag:
pytest -m "integration or diag" -v

# Run the full suite including integration (operator-only path):
pytest -m "" tests/
```

## Acceptance for future maintainers

If you find yourself tempted to drop the `integration` marker or
remove `-m "not integration"` from `pytest.ini`, **don't**. The
constraint stack (L1 + L2 + L8) makes the integration test
unsafe to run by default, and the diag variant covers the
plumbing regression surface adequately.

If a new browser session shape changes the RSS measurement math,
update the diag test alongside the integration test in the same
commit. The two share the warmup/measurement window logic;
diverging them silently would let a harness bug ship undetected.

## Related

- CONTEXT.md §L1, §L2, §L8
- `pytest.ini` — `markers` declaration, `addopts` default filter
- `tests/test_real_fag_memory.py` — the integration test
- `tests/test_real_fag_memory_diag.py` — the diag variant
- `docs/research/runner-audit.md` — the audit that surfaced this
- Issue #92 — the GitHub issue filed for this fix