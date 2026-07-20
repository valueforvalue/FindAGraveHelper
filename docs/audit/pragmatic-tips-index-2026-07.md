# Pragmatic Programmer Tip Index (100 tips)

> **Externalized from [`../agents/pragmatic-principles.md`](../agents/pragmatic-principles.md).**
> The principle spine in §1–§5 of that doc is what agents load
> when designing or reviewing a feature. This file holds the
> **per-tip reference**: every row in §6 (Tip index), §7
> (Summary counts), and §9 (Book chapter → tip cross-reference).
>
> **When to load:** on demand, when checking whether a specific
> commit, behavior, or new pattern is in compliance with the
> canonical book. Not part of the Tier-0 / Tier-1 load.

---

## §6 — Tip index (the 100 tips, by number)

This index is the **operational counterpart** to the principle
spine in §1. Each tip is a concrete behavior; the principle
is the *why* behind the behavior. The principle spine is what
an agent reads when designing a new feature; this index is what
an agent reads when checking whether a specific commit or
behavior is in compliance.

### When to consult this table

- **Slice planning** (per [`feature-protocol.md`](../agents/feature-protocol.md))
  — before shipping a Tier 2 vertical slice, scan the rows for
  any tip whose Principle column matches the slice's primary
  concern. If any row is ⚠️ or ❌ in that area, the slice plan
  needs a regression-test bullet that closes the gap.
- **PR review** — for each modified file, the reviewer reads
  the rows for the spine principles the file touches. A file
  under `internal/db/` triggers §1.1 (DRY) + §1.5 (Design by
  Contract) + §1.11 (Program Deliberately).
- **Retrospective** (post-merge audit cadence, per the
  adopting repo's audit process) — when a bug lands in `main`,
  find the tip row that should have caught it, mark the row
  ❌ or ⚠️, and file a follow-up issue to close the gap.
- **Onboarding a new contributor** — the table is the *single
  document* that names every behavior the repo enforces.
  Reading §1 first (the spine) gives the *why*; reading §6
  second (the index) gives the *what*.

**State legend:**
- ✅ **Enforced** — a [`laws.md`](../agents/laws.md) Law, a tier-1
  `core/*.md` rule, an `../addenda/*` rule, an `issues/*.md`
  template, a `../scripts/*` automation, or a `../templates/*.md.tmpl`
  pins the tip.
- ⚠️ **Partial** — the spirit is satisfied but no written rule,
  OR the rule exists but a recent commit violated it. Cited.
- ❌ **Gap** — the tip is not addressed and would be
  high-leverage to add. A candidate follow-up issue exists.
- ➖ **N/A** — the tip applies to contexts agent-stack does not
  inhabit.

**Principle column** maps the tip to the §1.x section in this
doc that explains the *why*. Tips with a "philosophy / technique"
note in the Principle column are *attitudes* (Ch 1 of the book)
or *techniques* (Ch 3+), not principles per se — they inform
behavior but are not operationalized as a deep-module rule.

**Evidence / how to apply** is the *concrete recipe* column. It
names the repo surface that enforces the tip AND the action the
agent takes. Where the recipe fits in one line, it fits in one
line; where it needs two or three lines (a code snippet, a
step-by-step), the row carries it inline.

The full evidence per tip lives in the source audit at
[`../docs/audit/pragmatic-programmer-audit-2026-07.md`](../docs/audit/pragmatic-programmer-audit-2026-07.md)
(the 100-tip map retained as a historical artifact).

| # | Tip | State | Principle | Evidence / how to apply |
|---|---|---|---|---|
| 1 | Care About Your Craft | ✅ | — (philosophy / technique, not a principle) | [`session-protocol.md`](../agents/session-protocol.md) §"Bias toward action" + §"Proportional depth" + the entire doc-comment floor + [`commit-and-branch.md`](../agents/commit-and-branch.md) §"Push verification" + the CHANGELOG discipline. *How to apply:* read [`AGENTS.md`](../AGENTS.md) first thing in every session; if a session ended without updating the doc when a new pattern emerged, the next session has lost the rule. |
| 2 | Think! About Your Work | ✅ | — (philosophy / technique, not a principle) | [`rpci.md`](../agents/rpci.md) RPCI flow explicitly turns off the autopilot: every Plan has a Critique phase the user signs off on before code lands. *How to apply:* before writing the first line of a slice, write the slice plan (files touched, success criteria, regression net) into the issue body. If you can't write those three things, you haven't thought yet. |
| 3 | You Have Agency | ✅ | — (philosophy / technique, not a principle) | [`rpci.md`](../agents/rpci.md) §C — Critique gate is the operational form. The user has explicit "approve, start" authority over every plan; the agent never starts work without it. *How to apply:* if a slice feels blocked by a missing requirement, surface the decision in `ask_user_question` with 2-4 options, not by stalling. |
| 4 | Provide Options, Don't Make Lame Excuses | ✅ | — (philosophy / technique, not a principle) | [`rpci.md`](../agents/rpci.md) Plan surfaces "decisions to confirm" with options; the user picks, the agent never says "can't be done." *How to apply:* every blocker you hit becomes a 2-4 option question, not a refusal. "Can't do X" → "Can do A, B, or C; which?" |
| 5 | Don't Live with Broken Windows | ✅ | — (philosophy / technique, not a principle) | [`laws.md`](../agents/laws.md) — every Law was earned by a real bug. The universal-laws pattern (re-entry, doc-comment floor, glossary, agent-context files, tier-0 size ceiling) is the operational form. *How to apply:* when a slice ships a backend surface without a UI apply-site, the slice is *not done*. Open a follow-up issue the same commit. |
| 6 | Be a Catalyst for Change | ⚠️ | — (philosophy / technique, not a principle) | agent-stack is *literally* a catalyst (`../scripts/init.sh` + `addenda/` invite contribution + the per-issue feature template). No written rule beyond "ship the follow-up issue in the same commit." *When violated:* a stale doc, an undocumented pattern, or a workaround that nobody proposed a fix for. *How to apply:* when you find a broken window, file the follow-up issue + propose the slice in the same message; don't wait for someone else. |
| 7 | Remember the Big Picture | ✅ | — (philosophy / technique, not a principle) | [`docs-index-scheme.md`](../agents/docs-index-scheme.md) 3-tier progressive-disclosure table is the operational form. Agents know which tier to load for the task. *How to apply:* every session starts by reading the tier table; the 3-tier structure tells you whether to load a doc, just skim it, or skip it entirely. |
| 8 | Make Quality a Requirements Issue | ✅ | — (philosophy / technique, not a principle) | [`issues/feature-template.md`](../issues/feature-template.md) §'Acceptance criteria' makes testability a required bullet; per-addendum quality bar (test floor, smoke probe, adjacent sweep) is the regression net. *How to apply:* the slice plan template makes test + smoke probe mandatory bullets; a plan without them is not a valid plan. |
| 9 | Invest Regularly in Your Knowledge Portfolio | ⚠️ | — (philosophy / technique, not a principle) | [`../docs/learning/README.md`](../docs/learning/README.md) + `../docs/learning/addenda/go-htmx.md` ship per the four-section pattern (mental model, vocabulary, idioms, anti-patterns). No scheduled reading cadence. *When violated:* a new framework or book is added to the stack without a learning doc. *How to apply:* when a new book or framework is added to the stack, add a learning doc that follows the four-section pattern. |
| 10 | Critically Analyze What You Read and Hear | ⚠️ | §2.1 WISDOM | The framework applies this in the "forgo following fads" framing (per §1.3 Reversibility). *When violated:* a "let's rewrite in X" pitch that arrives without a stated problem to solve. *How to apply:* every architecture choice ships with a 1-line problem statement; a pitch without the problem is a red flag. Ask "what bug does this fix?" before adopting. |
| 11 | English is Just Another Programming Language | ✅ | §1.1 DRY | [`glossary-discipline.md`](../agents/glossary-discipline.md) + the 3-tier docs taxonomy. Every doc is reviewed for terminology drift; the "Flagged ambiguities" section is the regression net. *How to apply:* if a term is used in two places, one of them is wrong. Either rename to match the glossary or update the glossary + file the rename in the same commit. |
| 12 | It's Both What You Say and the Way You Say It | ✅ | §2.1 WISDOM | [`commit-and-branch.md`](../agents/commit-and-branch.md) §"Commit message shape" mandates 1-3 bullets explaining the *why* + regression net. The CHANGELOG tone is exemplary: long-form bullets explain the *why*, the regression net, and the out-of-scope. *How to apply:* a commit message without the regression net line is incomplete; a CHANGELOG bullet without the *why* is too thin. |
| 13 | Build Documentation In, Don't Bolt It On | ✅ | §1.16 It's All Writing | [`laws.md`](../agents/laws.md) §"Doc comments on exported identifiers" + the 3-tier docs taxonomy + [`../templates/AGENTS.md.tmpl`](../templates/AGENTS.md.tmpl). Every exported identifier ships with a doc comment; every framework URL is a typed call. *When violated:* a new top-level URL string in a templ file (the architecture test fails the build). |
| 14 | Good Design Is Easier to Change Than Bad Design | ✅ | §1.3 Reversibility | [`complexity.md`](../agents/complexity.md) deep-module discipline + per-addendum guard tests are the rule. "Code that's easy to change" lives at the interface, not at the implementation. *How to apply:* a new module lands behind a small facade; the architecture test refuses cross-package deep imports. If your slice needs to reach across 3 packages, the design is wrong; refactor first. |
| 15 | DRY—Don't Repeat Yourself | ✅ | §1.1 DRY | [`glossary-discipline.md`](../agents/glossary-discipline.md) (vocabulary DRY) + [`complexity.md`](../agents/complexity.md) §"Two-adapter rule" (interface DRY) + per-addendum routebuilder + DOM-ID registries (typed-builder DRY). *When violated:* a URL literal in a templ file (caught by the per-addendum guard test); a duplicated kind label across two switch statements (caught by the per-package snapshot test); a vocabulary term with two spellings (caught by the glossary review). *How to apply:* before writing the second copy, grep for the first; if the first exists, refactor before duplicating. |
| 16 | Make It Easy to Reuse | ✅ | §1.1 DRY | The per-addendum design-system primitives (Button, Card, Pill, EmptyState, Field, Toast, Foldout in `../addenda/go-htmx.md`; analogous in other addenda) are the single source for visual patterns; per-component snapshot tests pin byte-stable output. *How to apply:* new visual pattern → new primitive in the per-addendum components directory + per-component snapshot test. A templ file with a hand-rolled class string is a *new primitive waiting to be extracted*. |
| 17 | Eliminate Effects Between Unrelated Things | ✅ | §1.2 Orthogonality | [`complexity.md`](../agents/complexity.md) deep-module discipline + the per-stack forbidden-import test pattern (e.g. `../addenda/go-htmx.md` HTMX-specific guard tests). *How to apply:* a new import that crosses a boundary fails the architecture test. Fix: move the type to a shared package or expose a facade method. |
| 18 | There Are No Final Decisions | ✅ | §1.3 Reversibility | [`commit-and-branch.md`](../agents/commit-and-branch.md) §"Branch policy" supports both single-branch and three-branch models. Releases tag the merge commit on the integration branch; rollbacks promote an older `stable` tag. *When violated:* a direct push to `main` or `stable` (rejected by branch protection); a non-reversible migration without a downgrade SQL path (rejected by the migrations review). |
| 19 | Forgo Following Fads | ⚠️ | §1.3 Reversibility | Implicit in the stack choices (no React, no ORM, no microservices — `addenda/` invites per-stack extension but doesn't mandate any of them) but no written policy. *When violated:* a "rewrite in [framework]" pitch that arrives without a 1-line problem statement. *How to apply:* the architecture choices are listed in [`adr-discipline.md`](../agents/adr-discipline.md); a new framework needs its own ADR with the alternatives considered and the rejected option's rationale. |
| 20 | Use Tracer Bullets to Find the Target | ✅ | §1.4 Tracer Bullets | The `tracer-bullets` skill (auto-loaded) + [`feature-protocol.md`](../agents/feature-protocol.md) §"Tracer bullets" + the Tier 1/2/3 commit rule. *How to apply:* every Tier 2 vertical slice is a tracer bullet. The slice's RED test is the "fires" check. If the bullet misses (the test is hard to write or passes for the wrong reason), the next slice adjusts the aim. |
| 21 | Prototype to Learn | ⚠️ | — (philosophy / technique, not a principle) | `.scratch/` is the prototype playground (Python scripts, MCP probes) and `repl` skill is a scratch tool. *When violated:* a 200-line prototype landed in `internal/` because nobody created the `.scratch/` shim first. *How to apply:* if the slice's success criteria includes "learn whether X is feasible," the prototype lives in `.scratch/`; only the proven mechanism ports to `internal/`. |
| 22 | Program Close to the Problem Domain | ✅ | — (philosophy / technique, not a principle) | [`complexity.md`](../agents/complexity.md) §"Deep-module discipline" mandates domain-shaped public surfaces. [`feature-protocol.md`](../agents/feature-protocol.md) §Module discipline: DTO names should read like the requirement ("Person Record", "Display ID"), not like the implementation. *When violated:* an `internal/<domain>/<domain>_infra.go` file with no domain terms in the type names. |
| 23 | Estimate to Avoid Surprises | ⚠️ | — (philosophy / technique, not a principle) | [`rpci.md`](../agents/rpci.md) Plan includes "files touched, success criteria, regression net" but no time estimate. The "Bias toward action" rule absorbs this. *When violated:* a slice ships that touches 15+ files when the plan estimated 3. *How to apply:* if a slice's actual footprint is 5x the estimate, the slice is doing two things; split it. |
| 24 | Iterate the Schedule with the Code | ➖ | — (philosophy / technique, not a principle) | N/A. Framework ships docs + scripts; no schedule to iterate. |
| 25 | Keep Knowledge in Plain Text | ✅ | — (philosophy / technique, not a principle) | Every config in agent-stack is plain text (Markdown, shell, JSON in `templates/`). No binary configs. |
| 26 | Use the Power of Command Shells | ✅ | — (philosophy / technique, not a principle) | `../scripts/*.sh` (`backfill-labels.sh`, `check-core-stack-agnostic.sh`, `check-mutations.sh`, `check-security.sh`, `dedupe-skills.sh`, `init.sh`, `sync-labels.sh`) + `../scripts/build_tip_index.py` + `../scripts/splice_tip_index.py` + the per-addendum Makefile / `package.json` targets. *How to apply:* if a step needs to run twice, it belongs in a script + a Makefile target. Manual repetition is the violation. |
| 27 | Achieve Editor Fluency | ➖ | — (philosophy / technique, not a principle) | N/A. Agent-context; not a framework concern. |
| 28 | Always Use Version Control | ✅ | — (philosophy / technique, not a principle) | The entire branching model in [`commit-and-branch.md`](../agents/commit-and-branch.md). Every change goes through git; the framework's own commits follow Conventional Commits. *How to apply:* every change goes through git; every commit has a message; every PR has a body. A change outside git is not a change. |
| 29 | Fix the Problem, Not the Blame | ⚠️ | — (philosophy / technique, not a principle) | Implicit in CHANGELOG tone ("two compounding bugs in X" — no person named) but no stated rule. *When violated:* a commit message names a person ("@alice broke this"). *How to apply:* a fix commit names the *bug*, the *root cause*, and the *regression net*. Person names never appear in commit messages. |
| 30 | Don't Panic | ➖ | — (philosophy / technique, not a principle) | N/A. No incident-response flow at framework level. |
| 31 | Failing Test Before Fixing Code | ✅ | — (philosophy / technique, not a principle) | [`tdd.md`](../agents/tdd.md) red-green-refactor protocol is the operational form. Step 1 ("RED") explicitly: write the failing test first. *How to apply:* the first commit in a bug-fix slice is the failing test; the second is the fix that turns it green. A fix without a preceding failing test is a Tier 3 maintenance commit, not a Tier 2 vertical. |
| 32 | Read the Damn Error Message | ✅ | §1.6 Dead Programs | [`tdd.md`](../agents/tdd.md) §"The failure modes TDD prevents" — failure class #1 (Invoker wiring) mandates asserting the response shape AND the post-click URL AND the DOM state (not "we got an error somewhere"). *How to apply:* a panic with a clear message is the signal; a swallowed panic with a generic toast is the violation. |
| 33 | "select" Isn't Broken | ✅ | §1.6 Dead Programs | [`bug-patterns.md`](../agents/bug-patterns.md) §'Debugging workflow' step 5 pins a five-step 'don't blame the framework by default' checklist. *How to apply:* before patching around a framework / compiler / runtime behavior, prove it. The default assumption is *your code is wrong*; the framework is right ~99% of the time. |
| 34 | Don't Assume It—Prove It | ✅ | §1.6 Dead Programs | [`tdd.md`](../agents/tdd.md) §"What's the seam?" + the per-layer recipes (handler test, smoke probe, migration test) mandate asserting the actual state, not the expected state. *How to apply:* a function's doc-comment carries the per-iter SQL footprint (count of SELECTs, INSERTs, transactions); the test asserts the footprint, not just the output. |
| 35 | Learn a Text Manipulation Language | ➖ | — (philosophy / technique, not a principle) | N/A at the framework level. Per-adopter concern. |
| 36 | You Can't Write Perfect Software | ✅ | §1.5 Design by Contract | [`laws.md`](../agents/laws.md) §"No unguarded re-entrant UI calls" + §"Tier-0 docs have a size ceiling" are earned-by-real-bug laws. *How to apply:* every error path either crashes early or surfaces a clear toast; a silent fallback (returning `nil, nil` on error, swallowing a panic) is the violation. |
| 37 | Design with Contracts | ✅ | §1.5 Design by Contract | [`tdd.md`](../agents/tdd.md) §"Contract touch" is the prospective function- and boundary-contract rule; per-addendum architecture tests enforce package contracts. *How to apply:* every new or materially changed public seam documents relevant caller obligations, observable guarantees, failure/state semantics, and retry/concurrency behavior; its RED test proves those claims. Skip mechanical edits and untouched code. Prefer types, constraints, typed errors, and tests over generic runtime assertion helpers. |
| 38 | Crash Early | ✅ | §1.5 Design by Contract | [`laws.md`](../agents/laws.md) §"No unguarded re-entrant UI calls" — crashing early preserves the UI thread. Per-addendum: the typed-attribute swap allowlist (e.g. `htmxattr.Mux` in Go) panics at render time on an invalid value. *How to apply:* an unreachable code path should panic, not silently return. The panic is the agent's "the world is broken" signal; swallowing it is the violation. |
| 39 | Use Assertions to Prevent the Impossible | ✅ | §1.5 Design by Contract | Per-addendum typed builders + DOM-ID registries prevent invalid states at construction time. The doc-comment floor enforces the assertion-via-documentation pattern. *How to apply:* prefer types, builders, database constraints, validation, and typed errors. Use a runtime panic only for a developer-created impossible state; never panic for ordinary user input, recoverable I/O, or third-party failure. |
| 40 | Finish What You Start | ⚠️ | — (philosophy / technique, not a principle) | The pattern lives in adopting repos via `defer` (Go) / `try/finally` (Python) / effect-cleanup (React). [`session-protocol.md`](../agents/session-protocol.md) names the principle implicitly but no framework-level guard test pins it. *When violated:* a resource opened without a defer / unsubscribe / cleanup. *How to apply:* every `Open()` / `Lock()` / goroutine launch is paired with `defer Close()` / `defer Unlock()` / a context-aware wait. |
| 41 | Act Locally | ⚠️ | — (philosophy / technique, not a principle) | [`complexity.md`](../agents/complexity.md) §"Two-adapter rule" prescribes local interfaces, but no named rule for "locality of state." Implicit in the deep-module discipline (variables live at the function or module scope, not at the package scope). *When violated:* a package-level mutable variable. *How to apply:* a `var foo = ...` at the package level is the violation; pass the value into the function or hold it on the per-process struct. |
| 42 | Take Small Steps—Always | ✅ | §1.10 Take Small Steps | [`rpci.md`](../agents/rpci.md) §I — Implement: "the first slice is the only slice that runs in the same session." Fresh-context-per-slice is the operational form. *How to apply:* a slice plan that lists >5 files touched is doing two things; split it. |
| 43 | Avoid Fortune-Telling | ✅ | — (philosophy / technique, not a principle) | [`session-protocol.md`](../agents/session-protocol.md) §"YAGNI" + [`complexity.md`](../agents/complexity.md) §"Strategic programming framework" + [`feature-protocol.md`](../agents/feature-protocol.md) §"Two-adapter rule". *When violated:* a slice adds an interface or a config field "for the future." *How to apply:* the rule is "no feature PR ships a parameter that no caller passes." Delete the parameter or file the follow-up issue. |
| 44 | Decoupled Code Is Easier to Change | ✅ | §1.7 Law of Demeter | [`complexity.md`](../agents/complexity.md) deep-module discipline is the operational form. The DTO-at-the-seam rule pins the per-package decoupling. *How to apply:* a chain like `result := a.B().C().D()` is a Demeter violation; pass the value or expose a facade method. |
| 45 | Tell, Don't Ask | ⚠️ | §1.7 Law of Demeter | [`feature-protocol.md`](../agents/feature-protocol.md) §"Module discipline — service is the seam" prescribes telling the service to do the work, not asking the model for its data. *When violated:* a templ file imports `internal/<pkg>` directly instead of the service's DTO. *How to apply:* the seam is the service interface; expose a DTO, not the persistence struct. |
| 46 | Don't Chain Method Calls | ➖ | §1.7 Law of Demeter | N/A as a stated rule; [`complexity.md`](../agents/complexity.md) deep-module discipline covers the same concern implicitly. |
| 47 | Avoid Global Data | ⚠️ | §1.2 Orthogonality | Per-adopter concern. [`complexity.md`](../agents/complexity.md) prescribes a model-without-UI-imports boundary; the "no package-level mutable state" rule is implicit in the deep-module discipline. *When violated:* a `var foo = make(...)` at package level. *How to apply:* hold the value on the per-process struct; pass the struct pointer into every consumer. |
| 48 | If It's Important Enough To Be Global, Wrap It in an API | ✅ | §1.2 Orthogonality | `../addenda/go-htmx.md` §"Stack laws" gives the worked example: `(*App).guardedSaveFileDialog` wraps the dangerous thing (the OS dialog) in an API that adds re-entry protection. *How to apply:* if the global is unavoidable (a system handle, a process-wide config), wrap it in a struct method that adds the safety invariant. |
| 49 | Programming Is About Code, But Programs Are About Data | ✅ | §1.2 Orthogonality | [`complexity.md`](../agents/complexity.md) §"Deep-module discipline" prescribes DTOs as the cross-boundary value type. The audit-probe pattern (per the adopting repo's audit chain) asserts on data shape, not on code paths. *How to apply:* a handler that returns a service struct is the violation; the handler returns a viewmodel DTO, the viewmodel maps the service struct. |
| 50 | Don't Hoard State; Pass It Around | ⚠️ | §1.2 Orthogonality | [`code-changes.md`](../agents/code-changes.md) prescribes arguments over global state implicitly, but no named rule. *When violated:* a function reads from a package-level variable instead of taking the value as a parameter. *How to apply:* function arguments over package-level state; the per-addendum `[data-*]` initializer pattern is the recent worked example. |
| 51 | Don't Pay Inheritance Tax | ➖ | §1.2 Orthogonality | N/A as a framework rule; the type-system-agnostic stance means each adopter inherits whatever their language provides. Composition is the only path; the rule is implicit and trivially satisfied by every framework binding. |
| 52 | Prefer Interfaces to Express Polymorphism | ⚠️ | §1.2 Orthogonality | Go interfaces are the operational form (per `../addenda/go-htmx.md` worked examples): services expose behavior through interface types, not concrete structs. *When violated:* a consumer that imports the concrete service struct. *How to apply:* the consumer imports an interface, the framework binding wires the concrete. |
| 53 | Delegate to Services: Has-A Trumps Is-A | ➖ | §1.2 Orthogonality | N/A in Go (and most agent-stack target languages). Composition is the only path; the rule is implicit and trivially satisfied by every framework binding. Other languages with inheritance (Python, TS) get this for free by the deep-module discipline ([`complexity.md`](../agents/complexity.md) §"Decomplect"). |
| 54 | Use Mixins to Share Functionality | ➖ | — (philosophy / technique, not a principle) | N/A in Go (no mixins). Embedding structs is the closest analog; the per-addendum dialog-guard mutex and the per-handler `inFlight` pattern (per `../addenda/go-htmx.md` §"Stack laws") are embedded once and reused. *When violated:* a struct copy-pastes a method instead of embedding the type that owns it. |
| 55 | Parameterize Your App Using External Configuration | ✅ | — (philosophy / technique, not a principle) | The Makefile / `package.json` + `.github/workflows/*.yml` + `../templates/CONTEXT.md.tmpl` are the build-time config. Per-adopter external config (env vars, settings files, `local_settings` analog) is a per-stack pattern. *How to apply:* a constant in source code that the user might want to change is the violation; move it to a config file or to the Makefile. |
| 56 | Analyze Workflow to Improve Concurrency | ✅ | §1.9 Temporal Coupling | The per-addendum export flow (PDF / JSON / archive) is jobs-based; the user gets a toast + the jobs page updates in parallel. The toast-header contract decouples the click from the work. *How to apply:* a handler that does the work inline (blocks the response for >500ms) is the violation; move the work to a job, return a 202 with a job ID. |
| 57 | Shared State Is Incorrect State | ✅ | — (philosophy / technique, not a principle) | The dialog-guard mutex + the per-process struct pattern (e.g. Wails `App`, Electron main, Tauri main) + the per-job worker context. [`laws.md`](../agents/laws.md) §"No unguarded re-entrant UI calls" is the operational form. *How to apply:* a goroutine / handler / worker that reads/writes a package-level variable is the violation; pass the per-process struct pointer, the worker owns no state of its own. |
| 58 | Random Failures Are Often Concurrency Issues | ✅ | — (philosophy / technique, not a principle) | Per-addendum race-stress workflow (e.g. `audit/race-stress.yml`) + per-adopter property-test gate (e.g. `internal/dates` dates property test). [`bug-patterns.md`](../agents/bug-patterns.md) §"Concurrency / dependency correctness" lists the AI-amplification evidence. *How to apply:* a flaky test is concurrency; run with `-race` (Go) or the language's race detector before assuming the test is broken. |
| 59 | Use Actors For Concurrency Without Shared State | ⚠️ | — (philosophy / technique, not a principle) | The per-process struct (Wails `App`, Electron main, Tauri main) is passed by reference; not technically an actor. The per-addendum `jobs.Start` pattern (e.g. `internal/jobs/jobs.go` in the Go addendum) is the closest operational form. *When violated:* a goroutine / worker that mutates a value owned by the caller. *How to apply:* the rule is "the goroutine owns its state; the caller passes inputs and reads outputs through channels or a return-only interface." |
| 60 | Use Blackboards to Coordinate Workflow | ➖ | §1.9 Temporal Coupling | N/A. Single-user single-process apps; no blackboard pattern. |
| 61 | Listen to Your Inner Lizard | ⚠️ | §1.9 Temporal Coupling | Implicit. The "agent inner lizard" surfaced in the over-decomposition anti-pattern ([`commit-and-branch.md`](../agents/commit-and-branch.md) §"Anti-patterns"). [`rpci.md`](../agents/rpci.md) §I — Implement mandates fresh-context-per-slice. *When violated:* the slice plan says "I'll figure out the shape as I go." *How to apply:* if a plan feels wrong, the plan is wrong; surface the concern in the slice plan's "Principle warnings" block. |
| 62 | Don't Program by Coincidence | ✅ | §1.11 Program Deliberately | The per-adopter property-test gate (e.g. `internal/dates` dates property test) is the operational form. The CHANGELOG entry tone is "root cause: X; fix: Y" — never "happened to work." [`rpci.md`](../agents/rpci.md) §P — Plan mandates "Decisions to confirm" surfaced explicitly. *When violated:* a commit message that doesn't explain *why* the fix works. *How to apply:* the slice plan's "regression net" line names the test that proves the fix; a fix without that line is coincidence. |
| 63 | Estimate the Order of Your Algorithms | ⚠️ | §1.12 Algorithm Speed | The per-addendum stress test (e.g. `TestStressEventAttachDetachRoundTrip` in the Go addendum) per-iter SQL footprint is the closest form. Not a stated rule for non-DB code paths. *When violated:* a function in the model's heavy paths (DB queries, batch ops, background jobs) whose doc-comment has no SQL footprint. *How to apply:* the doc-comment lists "O(N) reads, O(1) writes"; a doc-comment without the footprint is incomplete. |
| 64 | Test Your Estimates | ✅ | §1.12 Algorithm Speed | Per-addendum stress-test directory (e.g. `tools/tune/stress/`) + per-adopter race-stress workflow (e.g. `.github/workflows/race-stress.yml`). The race-detector step is the live regression net that catches drift between the estimate and reality. *How to apply:* every slice that touches the model's heavy paths runs the stress suite locally before the PR opens. |
| 65 | Refactor Early, Refactor Often | ✅ | §1.13 Refactoring | [`complexity.md`](../agents/complexity.md) is the operational form. The per-adopter Event Records refactor (sibling-table rename) is the canonical worked example. *How to apply:* the slice plan's "When to refactor" checklist (5 triggers: DRY violation, non-orthogonal, knowledge improved, requirements evolve, performance) — a slice that hits one trigger files the refactor as a sibling issue. |
| 66 | Testing Is Not About Finding Bugs | ✅ | §1.13 Refactoring | The audit cadence is the operational form. Per-adopter audit cycles (e.g. the DixieData #531, #539, #540, #542 cluster) each surfaced a *class* of bug the tests themselves couldn't catch. *How to apply:* the audit probe (Playwright or analog) is the second test surface; a slice that passes unit tests but fails the smoke probe is incomplete. |
| 67 | A Test Is the First User of Your Code | ✅ | §1.13 Refactoring | [`tdd.md`](../agents/tdd.md) Step 1 is "RED: write the failing test first." Per-addendum RED + GREEN shipping as a single reviewable commit is the worked example. *How to apply:* the slice plan's first commit is the failing test; the second is the fix. A slice with no RED commit is not TDD. |
| 68 | Build End-To-End, Not Top-Down or Bottom Up | ✅ | §1.4 Tracer Bullets | RPCI tracer-bullet slice 1 is the operational form. Every Tier 2 vertical slice crosses every layer (templ + htmx + JS + Go handler + DB). *When violated:* a "backend slice" that ships the handler but no UI, or a "frontend slice" that ships the templ but no handler. *How to apply:* the slice plan template requires both the apply-site URL and the smoke probe bullet; a plan without both is not Tier 2. |
| 69 | Design to Test | ✅ | §1.11 Program Deliberately | [`../addenda/go-htmx.md`](../addenda/go-htmx.md) HTMX-specific guard tests (architecture test + orphan-handler probe + smoke-probe per-apply-site contract) — three independent test surfaces. *How to apply:* a new handler without an audit probe entry is the violation; the audit probe is the test that catches the "handler returns 200 but renders nothing" bug class. |
| 70 | Test Your Software, or Your Users Will | ✅ | §1.4 Tracer Bullets | The smoke-probe per-apply-site contract (per [`feature-protocol.md`](../agents/feature-protocol.md) §"Backend-first law" + [`tdd.md`](../agents/tdd.md) §"Per-layer recipes") catches the "shipped but invisible" bug class. *When violated:* a feature ships without the smoke probe bullet; the user finds the bug. *How to apply:* the slice plan template lists smoke probes per apply-site; a missing probe is the violation. |
| 71 | Use Property-Based Tests to Validate Your Assumptions | ✅ | §1.17 Pragmatic Projects | The per-adopter property test (e.g. `internal/dates/dates_property_test.go` using `pgregory.net/rapid` in the Go addendum) is the operational form. Documented in [`tdd.md`](../agents/tdd.md) §"Per-layer recipes." *How to apply:* a function whose doc-comment claims "handles edge cases X, Y, Z" without a property test is the violation; the property test enumerates the input space. |
| 72 | Keep It Simple and Minimize Attack Surfaces | ✅ | — (philosophy / technique, not a principle) | The "no new component primitives" rule from the per-addendum Markdown cheatsheet work is the recent example. [`complexity.md`](../agents/complexity.md) deep-module discipline is the standing operational form. *When violated:* a slice adds a new templ primitive when an existing one (Foldout, Pill, EmptyState) would carry the case. *How to apply:* before adding a new primitive, grep for existing primitives + read the per-addendum components/conventions doc. |
| 73 | Apply Security Patches Quickly | ❌ | — (philosophy / technique, not a principle) | [`../scripts/check-security.sh`](../scripts/check-security.sh) template ships, but no per-addendum CI workflow runs `govulncheck` or `gosec` on a cadence inside the framework itself. Deps are updated when a PR forces it, not on a schedule. *Open gap:* add `govulncheck ./...` to a weekly workflow; add `gosec ./...` to the audit chain. *How to apply until then:* `go list -m -u all` every Friday; file a follow-up issue per dependency that has a CVE. |
| 74 | Name Well; Rename When Needed | ⚠️ | — (philosophy / technique, not a principle) | The glossary tier-2 rename pattern (per [`glossary-discipline.md`](../agents/glossary-discipline.md) §"Renaming a term") is the canonical example. *When violated:* a new type name that's a synonym for an existing one ("Worker" + "JobRunner" + "TaskProcessor" in the same package). *How to apply:* the slice plan's "files touched" line lists the new name; if the name is a synonym, rename one of them in the same slice. |
| 75 | No One Knows Exactly What They Want | ✅ | — (philosophy / technique, not a principle) | RPCI: "Plan → Critique" with explicit user gate. The "the user is the chat" capture rule in [`session-protocol.md`](../agents/session-protocol.md) §"Capturing decisions". *How to apply:* a slice plan that ships without a user sign-off is the violation; the Plan phase ends only when the user types "approved". |
| 76 | Programmers Help People Understand What They Want | ✅ | — (philosophy / technique, not a principle) | The slice plan + apply-sites checklist in every feature issue ([`issues/feature-template.md`](../issues/feature-template.md)) is the operational form. The user sees the *full shape* of the change before code lands. *How to apply:* the slice plan template lists the apply-sites (which pages the change touches) and the smoke probe; if either is missing, the user can't visualize the change. |
| 77 | Requirements Are Learned in a Feedback Loop | ✅ | — (philosophy / technique, not a principle) | RPCI's "fresh context per slice" ([`rpci.md`](../agents/rpci.md) §I) is the strongest form. The next session picks up the new state and refines. *When violated:* a slice ships with a "complete" spec that was never re-validated. *How to apply:* every slice ends with a `make freshness` + a per-addendum audit run; the next session's slice plan re-reads the previous slice's CHANGELOG bullet and asks "does this still match what the user said?" |
| 78 | Work with a User to Think Like a User | ⚠️ | — (philosophy / technique, not a principle) | Implicit in the user's "go ahead and tackle X" pattern, but no stated cadence. The per-adopter audit cycle is the closest scheduled form. *When violated:* a slice ships without the user manually clicking through the change on a real archive. *How to apply:* the slice plan's "Verification" line lists the manual click-through; a slice without it is incomplete. |
| 79 | Policy Is Metadata | ✅ | §1.8 Metaprogramming | The per-addendum DOM-ID registry (e.g. `internal/uiids` in Go) + the architecture-test forbidden-import map + the linter rule files (e.g. `.mutesting.yaml`) are the operational form. Policy lives in data, not code. *When violated:* a hardcoded list of valid swap targets in the templ layer (the data should live in the registry). *How to apply:* the rule is "if a value appears in 3+ places, it lives in a registry." |
| 80 | Use a Project Glossary | ✅ | §1.8 Metaprogramming | The project glossary (typically `CONTEXT.md` at the repo root, per [`glossary-discipline.md`](../agents/glossary-discipline.md)) is the single source. The "Flagged ambiguities" section is the regression net for vocabulary drift. *How to apply:* a new term in a doc or comment that isn't in the glossary is the violation; add the term + the `_Avoid_` list to the glossary in the same commit. |
| 81 | Don't Think Outside the Box—Find the Box | ✅ | — (philosophy / technique, not a principle) | [`complexity.md`](../agents/complexity.md) §"Strategic programming framework" + [`rpci.md`](../agents/rpci.md) §"Cutting the Gordian Knot" (the 6-question checklist per §2.4). *How to apply:* §2.4 is the 6-question checklist; a slice that answers "yes" on Q6 ("don't have to do it at all") files the abandonment as a sibling issue. |
| 82 | Don't Go into the Code Alone | ⚠️ | — (philosophy / technique, not a principle) | Implicit (the user + agent pairing) but no stated rule. The PR body + the slice plan review are the closest form. *How to apply:* a slice that ships without a PR description is the violation; the PR body is the conversation that catches the "you missed X" finding. |
| 83 | Agile Is Not a Noun; Agile Is How You Do Things | ➖ | — (philosophy / technique, not a principle) | N/A. (Solo / small-team framework; no team-level agile ceremony. The *spirit* is satisfied by the slice cadence + the "ship the smallest useful unit" discipline.) |
| 84 | Maintain Small Stable Teams | ➖ | — (philosophy / technique, not a principle) | N/A. Solo / small-team framework. |
| 85 | Schedule It to Make It Happen | ⚠️ | §1.15 Ubiquitous Automation | The `make freshness` gate (per [`commit-and-branch.md`](../agents/commit-and-branch.md) §"Push verification") + the per-PR CI + the per-addendum weekly cron are the closest form. But "scheduled reflection / learning" is not yet on the calendar. *When violated:* a quality improvement ships behind a feature because nobody scheduled the work. *How to apply:* the slice plan template lists a "Cadence" line; a cadence without a calendar entry is the violation. |
| 86 | Organize Fully Functional Teams | ➖ | §1.15 Ubiquitous Automation | N/A. |
| 87 | Do What Works, Not What's Fashionable | ⚠️ | — (philosophy / technique, not a principle) | Implicit in the architecture choices (no React, no ORM, no microservices — `addenda/` invites per-stack extension without mandating any of them). No stated policy. *When violated:* a "rewrite in [framework]" pitch without a 1-line problem statement. *How to apply:* the architecture choices are listed in [`adr-discipline.md`](../agents/adr-discipline.md) + the adopting repo's `../docs/adr/`; a new framework needs its own ADR with the alternatives considered and the rejected option's rationale. |
| 88 | Deliver When Users Need It | ✅ | — (philosophy / technique, not a principle) | The Tier 3 apply-site rule + the slice-1-only-per-session rule = ship the smallest useful unit as fast as possible. *When violated:* a 2-week polish cycle that ships nothing. *How to apply:* the slice plan's "Verification" line lists the manual click-through; the slice ships when the click-through is green. |
| 89 | Use Version Control to Drive Builds, Tests, and Releases | ✅ | — (philosophy / technique, not a principle) | The per-adopter `.github/workflows/{build,test,audit,race-stress}.yml` are the operational form. Every PR triggers the full chain. *When violated:* a manual build step that runs outside CI. *How to apply:* the workflow YAML files are the source of truth; if a step isn't in a workflow, it doesn't run. |
| 90 | Test Early, Test Often, Test Automatically | ✅ | §1.15 Ubiquitous Automation | Per-PR + per-push + weekly race-stress + per-promotion freshness. *How to apply:* a slice that ships without a CI-green check is the violation; the PR is not mergeable until the green check is in the PR body's status line. |
| 91 | Coding Ain't Done 'Til All the Tests Run | ✅ | §1.15 Ubiquitous Automation | The "RED + GREEN + adjacent-behavior sweep" in [`tdd.md`](../agents/tdd.md) + the package-floor + the smoke-probe per-apply-site contract. *When violated:* a slice ships with one passing test + one skipped test + one failing test. *How to apply:* the slice's PR description lists every test status; a slice without the full matrix is not mergeable. |
| 92 | Use Saboteurs to Test Your Testing | ❌ | — (philosophy / technique, not a principle) | No mutation testing. [`../scripts/check-mutations.sh`](../scripts/check-mutations.sh) template ships the dispatch logic but no framework package runs it. *Open gap:* add a mutation testing step to the audit chain (e.g., `go-mutesting` for Go, `stryker` for JS). *How to apply until then:* every PR review asks "does this test actually catch the bug it's named for?"; if the test is "expect sum of [1,2] == 3," the test is too trivial to trust. |
| 93 | Test State Coverage, Not Code Coverage | ⚠️ | — (philosophy / technique, not a principle) | The smoke probes assert state (response shape, URL, DOM) not just code paths. But there is no coverage metric on the state surface yet. *When violated:* a test that asserts the handler returns 200 but never reads the response body. *How to apply:* the per-adopter audit probe template asserts the full page state; a probe that asserts only the status code is incomplete. |
| 94 | Find Bugs Once | ✅ | §1.15 Ubiquitous Automation | Every `fix:` commit in CHANGELOG grows a regression test. The per-adopter `fix:` commits with regression nets in [`bug-patterns.md`](../agents/bug-patterns.md) are the audit trail. *How to apply:* the slice plan's "regression net" line names the test; a fix commit without a regression test name is the violation. |
| 95 | Don't Use Manual Procedures | ✅ | §1.15 Ubiquitous Automation | [`../scripts/init.sh`](../scripts/init.sh) + [`../scripts/backfill-labels.sh`](../scripts/backfill-labels.sh) + [`../scripts/check-core-stack-agnostic.sh`](../scripts/check-core-stack-agnostic.sh) + [`../scripts/check-mutations.sh`](../scripts/check-mutations.sh) + [`../scripts/check-security.sh`](../scripts/check-security.sh) + [`../scripts/dedupe-skills.sh`](../scripts/dedupe-skills.sh) + [`../scripts/sync-labels.sh`](../scripts/sync-labels.sh) + the per-addendum Makefile targets automate the build + probe chain. *When violated:* a step in the README that says "run X then Y then Z." *How to apply:* every multi-step procedure belongs in a script + a Makefile target; a README without a script is the violation. |
| 96 | Delight Users, Don't Just Deliver Code | ⚠️ | §1.17 Pragmatic Projects | [`session-protocol.md`](../agents/session-protocol.md) §"Bias toward action" + [`feature-protocol.md`](../agents/feature-protocol.md) §"Apply sites" carry the tip. No formal "delight" rule ships at the framework level; the per-addendum docs carry the worked examples. *When violated:* a slice ships the minimum required by the spec and nothing else. *How to apply:* the slice plan's "Verification" line lists the manual click-through; a click-through that ends with "works as specified" but no extra good moment is the violation. |
| 97 | Sign Your Work | ✅ | — (philosophy / technique, not a principle) | The CHANGELOG fixship-by-fixship attribution is the operational form. The "Ticket close-out law" in [`feature-protocol.md`](../agents/feature-protocol.md) requires the commit hash + verification output + acceptance criteria on every closing commit. *How to apply:* every closing commit ends with a `Verification:` block that pastes the test output; a closing commit without the block is unsigned. |
| 98 | First, Do No Harm | ✅ | — (philosophy / technique, not a principle) | The dialog-guard Law ([`laws.md`](../agents/laws.md) §"No unguarded re-entrant UI calls") + the "no feature PR ships a backend surface without a UI apply-site" Law ([`feature-protocol.md`](../agents/feature-protocol.md) §"Backend-first law") + the per-iter SQL footprint pattern. *When violated:* a slice that breaks a non-target surface. *How to apply:* the slice plan's "regression net" line lists every adjacent surface the change could touch; a slice without that list is a harm candidate. |
| 99 | Don't Enable Scumbags | ➖ | — (philosophy / technique, not a principle) | N/A. Framework ships engineering tools, not ethics guidance for hiring / customer-interaction surfaces. |
| 100 | It's Your Life. Share it. Celebrate it. Build it. AND HAVE FUN! | ✅ | — (philosophy / technique, not a principle) | The CHANGELOG tone + the "Bias toward action" rule + the prose style of every `core/` doc. The repo is built by humans who care. *How to apply:* when the work feels like a slog, the slog is the signal; surface the concern, ship a smaller slice, take a break. |

## §7 — Summary: the 100 tips in numbers

| State | Count | What it means |
|---|---|---|
| ✅ Enforced | 62 | The repo is in compliance. The principle spine in §1 names the operational form. |
| ⚠️ Partial | 23 | The spirit is satisfied but no written rule. A future commit could regress without the agent noticing. |
| ❌ Gap | 2 | Not addressed. A candidate follow-up issue exists; see §1 in this doc for the principle-level gaps. |
| ➖ N/A | 13 | Doesn't apply (multi-team management, hiring, incident response, etc.). |

The 100-tip audit is a **check**, not a refactor. The principle
spine (§1) is the primary lens for future work; the tip index
(§6, this section) is the primary lens for checking specific
commits against the canonical book.

When a new tip is added to a future edition of the book, append
a row to this index. When a tip's state changes (a new
commit pushes a ⚠️ to ✅ or a ✅ to ⚠️), update the State column.
The index is the **source of truth** for the per-tip state; the
audit doc is the per-tip *evidence*.

---

## §8 — References (companion)

- The companion audit doc:
  [`../docs/audit/pragmatic-programmer-audit-2026-07.md`](../docs/audit/pragmatic-programmer-audit-2026-07.md)
  — the per-tip *evidence* (historical artifact).
- The regenerator:
  [`../scripts/build_tip_index.py`](../scripts/build_tip_index.py)
  — reads the audit doc, writes `.scratch/appendix-final.md`.
  Run after every state change; then run this script to splice.
- The splicer:
  [`../scripts/splice_tip_index.py`](../scripts/splice_tip_index.py)
  — replaces any existing §6 (Tip index) / §7 (Summary) / §8
  (References) in this file with the regenerated content.

---

## §9 — Book chapter → tip cross-reference

The principle spine (§1) is *principle-organized*; the tip index
(§6) is *tip-organized*. Neither is *chapter-organized*. This
appendix maps every sub-section in the book's 9-chapter TOC to
the canonical tip(s) that cover it + the §1.N spine entry that
names the principle. An agent reading a specific chapter section
finds the operational form here.

Source: <https://pragprog.com/titles/tpp20/the-pragmatic-programmer-20th-anniversary-edition/>

### Ch 1 — A Pragmatic Philosophy

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| It's Your Life | #100 | (philosophy) |
| The Cat Ate My Source Code | #4, #29 | (philosophy) |
| Software Entropy | #5 | (philosophy) |
| Stone Soup and Boiled Frogs | #6, #59 | §2.1 (WISDOM), §1.9 (Temporal Coupling) |
| Good-Enough Software | #36, #64 | §1.5 (Design by Contract) |
| Your Knowledge Portfolio | #9 | (philosophy) |
| Communicate! | #10, #11, #12 | §2.1 (WISDOM), §1.16 (It's All Writing) |

### Ch 2 — A Pragmatic Approach

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| The Essence of Good Design | #14 | §1.3 (Reversibility) |
| DRY — The Evils of Duplication | #15, #16 | §1.1 (DRY) |
| Orthogonality | #17 | §1.2 (Orthogonality) |
| Reversibility | #18, #19 | §1.3 (Reversibility) |
| Tracer Bullets | #20 | §1.4 (Tracer Bullets) |
| Prototypes and Post-it Notes | #21 | (philosophy) |
| Domain Languages | #22 | (philosophy) |
| Estimating | #23, #24 | (philosophy) |

### Ch 3 — The Basic Tools

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| The Power of Plain Text | #25 | (philosophy) |
| Shell Games | #26 | §1.15 (Ubiquitous Automation) |
| Power Editing | #27 | (philosophy, agent-context) |
| Version Control | #28 | §1.15 (Ubiquitous Automation) |
| Debugging | #31, #32, #33, #34 | §2.3 (Debugging Checklist), §1.6 (Dead Programs) |
| Text Manipulation | #35 | (N/A, agent-context) |
| Engineering Daybooks | #73 (partial) | §1.16 (It's All Writing — "what assumptions does this PR make?" in slice plan) |

### Ch 4 — Pragmatic Paranoia

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| Design by Contract | #36, #37 | §1.5 (Design by Contract) |
| Dead Programs Tell No Lies | #38 | §1.6 (Dead Programs) |
| Assertive Programming | #39 | §1.5 (Design by Contract) |
| How to Balance Resources | #40, #41 | (philosophy) |
| Don't Outrun Your Headlights | #73 (partial) | §1.6 (Dead Programs — "graceful degradation" pattern) |

### Ch 5 — Bend, or Break

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| Decoupling | #44, #45, #46 | §1.7 (Law of Demeter) |
| Juggling the Real World | #41, #56 | §1.10 (Take Small Steps), §1.9 (Temporal Coupling) |
| Transforming Programming | #49, #50 | §1.2 (Orthogonality) |
| Inheritance Tax | #51, #52, #53, #54 | §1.2 (Orthogonality — composition is the only path) |
| Configuration | #55, #78, #79 | §1.8 (Metaprogramming) |

### Ch 6 — Concurrency

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| Breaking Temporal Coupling | #56, #57 | §1.9 (Temporal Coupling) |
| Shared State Is Incorrect State | #57 | §1.9 (Temporal Coupling) |
| Actors and Processes | #58, #59 | §1.9 (Temporal Coupling) |
| Blackboards | #60 | §1.9 (Temporal Coupling) |

### Ch 7 — While You Are Coding

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| Listen to Your Lizard Brain | #61 | §1.9 (Temporal Coupling) |
| Programming by Coincidence | #62 | §1.11 (Program Deliberately) |
| Algorithm Speed | #63, #64 | §1.12 (Algorithm Speed) |
| Refactoring | #65 | §1.13 (Refactoring) |
| Test to Code | #66, #67, #68, #69, #70 | §1.14 (Code That's Easy to Test) |
| Property-Based Testing | #71 | (philosophy) |
| Stay Safe Out There | #72, #73 | §1.6 (Dead Programs — defensive programming) |
| Naming Things | #74 | (philosophy) |

### Ch 8 — Before the Project

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| The Requirements Pit | #75, #76, #77 | §1.18 (Before the Project) |
| Solving Impossible Puzzles | #81 | §2.4 (Cutting the Gordian Knot) |
| Working Together | #82 | §1.18 (Before the Project) |
| The Essence of Agility | #83, #87 | §1.18 (Before the Project) |

### Ch 9 — Pragmatic Projects

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| Pragmatic Teams | #84, #86 | §1.17 (Pragmatic Projects) |
| Coconuts Don't Cut It | #87 | §1.17 (Pragmatic Projects) |
| Pragmatic Starter Kit | #85, #89, #90, #91 | §1.15 (Ubiquitous Automation), §1.17 (Pragmatic Projects) |
| Delight Your Users | #96 | §1.17 (Pragmatic Projects) |
| Pride and Prejudice | #98 | §1.17 (Pragmatic Projects) |

### Closing sections

| Sub-section | Tip(s) | Spine principle |
|---|---|---|
| Postface | (no tips) | — |
| Possible Answers to the Exercises | #92, #93, #94 | §1.15 (Ubiquitous Automation — test-the-tests discipline) |

### Note on chapter → principle spine coverage

The 18 spine principles (§1.1–§1.18) cover all 9 book chapters.
Two chapters had no dedicated spine entry before this revision:

- **Ch 3 (The Basic Tools)** — the *principle* of "use the basic
  tools well" is satisfied by §1.15 Ubiquitous Automation + the
  per-tip rows. The tools themselves (Plain Text, Shell, Version
  Control, Debugging) live as §6 tip rows + the §2.3 Debugging
  Checklist. No new spine entry needed; the tools are the
  *operational form* of §1.15.
- **Ch 8 (Before the Project)** + **Ch 9 (Pragmatic Projects)**
  now have dedicated spine entries (§1.17 + §1.18) so the
  project-shaped work has the same principle-spine coverage as
  the code-shaped work.

If a future revision adds a 19th principle that better names the
"Pragmatic Projects" cluster, fold §1.17 + §1.18 into it. Until
then, the two entries keep the spine faithful to the book's
