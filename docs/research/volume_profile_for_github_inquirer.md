# FindAGraveHelper — Volume Profile & Proxy Logic

> **Audience:** an external inquirer asking whether this project's
> FaG scrape is built for real production volume or only internal
> testing, and where proxy / quality logic would enter the picture.
>
> **Date:** 2026-07-31
> **Author:** maintainer analysis (Jeremy Morris)
>
> **Source data:**
> - `data/results/run_50_test_smoke/` — 50-pensioner FaG/CGR run,
>   2026-07-16, real Playwright + stealth, throttle=2.0s.
> - `data/results/run_2026_07_24_g10_stealth_swap_verification/` —
>   10-pensioner Blackboard architecture run, 2026-07-24, throttle=2.5s.
> - `docs/learnings/2026-07-16-run-1-learnings.md`,
>   `docs/learnings/2026-07-16-run-2-learnings.md` — earned-by-bug
>   notes (DOM crash, memory leak).
> - `CONTEXT.md` L1, L2, L8, L10, L12 — the laws that pin the
>   throttle / browser-reset / resume / lease behavior.

## TL;DR

This is an **internal-research-volume** project (a single operator
working through ~7,700 Oklahoma Confederate pensioners against
Find a Grave memorials). The architecture is correct for the
workload it actually has. There is **no proxy logic** anywhere
in the codebase, on purpose. Where the design IS opinionated
about volume quality, it shows up as: throttling,
per-record memory hygiene, resume-safe state writes, lease TTL
on dispatched work, and a Cloudflare ResponseClassifier that
handles the rare 1015 backoff.

If you are evaluating this as a *starting point* for higher-volume
work, the right patterns to lift are the throttle, the per-record
flush, and the lease TTL. The right things to add for a 10×+ scale
up are: distributed FaG query (multiple browser sessions behind
proxies with per-session throttles), per-IP rate measurement,
and a CAPTCHA-solver decision policy. None of those are in scope
for the current 7,700-pensioner workload.

## 1. The actual workload

**Volume profile** (from `data/results/run_50_test_smoke/run.log`
+ state.jsonl, 2026-07-16 run):

| Metric | Value |
| --- | --- |
| Pensioners in canonical roster | 7,709 |
| Records in this run (smoke) | 50 |
| Wall time | 221.2s (~3.7 min) |
| Throughput | ~0.23 records/s |
| FaG request rate | ~0.4 req/s (throttle=2.0s + page loads) |
| Status: `auto_accept` | 5 (10%) |
| Status: `too_many` (>20 candidates) | 43 (86%) |
| Status: `skip` (CGR strong, no FaG name match) | 2 (4%) |
| Status: `no_results` / `error` / `captcha` | 0 |
| Outliers flagged | 3 (6%, all low-score) |
| CGR + FaG agree (BOTH MATCH) | 13 (26%, all via corroboration) |
| Errors | 0 |

**Blackboard run profile** (from
`data/results/run_2026_07_24_g10_stealth_swap_verification/run_analytics.json`,
2026-07-24, throttle=2.5s, the architecture shipped in commit
c2b…):

| Knowledge Source | Work items | Avg dur (s) | p95 dur (s) | Success rate |
| --- | ---:| ---:| ---:| ---:|
| `RegionalPlannerKS` | 10 | 0.05 | 0.07 | 100% |
| `FaGScraperKS` | 65 | **17.9** | **23.1** | 100% |
| `CandidateScorerKS` | 20 | 0.05 | 0.09 | 100% |
| `DeepRefinerKS` | 10 | 0.11 | 0.21 | 100% |
| `CalibratedDecisionKS` | 10 | 0.05 | 0.07 | 100% |

The dominant cost is **FaGScraperKS** at ~18-23s per work item
(a work item is one scraped memorial page; each pensioner
generates 2-7 work items depending on how many results the
planner escalates to). Everything else is sub-second CPU.

**Per-record memory + state** (CONTEXT.md L2, L3, L10):

- `page.inner_text("body")` returns a 200KB+ string per result
  page; the harness must `del` the locator and body_text refs and
  `gc.collect()` every 25 records, or RSS grows unbounded.
- `state.jsonl` is flushed per-pensioner (`f.flush();
  os.fsync(f.fileno())`). A `kill -9` mid-run loses at most one
  record.
- Work items carry a lease TTL (default 60s) with a heartbeat
  thread that extends the deadline while the KS is running.
  After 3 failed attempts, the item transitions to `BLOCKED`
  for operator review (L12).

## 2. Why no proxy logic

The throttle is the rate limit (CONTEXT.md L1, earned by Run #1).
**At ~0.4 req/s, a single browser session never trips the
Cloudflare Turnstile 1015 backoff.** The throttle is *the* rate
limit; proxies would be a different rate limit, but adding them
now is a no-op for this workload and creates operational cost
(proxy quality, rotation logic, cost).

Three concrete consequences:

1. **No proxy rotation.** Single Playwright session, single
   egress IP. The 2.5s throttle means at most 2,400 req/hour
   per IP, well under the Cloudflare threshold. (For reference:
   a 30-min 1015 backoff is the failure mode if the throttle
   is bypassed, and it dwarfs the saved throttle time. This is
   documented in `docs/learnings/2026-07-16-run-1-learnings.md`.)

2. **No CAPTCHA solver.** `captcha` status in the run table
   above is 0. The Cloudflare challenge is rare at this volume;
   the `ResponseClassifier` (`scripts/blackboard/`) detects
   it before the parser and either retries or transitions the
   work item to `BLOCKED`. A solver would only matter at much
   higher request rates.

3. **No IP rotation, no UA spoofing, no fingerprint rotation.**
   Stealth is handled by `patchright` (binary-level
   Runtime.Enable fix) + `playwright-stealth` (JS evasions) +
   a Cloudflare warmup visit to the homepage. This is sufficient
   for a single egress IP at this request rate. See commit
   history for the L8 + #94 swap from `playwright_stealth` to
   `patchright`.

## 3. Where volume quality *does* show up

The design is not naive about volume; it's opinionated about
*correct* volume quality. The patterns that earned their keep:

- **Throttle = rate limit** (L1, earned 2026-07-16): the single
  most important design decision. Anything that bypasses it
  is a bug.
- **Per-record flush + fsync** (L3, L10): no batched writes, no
  "wait until the buffer is full." A `kill -9` loses at most
  one record (the in-flight one).
- **Browser reset on closed-target** (L2, earned Run #2): the
  Playwright exception "Target page, context or browser has
  been closed" is a stable substring (not the full message) so
  the recovery triggers across Playwright versions.
- **Lease TTL + heartbeat** (L12, earned Scheduler Phase 5):
  a Cloudflare challenge mid-invoke doesn't permanently lock
  the work item; the deadline-based reclaim cycle picks it up.
- **Locator hygiene every 25 records** (earned Run #2 memory
  leak): 200KB strings live until function exit. Without
  periodic `del` + `gc.collect()`, RSS grows unboundedly.

## 4. What a 10×+ scale-up would actually need

If the workload jumped from 7,700 pensioners to 77,000 (one
state, not OK) or 770,000 (a multi-state CGR-style pass), the
following would be required *in addition* to the current
design:

1. **Distributed browser sessions.** Multiple Playwright
   processes, each on its own egress IP, with per-session
   throttles. The Blackboard Scheduler already supports
   multi-process dispatch (see L12 lease + heartbeat) but
   only one process is running today.

2. **Per-IP rate measurement.** A counter that watches
   `429 / 403 / 1015` responses per session and shifts new
   work to cooler sessions. Today the throttle is
   *preventative* (constant 2.5s gap) rather than
   *reactive* (measured response).

3. **CAPTCHA-solver decision policy.** At higher rates the
   rare Cloudflare challenge stops being rare. A decision
   branch in `DecisionPolicy.classify()` would weigh
   "spend $0.001 on a solver" vs "transition to BLOCKED."

4. **Proxy quality scoring.** If a proxy is added, the
   per-session FaGScraperKS p95 already surfaces the right
   metric (~18-23s). Sessions whose p95 climbs above, say,
   35s would be evicted and replaced.

None of these are in the current design because the workload
doesn't demand them. **Adding them prematurely is the "premature
scale" anti-pattern the architecture explicitly avoids.**

## 5. Reproducing the numbers

```bash
# The 50-pensioner smoke:
ls data/results/run_50_test_smoke/
# state.jsonl — per-pensioner outcomes
# outliers.jsonl — flagged for follow-up
# report_*.md / report_*.json — auto-generated summary
# run.log — the run log with heartbeats

# The Blackboard 10-pensioner reference run:
ls data/results/run_2026_07_24_g10_stealth_swap_verification/
# results.jsonl — per-pensioner decision records
# run_analytics.json — per-KS work-item timing + success rate
# run_audit.ocsf.jsonl — OCSF-formatted audit events
# run.log — start/finish + errors
```

## 6. Bottom line for the inquirer

- The FaG scrape piece is **internal testing / manual research
  volume** (a single operator, 7,700 pensioners, ~0.4 req/s,
  resume-safe over many short sessions).
- There is **no proxy layer** and adding one now would be
  premature for the workload.
- The architecture is **opinionated about correct volume**:
  throttle, per-record flush, lease TTL, memory hygiene.
  Those patterns transfer to higher-volume work; the design
  has earned each of them by real bugs (L1/L2/L3/L10/L12).
- The hard scaling work (multi-session, per-IP rate
  measurement, CAPTCHA-solver policy) is **explicitly out of
  scope** and the design intentionally does not pay that cost.

If you want to discuss the proxy/scale architecture for a
production FaG scraper, the right starting points in the
codebase are: `scripts/fag/fag_browser.py` (browser layer),
`scripts/blackboard/scheduler.py` (lease + heartbeat),
and `scripts/search/fag_engine.py` (the per-search Protocol).
