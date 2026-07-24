# Competitive Audit — FindAGraveHelper vs Similar Projects

> **Date:** 2026-07-22
> **Subject:** `valueforvalue/FindAGraveHelper` (227 commits, ~1,358
> passing tests, last commit `c8106c0`).
> **Axes:** CW genealogy / FaG scraping — browser-stealth
> frameworks — local-first blackboard / scheduler architectures.
> **Method:** Three parallel research streams, each
> benchmarking 3-5 peers; full sources cited per section.
> **Verdict:** Architecturally distinctive (Blackboard + KS +
> engine-agnostic ladder + Cloudflare-aware throttle is
> unmatched in this comparison). Visibility, integration testing,
> and one stealth layer (the JS-patch surface) lag peers.

---

## Axis 1 — CW genealogy / Find a Grave projects

| # | Project | Stars | Last activity | Scope | Browser | Throttle/CF | Resume | Tests | License |
|---|---|---:|---|---|---|---|---|---|---|
| 1 | [doug-foster/Find-a-Grave-Tools](https://github.com/doug-foster/Find-a-Grave-Tools) | 7 | Oct 2025 | Stash-and-extract: pull cemetery pages, parse later into Excel | `requests` + BS4, no JS | None | File cache only | None | GPL-3.0 |
| 2 | [mcqueary/graver](https://github.com/mcqueary/graver) | 2 | Nov 2023 | CLI: given a list of memorial IDs, scrape → SQLite | `requests` + BS4 | None, no stealth | None | CI + Coveralls | MIT |
| 3 | [miyakoj/Find-a-Grave-Memorial-Extractor-Browser-Extension-for-Chromium](https://github.com/miyakoj/Find-a-Grave-Memorial-Extractor-Browser-Extension-for-Chromium) | 0 (shipped) | Jan 2026 | Browser-extension CSV dump of a cemetery's list page | Runs in user tab; honors FG's 10k cap | FG default rate-limit | None | Manual across 5 fixtures | MIT |
| 4 | [mattprusak/autoresearch-genealogy](https://github.com/mattprusak/autoresearch-genealogy) | 1.2k | Jun 2026 | 13 Claude Code prompts, including `03-findagrave-sweep` | Claude Code browser | Implicit | Per-session autonomous loop | `scripts/validate-repo` | MIT |
| 5 | [OpenGravestones](https://github.com/OpenGravestones/OpenGravestones) | 19 | 2015 (abandoned) | Schema-first cemetery data (JSON-LD, Muninn Graves ontology) | BillionGraves API + manual | None | N/A | None | CC0 |

### Where the subject leads
- **Only project that fuses** a Blackboard + Scheduler + KS control
  architecture with engine-agnostic search abstractions (FaGEngine +
  NewspapersComEngine share one pipeline).
- **Only project with a 13-strategy ladder** + per-strategy audit
  logging + cross-run dedup.
- **Only project with Cloudflare-aware Playwright/stealth throttling**
  — peers stuck on `requests`+BS4 (graver, Find-a-Grave-Tools)
  would be blocked by FaG's current challenge page; autoresearch
  delegates crawling to Claude Code without owning transport.
- **Local-first SQLite-WAL** + per-row fsync + lease TTL
  (CONTEXT.md L9-L12) is unmatched. Only graver runs CI, at <100
  commits and no `LiveProcess` abstraction.

### Where it lags
- **0 stars** vs. autoresearch-genealogy's 1.2k; no onboarding docs
  for non-CW researchers.
- **Userscript half** tied to Tampermonkey; miyakoj's extension is
  a simpler fit for casual users.
- **Fellegi-Sunter scorer is heuristic** (hand-tuned priors), not
  learned end-to-end — record-linkage precision depends on priors.
- **No export to open-burial-data formats** (Schema.org/Cemetery,
  Muninn Graves ontology). Limits interop with WikiTree + Wikidata
  tooling miyakoj already exploits.

### Top improvements
1. **Adopt open-burial-data export.** Add
   `scripts/exports/open_gravestones.py` emitting JSON-LD per
   Schema.org/Cemetery + Muninn Graves + WikiTree/Wikidata link
   column. *Effort: 3-5 days. Impact: high* — unlocks miyakoj-style
   extension ecosystem.
2. **Plug a learned pairwise scorer alongside Fellegi-Sunter.**
   `scripts/calibration/` already exists; wire `CalibratedClassifier`
   + `PairwiseWeightLearner` into the Blackboard decision path.
   *Effort: 1-2 weeks.* Impact: high — raises the 80% cold-start
   hit-rate flagged in `docs/v5-design/`.
3. **Ship a one-shot Docker image + GitHub Action** that runs the
   pytest suite + a small Playwright smoke. Containerized run with
   `playwright install chromium` pre-baked + sandbox-mode flag
   closes the e2e gap from `docs/learnings/2026-07-22-real-fag-memory-default-skip.md`.
   *Effort: 1-2 days. Impact: medium* — currently no CI badge.

---

## Axis 2 — Browser-stealth scraping frameworks

| # | Name | Stars | Last Activity | Sync/Async | Stealth Method | Headless | Throttle Built-in | Resume Built-in | Maintenance |
|---|---|---:|---|---|---|---|---|---|---|
| 1 | [playwright-stealth](https://github.com/AtuboDad/playwright_stealth) (AtuboDad) | 979 | Sep 2023 | both | JS `addInitScript` patches | yes | no | no | **dormant** |
| 2 | [playwright-stealth v2](https://pypi.org/project/playwright-stealth/) (Mattwmaster58) | n/a | active on PyPI | both | refactored patch set | yes | no | no | **active** (PyPI maintainer) |
| 3 | [undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver) | 12.8k | Jul 2025 | sync (Selenium) | binary-chromedriver patch | yes (WIP) | no | no | maint-mode |
| 4 | [nodriver](https://github.com/ultrafunkamsterdam/nodriver) | 4.6k | May 2026 | async | raw CDP, no WebDriver, `cf_verify()` | yes | no | cookies save/load only | **very active** |
| 5 | [botasaurus](https://github.com/omkarcloud/botasaurus) | 5.6k | Jun 2026 | both | Firefox driver + humanized cursor | yes | decorator `max_retry` | JSON per task | **active** |
| 6 | [camoufox](https://github.com/daijro/camoufox) | 10.4k | Jul 2026 | async (Playwright) | patched Firefox C++ build (canvas/audio/WebGL/fonts/locale) | yes | no | no | **very active** |
| 7 | [puppeteer-extra / playwright-extra](https://github.com/berstend/puppeteer-extra) | 7.4k | Mar 2023 | JS only | modular evasions plugin | yes | no | no | **dormant** |

### Where the subject's stack is strong
- Every layer concerns a different failure mode:
  stealth layer (Cloudflare fingerprinting) +
  `RequestGate` (2.5 s monotonic floor; no peer has pace-shaped
  throttling) + JSONL+fsync+lease-TTL (resumable, multi-process-safe)
  + `reset_every=250` (Playwright-RSS bound; most peers ignore).
- Against FindAGrave's specific load (one record per page, no
  Cloudflare JS challenge every hit), over-engineered in the right
  places and under-engineered nowhere visible.

### Where it is fragile
- **`playwright-stealth` (AtuboDad) frozen since Sep 2023**.
  PyPI moved to Mattwmaster58's v2 — fine refactor, but still
  depends on the same `addInitScript` surface that has been
  losing ground against Cloudflare's `window.chrome.loadTimes` /
  `csi` gaps since 2024.
- **camoufox** (10.4k, Jul 2026) and **nodriver** (4.6k, May 2026)
  patch at the browser layer (C++ build or raw CDP) and are
  demonstrably harder to fingerprint.
- **No recovery once a Cloudflare challenge lands mid-batch** —
  the lease will retry, but the page will still be blocked.
  nodriver/botasaurus expose a `cf_verify()` / humanized-cursor
  recovery path; the subject does not.

### Top improvements
1. **Swap the stealth layer.** Drop `playwright-stealth` (AtuboDad).
   Replace Playwright-Chrome with **camoufox** for findagrave
   profile-page renders, or switch to **nodriver** if Turnstile
   handling is needed. Both are actively maintained and patch at
   the browser layer, not the JS layer.
2. **Promote `RequestGate` + JSONL lease scheduler to a reusable
   module.** They are the genuinely differentiated parts of the
   subject; they would slot cleanly into botasaurus or nodriver
   as a small adapter.
3. **Add a `cf_verify()` fallback or humanized-cursor path** like
   nodriver/botasaurus, gated on 403/503 from the gate. A
   one-shot humanized re-challenge per session closes the gap.

---

## Axis 3 — Local-first blackboard / scheduler architectures

| # | Name | Stars | Last Activity | Durable queue | Leases | Dedup | Projection | No-broker | Complexity |
|---|---|---:|---|---|---|---|---|---|---|
| 1 | **FindAGraveHelper** (subject) | 0 | Jul 2026 | SQLite-WAL (in-process) | 60 s TTL, 3-attempt → BLOCKED | SHA-256 of payload tuple | Post-pass `ProjectionBuilder → state.jsonl` | ✅ | Low |
| 2 | [langroid](https://github.com/langroid/langroid) | 4.1k | Jul 2026 | None (LLM chat graph) | None (LLM turn-bound) | None | None | ✅ | High (Pydantic v2) |
| 3 | [spotify/luigi](https://github.com/spotify/luigi) | 18.7k | Jul 2026 | Central scheduler + target store (HDFS/S3/…) | None (worker-poll) | Target output existence | None (file outputs) | ❌ | Med |
| 4 | [PrefectHQ/prefect](https://github.com/PrefectHQ/prefect) | 23.5k | Jul 2026 | Server/Cloud (Postgres/SQLite) | Lease via work-queue claim | Task run ID + cache keys | Results in DB; flows | ❌ | High |
| 5 | [dagster-io/dagster](https://github.com/dagster-io/dagster) | 15.9k | Jul 2026 | Run DB + asset materialization | Run-level + asset checks | Asset partition keys | Asset catalog = first-class | ❌ | Very high |
| 6 | [temporalio/sdk-python](https://github.com/temporalio/sdk-python) | 1.1k | Jul 2026 | Temporal server (Cassandra/Postgres) | Activity heartbeats + start-to-close | Workflow ID | Event history + replay | ❌ | Very high |
| 7 | [Bogdanp/dramatiq](https://github.com/Bogdanp/dramatiq) | 5.3k | (active) | RabbitMQ/Redis broker | None (consumer ack) | Message ID | None | ❌ | Med |
| 8 | [coleifer/huey](https://github.com/coleifer/huey) | 6.0k | Jul 2026 | Redis/Postgres/SQLite/file | None (consumer-claim) | Task ID | None | ⚠️ broker-or-sqlite | Low |
| 9 | [pyeventsourcing/eventsourcing](https://github.com/pyeventsourcing/eventsourcing) | 1.7k | active | Application store (any DB) | None | Aggregate IDs | First-class `Projection` | ✅ | Med |

### Where the subject's architecture is distinctive
- Most architecturally aligned with the **classical blackboard
  literature** (Hayes-Roth 1985) of any modern Python peer.
- No peer combines:
  - **(a)** engine-agnostic KS adapters that volunteer via
    `eligible_work_kinds`,
  - **(b)** deterministic observation IDs derived from a
    payload hash,
  - **(c)** post-pass-only projection that reads observations
    without mutating canonical rows.
- **langroid** shares the in-process / no-broker property, but
  coordinates by message-passing between LLM agents, not a shared
  blackboard with lease-TTL recovery.
- **eventsourcing** library has the closest analogue to the
  subject's `ProjectionBuilder`, but serves an event-sourced
  aggregate rather than an opportunistic observation stream.

### Where peers beat it
- **Temporal** beats the lease model with **heartbeats + workflow
  replay** — recovery is automatic across crashes, not
  60-s-window-dependent.
- **Prefect + Dagster** provide **first-class lineage** (task
  runs ↔ assets) that the state.jsonl + RunAuditLog pairing
  approximates but doesn't enforce.
- **Luigi's file-target model** gives trivial idempotency
  ("output exists?") that beats a SHA-256-hash scheme for
  file-shaped outputs.
- **eventsourcing's aggregate-IDs** beat the 6-tuple hash for
  record-keyed dedup.
- Every peer *except* langroid, eventsourcing, and the subject
  requires a broker/server — the exact axis the subject
  optimized for. Rejecting dramatiq/huey was correct (per
  `docs/research/runner-audit.md`).

### Top improvements
1. **Add a heartbeat field** to `WorkItem.lease_expires_at` and
   write it on a background thread inside `invoke()`. Turns the
   60 s lease from a fixed budget into a signalled one, matching
   Temporal's pattern at zero infra cost.
2. **Promote `ProjectionBuilder` to a versioned materialization**
   (`state.v3.jsonl` with schema in `state.schema.json`) so
   view-layer changes are non-breaking the way Dagster's asset
   partitions are.
3. **Factor `KnowledgeSource.invoke` into a `Strategy | Engine`
   dual-protocol** so the existing `Strategy` template DSL can
   be applied at the KS level — closes the last semantic gap
   between the engine-agnostic abstraction and the Blackboard
   dispatch layer, and unlocks cross-engine strategy reuse without
   touching the scheduler.

---

## Overall verdict

### Strengths unique to the subject (or near-unique)
1. **Blackboard + Scheduler + engine-agnostic KS + 13-strategy
   ladder + Cloudflare-aware throttle** as one composition. No
   peer has all four.
2. **`RequestGate` (per-URL monotonic throttle) + JSONL + fsync
   + lease TTL** is genuinely differentiated. None of the
   surveyed stealth frameworks offer pace-shaped throttling or
   durable resume.
3. **Two engines on one pipeline** (FaG + Newspapers.com)
   proving the engine-agnostic abstraction is real, not
   aspirational.
4. **Local-first, no broker.** Rejected all task-queue candidates
   correctly (per `docs/research/runner-audit.md`).
5. **1,358-test pytest suite** with intentional CI gates
   documented as learnings (#91, #92).

### Where peers lead
1. **Stealth layer is the weak link.** camoufox (10.4k) and
   nodriver (4.6k) patch at the browser layer; `playwright-stealth`
   patches at the JS layer. Subject's stealth is the only
   long-frozen dependency in the stack.
2. **No CI badge / no Docker image.** OpenGravestones and graver
   have shipped in default CI for years; the subject's e2e path
   is operator-only.
3. **No open-burial-data export.** Schema.org/Cemetery + WikiTree
   + Wikidata interop is held back by the absence of an export
   module.
4. **Heartbeat-free leases.** Temporal's heartbeats are stronger
   recovery semantics at zero infra cost (just a background
   thread per leased WorkItem).

### Prioritized improvement backlog

| Priority | Effort | Impact | Improvement | Notes |
|---|---|---|---|---|
| 1 | 1-2 days | Medium | **CI/Docker**: GitHub Action + container image with `playwright install chromium` pre-baked; closes the e2e gap from the default-suite learnings (#91, #92). |
| 2 | 1-2 weeks | High | **Stealth swap**: replace `playwright-stealth` (AtuboDad, frozen) with camoufox or nodriver. Closes the strongest fragility point in the stack. |
| 3 | 3-5 days | High | **Open-burial-data export**: `scripts/exports/open_gravestones.py` emitting JSON-LD per Schema.org/Cemetery + Muninn Graves ontology. Unlocks WikiTree/Wikidata interop. |
| 4 | 1-2 weeks | High | **Learned scorer wire-up**: plug `CalibratedClassifier` + `PairwiseWeightLearner` (already exist) into the Blackboard decision path. Raises the 80% cold-start hit-rate. |
| 5 | 1 day | Medium | **Heartbeat leases**: add `lease_expires_at` field to `WorkItem`; background thread renews during `invoke()`. Matches Temporal's pattern at zero infra cost. |
| 6 | 1 day | Medium | **Versioned projection**: `state.v3.jsonl` + `state.schema.json`. View-layer changes become non-breaking. |
| 7 | 1 week | Medium | **Strategy-at-KS dual-protocol**: factor `KnowledgeSource.invoke` to use the existing `Strategy` template DSL. Cross-engine strategy reuse. |

---

## Sources

### Axis 1 — CW genealogy / FaG projects
- doug-foster/Find-a-Grave-Tools: https://github.com/doug-foster/Find-a-Grave-Tools
- mcqueary/graver: https://github.com/mcqueary/graver
- miyakoj/Find-a-Grave-Memorial-Extractor-Browser-Extension-for-Chromium: https://github.com/miyakoj/Find-a-Grave-Memorial-Extractor-Browser-Extension-for-Chromium
- mattprusak/autoresearch-genealogy: https://github.com/mattprusak/autoresearch-genealogy
- OpenGravestones: https://github.com/OpenGravestones/OpenGravestones

### Axis 2 — Stealth frameworks
- AtuboDad/playwright_stealth: https://github.com/AtuboDad/playwright_stealth (dormant since Sep 2023)
- Mattwmaster58/playwright-stealth (PyPI): https://pypi.org/project/playwright-stealth/
- undetected-chromedriver: https://github.com/ultrafunkamsterdam/undetected-chromedriver
- nodriver: https://github.com/ultrafunkamsterdam/nodriver
- botasaurus: https://github.com/omkarcloud/botasaurus
- camoufox: https://github.com/daijro/camoufox
- puppeteer-extra: https://github.com/berstend/puppeteer-extra
- [playwright-stealth-mode in 2026 reference](https://dev.to/vhub_systems_ed5641f65d59/playwright-stealth-mode-in-2026-the-7-patches-that-actually-matter-46bp)

### Axis 3 — Blackboard / scheduler architectures
- langroid: https://github.com/langroid/langroid
- spotify/luigi: https://github.com/spotify/luigi
- PrefectHQ/prefect: https://github.com/PrefectHQ/prefect
- dagster-io/dagster: https://github.com/dagster-io/dagster
- temporalio/sdk-python: https://github.com/temporalio/sdk-python
- Bogdanp/dramatiq: https://github.com/Bogdanp/dramatiq
- coleifer/huey: https://github.com/coleifer/huey
- pyeventsourcing/eventsourcing: https://github.com/pyeventsourcing/eventsourcing
- Temporal lease blog: https://temporal.io/blog/coordinate-access-to-shared-resources-with-a-distributed-lock-built-on-temporal-workflows
- eventsourcing Projection docs: https://eventsourcing.readthedocs.io/en/stable/topics/projection.html
- Subject's own: https://github.com/valueforvalue/FindAGraveHelper

### Internal references
- `docs/research/runner-audit.md` — the runner library survey
- `docs/designs/post-pass-extraction.md` — the 10-slice refactor
- `docs/learnings/2026-07-22-e2e-gt-skip.md` — #91 e2e skip rationale
- `docs/learnings/2026-07-22-real-fag-memory-default-skip.md` — #92
  integration deselect rationale