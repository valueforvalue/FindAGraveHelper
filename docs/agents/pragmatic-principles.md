# Pragmatic Principles — A Field Guide

> **Audience:** every agent that lands on a slice. Load this doc
> when designing a new feature, refactoring, reviewing a PR, or
> debugging a recurring class of bug. Cross-referenced from
> `AGENTS.md` §LLM session protocol and from
> [`feature-protocol.md`](feature-protocol.md) §Slice plan
> template.

## What this doc is

A **guide**, not a law set. The principles below come from
_The Pragmatic Programmer, 20th Anniversary Edition_ (Hunt &
Thomas). They are the *why* behind the repo's existing rules:
the architecture forbidden-import test enforces **orthogonality**;
the per-addendum routebuilder + uiids registries enforce **DRY**;
the slice-1 discipline enforces **tracer bullets**; the
doc-comment floor enforces **design by contract**.

The laws in [`laws.md`](laws.md) §"Laws (non-negotiable)" are
*earned by a real bug* and are not negotiable. The principles
here are *guides* — they tell you what to think about, and they
name the *known cases* where the repo legitimately violates a
principle temporarily. The agent's job is to know the principle,
know the violation pattern, and **warn + cite** before violating
it (see §"The warn + cite protocol" below).

This is a **field guide**: it tells you what to do, when to do it,
and what to do when the rule doesn't fit. It is not a textbook.
For the book-length treatment, see Hunt & Thomas.

## The warn + cite protocol

When a slice is about to **violate a principle documented here**,
the agent must:

1. **Name the principle** in the slice Plan (the "Principle
   warnings" block — see [`feature-protocol.md`](feature-protocol.md)
   §Slice plan template).
2. **Cite the operational form** being violated (e.g. "the
   deep-module rule in [`complexity.md`](complexity.md)", "the
   forbidden-import test").
3. **State the rationale** for the temporary violation (the
   *why* — what makes this case an exception).
4. **State the cleanup plan** (when + how the violation gets
   resolved — usually a follow-up issue filed in the same slice
   commit).
5. **Land the rationale + cleanup plan verbatim in the commit
   message and the CHANGELOG bullet** so the next agent sees the
   documented violation when reading the work.

The user signs off on the violation as part of the Plan approval
gate (per [`rpci.md`](rpci.md) §C — Critique). Violations without
a documented rationale + cleanup plan are not mergeable. This is
the **enforcement mechanism** for principles-as-guides: not a CI
check (not everything is a law), but a review-gate check (the
human sees the warning before the violation lands).

A documented violation is **not a bug** — it's a *known and
intentional* exception. An **undocumented** violation is a bug.
That distinction is the whole point of the protocol.

## When the principles don't fit

Three patterns where the principles *legitimately* need a local
override:

- **Bridges / adapter code** — every concrete stack has
  adapters that absorb the shape of the world (HTMX attribute
  strings, Wails dialog semantics, OS path quirks). DRY is
  enforced by these adapters; DRY is *not* enforced inside the
  adapters (the adapter is the one place where the duplicated
  shape gets collapsed). See e.g. `addenda/go-htmx.md` for the
  stack-specific worked examples.
- **Tier 1 vs Tier 2 surface** — the per-component byte-stability
  rule in adoptions that pin primitive rendered output. This is
  *imposed duplication* (per DRY §1.1) on purpose: snapshot tests
  pin the duplication so a future refactor can verify the
  primitive swap is safe.
- **Temporary divergence** — a slice that needs to ship faster
  than the principled refactor would allow. The cleanup plan
  documents the divergence; the follow-up issue does the
  refactor. This is **not** an excuse for permanent divergence —
  every temporary violation has a deadline (the cleanup plan),
  and the follow-up issue tracks the deadline.

---

## §1 — The 18 principles

Each entry: 1-sentence definition (from the book), the *why* (what
it saves you from), the repo's operational form (file:line where
the principle is enforced), and a "When you might violate" section
listing the *known* cases where the repo legitimately breaks the
principle. New violation cases found in the wild are added to the
"when you might violate" list — they are warnings, not errors.

### §1.1 — DRY (Don't Repeat Yourself) — Tip #15

> "Every piece of knowledge must have a single, unambiguous,
> authoritative representation within a system."

**The why:** every duplicated representation is a place where a
future change has to be made in N places. Miss one and the system
silently diverges. The cost of a single-source change is O(1); the
cost of an N-place change is O(N) and grows with the system.

**Repo operational form:**
- [`glossary-discipline.md`](glossary-discipline.md) — vocabulary
  DRY (the term + definition + avoid-list pattern). The
  "Flagged ambiguities" section is the regression net for
  vocabulary drift.
- `addenda/go-htmx.md` §"Every templ `hx-*` URL goes through a
  routebuilder" + §"Every persistent DOM surface ID is in the
  registry" — the per-addendum typed URL builder + DOM-ID
  registry are the DRY seam for stack-specific surfaces. The
  `hx_guard_test.go` test fails any templ that uses a string
  literal.
- [`complexity.md`](complexity.md) §"Two-adapter rule" —
  interface DRY (no speculative public methods; one method per
  acceptance criterion, one more per second adapter).

**When you might violate (known cases):**
- **Tier 1 vs Tier 2 surface** — a new component primitive has
  to coexist with the literal class strings it will replace for
  one slice. The follow-up issue documents the swap.
- **Bridge code** — see "When the principles don't fit" above.
- **Glossary tier-2 rename** — when a glossary term is revised,
  the old term may live in the codebase for a release cycle.
  The migration note documents the temporary divergence.

### §1.2 — Orthogonality — Tip #17

> "Two or more things are orthogonal if changes in one do not
> affect any of the others." Also called *cohesion*.

**The why:** a change to module A should not silently require a
change to module B. Non-orthogonal systems make every change
expensive, and the cost grows with the system.

**Repo operational form:**
- [`complexity.md`](complexity.md) §"Enforce boundaries, don't
  honour them" — the architectural-test pattern is the rule.
  Where the language allows, internals are marked internal;
  where it doesn't, a forbidden-import test fails CI on a leak.
  UI depends on the service's DTOs, never on the persistence
  struct.
- The per-stack addendum (`addenda/<stack>.md`) ships the
  package-boundary guard test that mechanically enforces the
  orthogonal shape (e.g. `addenda/go-htmx.md` HTMX-specific
  guard tests: route-table integrity, response-shape contract,
  swap-scope re-binding, OOB target integrity, route-order
  wildcard ordering).

**When you might violate:**
- **Bridge code** — `htmxattr.Mux` (Go) couples the templ + htmx
  worlds on purpose. The coupling is local (one file); the
  *uncoupling* is the rest of the codebase.
- **Cross-cutting concerns** — logging, tracing, theming are
  *designed* to be cross-cutting. They violate strict
  orthogonality; they earn it by being the smallest possible
  cross-cutting surface.
- **DI across a host binding** — when a service is constructed
  in the host entrypoint and passed to a framework binding (Wails
  binding, Electron IPC handler, etc.), the binding *does* know
  about the service. The host-app shape forces this. The
  mitigation is "binding is a thin wrapper, service holds the
  logic" (the seam rule from
  [`feature-protocol.md`](feature-protocol.md) §Module discipline).

### §1.3 — Reversibility — Tip #18

> "No decision is cast in stone. Instead, consider each as being
> written in the sand at the beach, and plan for change."

**The why:** every decision has a chance of being wrong. Decisions
that are easy to reverse are cheap; decisions that are hard to
reverse are expensive. The expensive ones are the ones that need
the most scrutiny.

**Repo operational form:**
- [`commit-and-branch.md`](commit-and-branch.md) §"Branch policy"
  — single-branch default for small repos, three-branch model
  (`dev` / `stable` / `main`) for repos that need a frozen
  production-history anchor. Releases can be rolled back by
  promoting an older `stable` tag.
- The per-addendum URL + DOM-ID registries — every URL and DOM
  ID is a string in a registry, not a literal in templ. A
  rename is a one-file change.
- For repos with a database: the per-migration reversibility
  classification (Reversible / Partially Reversible / Non-
  Reversible), with the downgrade SQL pinned per migration.

**When you might violate:**
- **Host runtime commitment** — e.g. Wails v2.12.0, Electron, Tauri.
  A future major-version migration is the hardest reversibility
  problem in many repos. The mitigation is *named, local*
  workarounds that a future migration can find and remove (per
  `addenda/go-htmx.md` §"Framework quirks" — the
  `Wails-PATCH` / `Wails-FormData` workaround comments are the
  pattern).
- **Schema changes that are non-reversible** — `CREATE TABLE`
  without a corresponding `DROP TABLE` in the downgrade. The
  classification is the *honest* signal: future readers know
  which blocks are forward-only.

### §1.4 — Tracer Bullets — Tip #20

> "Tracer bullets let you home in on your target by trying things
> and seeing how close they land." Small end-to-end vertical
> slices, NOT horizontal layers. Tracer code IS the skeleton of
> the final system — it is NOT a prototype.

**The why:** a tracer bullet proves the path is *wired* end-to-end
without building every layer in isolation. The first bullet
doesn't have to hit the target; the *feedback* is the point.

**Repo operational form:**
- [`feature-protocol.md`](feature-protocol.md) §"Tracer bullets"
  — the rule.
- The `tracer-bullets` skill — auto-loaded by the agent harness.
- [`rpci.md`](rpci.md) §I — "the first slice is the only slice
  that runs in the same session." Slice 1 is always a tracer
  bullet.

**When you might violate:**
- **Documentation-only changes** — no tracer needed for a doc
  commit. The TDD discipline still applies (the doc is the
  surface; the review is the test).
- **Maintenance commits** — `chore:` / `docs:` / `style:` commits
  that ship no behavior change. The fresh-context-per-slice rule
  still applies (the agent must re-read the touched code), but
  the tracer-bullet framing doesn't add signal.

### §1.5 — Design by Contract — Tip #37

> "A correct program is one that does no more and no less than it
> claims to do." Use **preconditions, postconditions, invariants**.

**The why:** contracts make the *boundary* between caller and
callee explicit. A caller that violates a precondition knows
immediately; a callee that violates a postcondition knows
immediately. The contract is the *test surface* — the unit test
is the runtime check.

**Repo operational form:**
- The doc-comment floor ([`laws.md`](laws.md) §"Doc comments on
  exported identifiers") — preconditions are documented for
  every exported Go identifier (per-addendum) or every public
  type (per-stack).
- [`code-changes.md`](code-changes.md) — the cross-layer working
  contract. The drift bug class is what happens when layers
  diverge from the contract.
- The per-addendum architecture test — package-level invariants
  (e.g. `addenda/go-htmx.md` HTMX-specific guard tests).
- The adopting repo's smoke probes — behavioral postconditions
  for the HTTP surface.
- [`tdd.md`](tdd.md) §"Contract touch" — prospective rule for
  new behavior and materially changed public seams. The RED
  test makes relevant caller obligations and observable
  guarantees executable.

**Prospective contract-touch rule:** every new or materially
changed public seam leaves with a clearer documented and
executable contract than it had before. State the relevant
preconditions, postconditions, failure modes, state/atomicity
effects, and idempotency/concurrency rules; omit dimensions
that do not apply. Apply this to existing code when a
behavioral slice materially touches its seam, not through a
backlog-wide retrofit. Mechanical edits do not trigger
contract churn.

This is pragmatic DbC, not a Meyer-style runtime contract
system. Do not add generic `Require`, `Ensure`, or
`Invariant` helpers. Prefer typed languages' type system,
typed builders, database constraints, service validation and
typed errors, architecture tests, and behavior tests. Reserve
panics for developer-created impossible states; ordinary user
input and recoverable failures return through the seam's
documented error path.

**When you might violate:**
- **Third-party library contracts** — when the repo wraps a
  framework behavior, the contract is *theirs*, not ours. The
  repo's contract is the wrapper's doc comment.
- **Best-effort code paths** — graceful-degradation paths fall
  back to a simpler implementation when a richer one fails. The
  contract is "rich path preferred, fallback documented."

### §1.6 — Dead Programs Tell No Lies (Crash Early) — Tip #38

> "A dead program normally does a lot less damage than a crippled
> one."

**The why:** a "crippled" program keeps running with corrupt
state. The damage compounds. A dead program stops, the user
notices, and the bug is found in 5 minutes instead of 5 hours.

**Repo operational form:**
- [`laws.md`](laws.md) §"No unguarded re-entrant UI calls" —
  refusing to start a second native dialog is *crashing early*
  (the UI thread is preserved).
- The per-addendum typed-attribute swap allowlist (e.g.
  `htmxattr.Mux` in Go) — panics at render time on an invalid
  swap value. The panic is the *signal*.

**When you might violate:**
- **User-recoverable errors** — a missing optional field is a
  *toast* (graceful degradation), not a crash.
- **Background jobs** — a job worker that crashes leaves the job
  in an interrupted state. The user can re-run from the source
  page. The interrupted status is the *graceful* version of
  "crash early."

### §1.7 — Decoupling / Law of Demeter — Tip #44

> An object's method should call only methods belonging to itself,
> its parameters, objects it creates, or its directly held
> component objects. "Write shy code."

**The why:** chains like `a.b().c().d()` create hidden coupling.
A change to `b` propagates silently. The Law of Demeter says:
"if you want to talk to `d`, ask `a` to talk to `d` for you."

**Repo operational form:**
- [`complexity.md`](complexity.md) — the deep-module rule covers
  *package*-level decoupling.
- (No formal regression net for *expression*-level Demeter. The
  `gocritic` `rangeValCopy` / `hugeParam` lints catch adjacent
  smells but not Demeter chains. Open gap.)

**When you might violate:**
- **Error chains** — `if err := a.B(); err != nil { return
  fmt.Errorf("b: %w", c(err)) }` is *not* a Demeter violation;
  the chain is *one* call. Demeter violations look like
  `result := a.B().C().D()` where the intermediate objects
  matter.
- **Builder / fluent APIs** — `htmxattr.Mux{...}.Attrs()` IS a
  Demeter chain. The mux package owns the constraint (it
  validates as it builds), so the chain is *intentional and
  self-checking*.

### §1.8 — Metaprogramming (abstractions in code, details in metadata) — Tip #79

> "Program for the general case, and put the specifics somewhere
> else — outside the compiled code base."

**The why:** code is expensive to change (rebuild, redeploy);
metadata is cheap (reload). The rule puts the *stable* part in
code and the *changeable* part in metadata.

**Repo operational form:**
- The per-addendum URL + DOM-ID registries are metadata.
- Lint rule definitions are *data* that the linter consumes
  (e.g. `.mutesting.yaml` per `addenda/go-htmx.md`).
- Theme tokens are metadata; the templ / view components
  consume them.
- [`laws.md`](laws.md) §"Tier-0 docs have a size ceiling" pins
  the tier-0 budget as metadata (a budget per tier, not per
  doc); the agent reads the budget at session start.

**When you might violate:**
- **Performance-critical paths** — when the metadata lookup is a
  hot path, a precomputed constant in code wins. The
  `htmxattr.Mux` builder pre-validates at construction time so
  the render path is metadata-free.
- **Type-checked metadata** — when the metadata has invariants
  that a string registry can't express, a typed enum / const
  wins.

### §1.9 — Temporal Coupling / Concurrency — Tip #57

> "Reduce any time-based dependencies." Design for concurrency so
> the system can be deployed flexibly and tested for thread safety.

**The why:** a system with hidden time dependencies is hard to
test (you can't pause it), hard to reason about, and prone to
race conditions. Explicit concurrency makes the time dimension
*part of the API*.

**Repo operational form:**
- Per-process actor state (the Wails `App` struct, the Electron
  main process, Tauri main, etc.) — equivalent to an actor. The
  actor holds all state; goroutines / handlers receive a
  pointer.
- The hungry-consumer model in background-job workers.
- The in-flight dedup pattern (`LoadOrStore` + `defer Delete`)
  is a per-slot mutex.

**When you might violate:**
- **Single-threaded UI paths** — the templ render path is
  single-threaded by construction (Go templates are not
  thread-safe in the templ runtime). The render doesn't *need*
  concurrency; forcing it would add coordination cost for no
  win.
- **Synchronous test paths** — Go tests run sequentially by
  default. The race detector (`go test -race`) is the *opt-in*
  concurrency check.

### §1.10 — Take Small Steps (Tracer Bullets + MVC seam) — Tip #42

> "Small steps always; check the feedback; and adjust before
> proceeding." Each slice is a *view* of the model rendered
> once — the slice lives or dies on the next slice's signal.

**The why:** a big-bang change hides the failure mode until
the change is too big to roll back. A small step is *cheap
to reverse* (Tip #18 Reversibility) and *cheap to verify*
(Tip #31 Failing Test Before Fixing Code). The "view" is
the slice's rendered output — a view that knows about the
model is bound to one view of that model; a small step
that knows about the *next* step is free to evolve.

**Repo operational form:**
- **Tracer Bullets** — [`feature-protocol.md`](feature-protocol.md)
  slice discipline. Every Tier 2 vertical slice crosses every
  layer (templ + htmx + JS + Go handler + DB). The slice IS
  the "view" of the model the user sees at that commit.
- **MVC seam** — the model layer (no UI imports), the view layer
  (templ / templates + frontend JS), the controller layer (HTTP
  handlers + framework bindings), and a grey-box viewmodel layer
  between the model and the view.

**When you might violate:**
- **Static / read-only viewers** — a static archive or read-only
  snapshot that ships a *second* view of the same data the live
  app mutates. This is *intentional* — the static archive IS a
  second view of the same model. The principle is satisfied.
- **Debug overlays** — a `//go:build debug` debug overlay that
  ships nowhere in production. The build tag is the seam.
- **Big-bang refactors** — a refactor that touches every layer
  in one commit is the "all the eggs in one basket" violation.
  The Tier 2 / Tier 3 commit rule catches this; the refactor
  belongs in N small slices, each slice a view of the target
  shape.

### §1.11 — Program Deliberately — Tip #62

> "Rely only on reliable things. Beware of accidental complexity,
> and don't confuse a happy coincidence with a purposeful plan."

**The how-to-program-deliberately checklist (8 rules):**
1. Always be aware of what you are doing
2. Don't code blindfolded
3. Proceed from a plan
4. Rely only on reliable things
5. Document your assumptions
6. Test assumptions as well as code
7. Prioritize your effort
8. Don't be a slave to history

**The why:** every "it worked but I don't know why" moment is a
landmine. Program by coincidence is the *fastest* way to ship
a bug.

**Repo operational form:**
- Rules 1-4: [`rpci.md`](rpci.md) + [`tdd.md`](tdd.md) cover
  all four.
- Rule 5: doc-comment floor ([`laws.md`](laws.md) §"Doc comments
  on exported identifiers") + "What assumptions does this PR
  make?" line in the slice plan (open audit gap).
- Rule 6: property-based tests, drift detectors.
- Rule 7: fresh-context-per-slice rule ([`rpci.md`](rpci.md)
  §I).
- Rule 8: refactor Early / refactor Often.

**When you might violate:**
- **Rapid prototyping** — `.scratch/` is *deliberately* below
  the bar. The code there is disposable; "test assumptions"
  doesn't apply to throwaway.
- **Documentation work** — the principle is about *code*. Docs
  are checked by the review, not by tests.

### §1.12 — Algorithm Speed (Big O) — Tip #63

> "Get a feel for how long things are likely to take before you
> write code."

**The why:** an O(n²) algorithm on a 10k-row table is a real
problem; the same algorithm on a 100-row table is not. The Big
O annotation tells the next reader *where* to look if the perf
budget breaks.

**Repo operational form:**
- The per-iter footprint doc-comment pattern (per
  [`tdd.md`](tdd.md) §"Per-layer recipes") — count of DB
  queries per operation + budget. The pattern documents the
  actual footprint in the function's doc-comment.

**When you might violate:**
- **Trivial code paths** — a 5-line helper doesn't need an
  O(1) annotation. The rule applies to *non-trivial* functions
  in the model's heavy paths (DB queries, batch operations,
  background-job workers).
- **Already-validated code** — the per-iter footprint pattern
  subsumes Big O for the database paths. A function that
  already has a documented footprint doesn't need a separate
  Big O annotation.

### §1.13 — Refactoring — Tip #65

> "Just as you might weed and rearrange a garden, rewrite, rework,
> and re-architect code when it needs it. Fix the root of the
> problem."

**The when-to-refactor checklist (5 triggers):**
1. DRY violation
2. Non-orthogonal
3. Knowledge improved
4. Requirements evolve
5. Performance

**The how-to-refactor checklist (3 rules):**
1. Don't try to refactor and add functionality at the same time
2. Make sure you have good tests before you begin refactoring
3. Take short, deliberate steps

**Repo operational form:**
- The Tier 2 / Tier 3 commit rule ([`feature-protocol.md`](feature-protocol.md))
  — the "don't refactor and add functionality at the same
  time" rule is operationalized as the slice discipline.
- [`tdd.md`](tdd.md) — "have good tests before refactoring."

**When you might violate:**
- **Drive-by cleanup** — a "while I'm here" cleanup in a feature
  commit violates rule 1. The Tier 2 / Tier 3 rule catches
  this; the drive-by belongs in a separate commit.
- **Refactor without tests** — the red-green-refactor loop
  requires tests *first*. A refactor commit without coverage
  is a Tier 3 maintenance commit, not a Tier 2 vertical.

### §1.14 — Code That's Easy to Test — Tip #67

> "Build testability into the software from the very beginning."

**The 7 Aspects of Testing (Ch 8):**
1. Unit testing
2. Integration testing
3. Validation and verification
4. Resource exhaustion, errors, and recovery
5. Performance testing
6. Usability testing
7. Testing the tests themselves

**Repo operational form:**
- (1) Unit: every internal package has a `*_test.go` (or
  analog).
- (2) Integration: an HTTP-handler test harness + per-handler
  integration tests.
- (3) Validation: smoke probes driving the live binary.
- (4) Resource: goroutine leak tests (`zzz_goleak_test.go` or
  analog).
- (5) Performance: the per-iter footprint doc-comment pattern
  + a stress-test workflow.
- (6) Usability: the manual audit playbook (see
  `docs/agents/manual-audit-playbook.md`).
- (7) Test-the-tests: mutation testing is an open gap (see
  `scripts/check-mutations.sh` template).
- Test-quality bar: [`testing-philosophy.md`](testing-philosophy.md)
  — the saboteur test (Tip #64) and the "which tests earn
  their place" checklist (state coverage not line coverage, no
  stdlib re-testing, no compile-time checks masquerading as
  runtime tests). Pairs with [`tdd.md`](tdd.md): TDD is the
  *process*, testing philosophy is the *quality bar*.

**When you might violate:**
- **Pure UI code** — usability testing is the only aspect that
  applies, and it is manual.
- **Throwaway code** — `.scratch/` and the `repl` skill are
  below the testing bar by design.

### §1.15 — Ubiquitous Automation — Tip #85

> "A shell script or batch file will execute the same
> instructions, in the same order, time after time."

**The why:** every manual procedure is a place where a future
operator will get it slightly different. Automation is the
*only* way to guarantee repeatability.

**Repo operational form:**
- The adopting repo's `scripts/` + `Makefile` / `package.json`
  targets + CI workflows.
- The agent-stack CLI surface: any documented CLI / make
  target should be enforced by a coverage check (DixieData's
  `cli-coverage.mjs` is the reference pattern; per-adopter
  concern).

**When you might violate:**
- **One-time setup** — a single `git mv` is fine by hand; a
  scripted equivalent adds complexity for no win.
- **Operator judgment** — a "promote to stable" decision is
  *not* fully automatable (the human reviews the diff). The
  automation is the *enforcement* (`make promote-dry-run` is
  a CI gate), not the *decision*.

### §1.16 — It's All Writing (English as code) — Tip #13

> "Write documents as you would write code: honor the DRY
> principle, use metadata, MVC, automatic generation."

**The why:** docs that diverge from the code rot. Docs that
live in the same repo (versioned, reviewed, CI-checked) don't
rot as fast.

**Repo operational form:**
- `CONTEXT.md` is the project glossary (DRY for vocabulary).
- [`docs-index-scheme.md`](docs-index-scheme.md) is the
  progressive-disclosure table (3-tier doc structure).
- The doc-comment floor ([`laws.md`](laws.md) §"Doc comments on
  exported identifiers") is the cross-layer contract: code and
  doc are versioned together.

**When you might violate:**
- **Date-stamped web docs** — the book recommends date-stamping
  every web page; the repo's `docs/` are local +
  version-controlled and the date stamp is
  `git log -1 --format=%ai <file>`. The principle is satisfied;
  the form is different.
- **Per-release notes** — the CHANGELOG is hand-curated today.
  A git-cliff / conventional-changelog generator is an open
  follow-up; the manual curation works for now.

### §1.17 — Pragmatic Projects (Ch 9) — Tip #96

> "Develop solutions that produce business value for your users
> and delight them every day." The project is bigger than the
> code: the team shape, the starter kit, the cadence, and the
> user-impact measurement are all part of the work.

**The why:** Ch 9 (Pragmatic Projects) is the book's reminder
that *shipping code* is not the same as *shipping a project*.
A team that can't communicate, a kit that doesn't bootstrap a
new contributor in a day, and a release cadence that misses the
user's need all fail the project even when the code is correct.
"Delight users" is the *outcome*; teams, starter kit, and pride
are the *inputs*.

**Repo operational form:**
- **Pragmatic Teams** — Tip #86 is N/A for solo work, but the
  *full-stack team* discipline lives in the slice discipline
  (every slice crosses every layer, so the same agent exercises
  backend + frontend + test).
- **Coconuts Don't Cut It** — Tip #87 ("Do What Works, Not
  What's Fashionable") is the explicit form: no React, no ORM,
  no microservices. The stack is chosen for fit, not fashion.
  The `addenda/` invite per-stack extension (Go + HTMX,
  React, Python, etc.) without mandating any of them.
- **Pragmatic Starter Kit** — Tip #89 (Version Control to Drive
  Builds) + Tip #90 (Test Early/Often/Auto) + Tip #85 (Schedule
  It) are the starter-kit pillars. The `scripts/init.sh`
  bootstrap + `templates/AGENTS.md.tmpl` are the operational
  form.
- **Delight Your Users** — Tip #96 is the canonical anchor.
  Every slice carries an "Acceptance criteria" section that
  pins what the user sees (not what the code does).
- **Pride and Prejudice** — Tip #98 ("First, Do No Harm") is
  the anchor. The universal-laws pattern (every law was earned
  by a bug it would prevent) + the cross-layer working contract
  in [`code-changes.md`](code-changes.md) are the form.

**When you might violate:**
- **Solo project scope** — Tips #84, #86, #83 are formally
  N/A (no teams, no agile ceremony). The *principles* still
  apply: small stable review surface, full-stack scope per
  slice, "the code is the project" mindset.
- **Per-user ad-hoc cadence** — the project ships when the
  smallest useful slice is green. A "polish cycle" that ships
  nothing for 2 weeks violates Tip #88 ("Deliver When Users
  Need It").

### §1.18 — Before the Project (Ch 8) — Tip #75

> "They might know a general direction, but they won't know the
> twists and turns." Requirements are *learned in a feedback
> loop*; the project's shape is co-created with the user.

**The why:** Ch 8 (Before the Project) covers the work that
happens *before* the code: requirements discovery, impossible
problems, team shape, agility. The pragmatic answer is not a
big upfront spec — it's a feedback loop (RPCI) where each slice
sharpens the next.

**Repo operational form:**
- **The Requirements Pit** — Tip #75 ("No One Knows Exactly
  What They Want") + Tip #76 ("Programmers Help People
  Understand What They Want") + Tip #77 ("Requirements Are
  Learned in a Feedback Loop"). The slice plan + the
  apply-sites checklist in every feature issue
  ([`issues/feature-template.md`](../issues/feature-template.md))
  are the operational form. The user sees the *full shape* of
  the change before code lands.
- **Solving Impossible Puzzles** — §2.4 Cutting the Gordian
  Knot is the bookend checklist; the 6 questions are the test
  surface for "find the box."
- **Working Together** — Tip #82 ("Don't Go into the Code
  Alone") is partial — the user + agent pairing is the
  implicit team. The slice-plan review + the PR body are the
  closest formal form.
- **The Essence of Agility** — Tip #83 ("Agile Is Not a Noun;
  Agile Is How You Do Things") is N/A in name but satisfied in
  practice: the slice cadence + the "ship the smallest useful
  unit" discipline are the operational form.

**When you might violate:**
- **User-stated requirements** — the user *is* the chat per
  `AGENTS.md`; the feedback loop runs through every slice. A
  user who says "I want X, build X" gets X via the slice plan,
  but the slice plan may also surface adjacent concerns the
  user hadn't articulated (Tip #76).
- **Single-shot projects** — a "one and done" project still
  goes through the requirements loop, just faster. The slice
  discipline is the loop's compression.

---

## §2 — The 4 book-end checklists

The book has 4 checklists that the principle spine references but
which don't fit under any one principle. Each is a *test* an
agent should run before shipping.

### §2.1 — WISDOM Acrostic (Ch 1, Communicate)

When writing for the user (CHANGELOG, issue body, commit
message, ADR, README), use the WISDOM acrostic:

- **W**hat do you want them to learn?
- What **i**s their interest in what you've got to say?
- How **s**ophisticated are they?
- How much **d**etail do they want?
- Whom do you want to **o**wn the information?
- How can you **m**otivate them to listen to you?

**The why:** a CHANGELOG bullet aimed at the wrong audience either
bores an expert or loses a new contributor. The WISDOM acrostic
forces the writer to choose the audience before choosing the
words.

**When you might violate:** internal-only docs (`.scratch/`,
`/tmp`, debug logs) where the audience is the agent.

### §2.2 — Architectural Questions (Ch 7)

When designing a new module / service / feature, ask:

1. Are responsibilities well defined?
2. Are the collaborations well defined?
3. Is coupling minimized?
4. Can you identify potential duplication?
5. Are interface definitions and constraints acceptable?
6. Can modules access needed data — when needed?

**The why:** the 6 questions are the *test surface* for the deep-
module rule. A "no" on any one of them is a flag that the design
will fight back later.

**Repo operational form:** questions 1-4 are operationalized by
[`complexity.md`](complexity.md) §"Deep-module discipline".
Questions 5-6 depend on per-stack conventions in the relevant
addendum.

### §2.3 — Debugging Checklist (Ch 3)

When stuck on a bug, ask:

1. Is the problem being reported a direct result of the underlying
   bug, or merely a symptom?
2. Is the bug really in the compiler? Is it in the OS? Or is it
   in your code?
3. If you explained this problem in detail to a coworker, what
   would you say?
4. If the suspect code passes its unit tests, are the tests
   complete enough? What happens if you run the unit test with
   this data?
5. Do the conditions that caused this bug exist anywhere else in
   the system?

**The why:** the 5 questions are the *test surface* for the
"fix root cause, not symptom" pattern. A "no" on question 5 is
a flag for the "find bugs once" rule — the bug will recur.

**Repo operational form:** spirit is enforced by the
orphan-handler probe + the per-bug regression-test discipline
(per [`tdd.md`](tdd.md)). The 5-question checklist is not yet
in any tier-1 doc; this doc is the first place it lives.

### §2.4 — Cutting the Gordian Knot (Ch 7)

When solving an impossible problem, ask:

1. Is there an easier way?
2. Am I solving the right problem?
3. Why is this a problem?
4. What makes it hard?
5. Do I have to do it this way?
6. Does it have to be done at all?

**The why:** the 6 questions are the *test surface* for the
"find the box" rule. A "yes" on question 6 ("don't have to do
it at all") is the most valuable answer in software.

**When you might violate:** a user-stated requirement that
*is* required (a tax form, a regulatory export). The 6 questions
help the agent find a *cheaper* way; they don't help with a
*non-negotiable* way.

---

## §3 — Cross-reference: principle ↔ agent-stack doc

Some principles are *also* enforced as Laws (in
[`laws.md`](laws.md)). This is intentional: the principles are
the *why*; the Laws are the *earned-by-real-bug operational
form* of the principles. A principle may have multiple Laws
under it; a Law may pin a single operational form of a
principle.

| Principle | Agent-stack Doc(s) / Law(s) |
|---|---|
| DRY | [`glossary-discipline.md`](glossary-discipline.md) (vocabulary DRY); [`complexity.md`](complexity.md) §"Two-adapter rule" (interface DRY) |
| Orthogonality | [`complexity.md`](complexity.md) — the deep-module rule + architectural-test pattern |
| Reversibility | [`commit-and-branch.md`](commit-and-branch.md) §"Branch policy"; per-stack reversibility classification |
| Tracer Bullets | [`feature-protocol.md`](feature-protocol.md) — slice discipline |
| Design by Contract | [`laws.md`](laws.md) §"Doc comments on exported identifiers"; [`code-changes.md`](code-changes.md) — cross-layer contract |
| Dead Programs | [`laws.md`](laws.md) §"No unguarded re-entrant UI calls"; per-addendum dialog-guard laws |
| Law of Demeter | [`complexity.md`](complexity.md) — deep-module rule at package level |
| Metaprogramming | Per-addendum: typed URL builder + DOM-ID registry |
| Temporal Coupling | [`laws.md`](laws.md) — re-entry protection (per-slot mutex) |
| Take Small Steps | [`feature-protocol.md`](feature-protocol.md) — tracer-bullet slice discipline; model + viewmodel + view layers |
| Program Deliberately | [`rpci.md`](rpci.md) — RPCI flow; [`laws.md`](laws.md) — universal laws |
| Algorithm Speed | [`tdd.md`](tdd.md) — per-iter footprint doc-comment pattern |
| Refactoring | [`feature-protocol.md`](feature-protocol.md) — Tier 2 / Tier 3 commit rule |
| Code That's Easy to Test | [`tdd.md`](tdd.md) — RED/GREEN/REFACTOR; [`testing-philosophy.md`](testing-philosophy.md) — quality bar (which tests earn their place, the saboteur test, find-bugs-once) |
| Ubiquitous Automation | Per-repo CI + `scripts/` |
| It's All Writing | [`laws.md`](laws.md) — doc-comment floor; [`docs-index-scheme.md`](docs-index-scheme.md) (tier table) |
| Pragmatic Projects | `scripts/init.sh` (starter kit); [`feature-protocol.md`](feature-protocol.md) §Apply sites (delight users) |
| Before the Project | [`rpci.md`](rpci.md) — RPCI feedback loop; [`feature-protocol.md`](feature-protocol.md) §Slice plan template (apply-sites checklist) |

The principle is the *why*; the doc is the *what*. Both are
useful. New contributors should read the principles (this doc);
the *reviewer* reads the Laws. The principle explains why the
Law exists; the Law tells you what to do without re-deriving
the why.

---

## §4 — How to extend this doc

When a new principle-violation pattern shows up in a PR review:

1. **File the violation in the slice commit's "Principle warnings"
   block** (per §"The warn + cite protocol" above).
2. **If the violation is the kind that will recur**, add a
   "When you might violate" bullet to the relevant principle
   section. The doc grows with the codebase.
3. **If the violation is the kind that should NOT recur**, file
   a follow-up issue for the cleanup, and add a "Known gap"
   bullet to the principle section. The doc + the issue track
   the violation together.

When a new principle is needed (e.g. a 19th principle emerges
from a new book or a new pattern in the codebase), add a new
§1.N section following the same template. The doc is *additive*;
a new section is one PR.

---

## §5 — References

- _The Pragmatic Programmer, 20th Anniversary Edition_, Hunt &
  Thomas. The 100 tips are excerpted at
  <https://pragprog.com/tips/>.
- The principle spine + 11 book-end checklists are summarized
  at
  <https://github.com/HugoMatilla/The-Pragmatic-Programmer#checklist>.
- The 2-pass audit that produced this doc:
  [`docs/audit/pragmatic-programmer-audit-2026-07.md`](../docs/audit/pragmatic-programmer-audit-2026-07.md)
  (100-tip view, retained as a historical artifact).
- The cross-referenced agent-stack docs:
  - [`laws.md`](laws.md) — the earned-by-real-bug operational form
  - [`feature-protocol.md`](feature-protocol.md) — slice discipline + Tier 1-3 commit rule
  - [`rpci.md`](rpci.md) — RPCI flow
  - [`complexity.md`](complexity.md) — deep-module discipline
  - [`tdd.md`](tdd.md) — RED/GREEN/REFACTOR
  - [`testing-philosophy.md`](testing-philosophy.md) — test-quality bar (which tests earn their place)
  - [`code-changes.md`](code-changes.md) — cross-layer working contract
  - [`glossary-discipline.md`](glossary-discipline.md) — vocabulary DRY
  - [`bug-patterns.md`](bug-patterns.md) — per-layer bug catalog
  - [`commit-and-branch.md`](commit-and-branch.md) — branch policy
  - [`session-protocol.md`](session-protocol.md) — agent procedural rules
  - [`docs-index-scheme.md`](docs-index-scheme.md) — 3-tier docs taxonomy
  - [`adr-discipline.md`](adr-discipline.md) — ADR mechanics

---


---

## Tip index + chapter cross-reference (externalized)

The full per-tip table (§6, ~100 rows of Tip → State →
Principle → Evidence), the count summary (§7), and the chapter
cross-reference (§9) live in a separate doc to keep this spine
load-light:

> **[`../audit/pragmatic-tips-index-2026-07.md`](../audit/pragmatic-tips-index-2026-07.md)**

**When to load:** on demand, when checking whether a specific
commit, behavior, or new pattern is in compliance with the
canonical book. **Not** part of the Tier-0 / Tier-1 load — load
only when reviewing or planning.

The spine (this doc's §1–§5) is the primary lens for design
work; the tip index is the primary lens for compliance checks.
See the externalized doc for the per-tip state legend, the
100-row table, the count summary, and the 9-chapter
cross-reference.
