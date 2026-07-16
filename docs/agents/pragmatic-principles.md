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
| Code That's Easy to Test | [`tdd.md`](tdd.md) — RED/GREEN/REFACTOR |
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
  - [`code-changes.md`](code-changes.md) — cross-layer working contract
  - [`glossary-discipline.md`](glossary-discipline.md) — vocabulary DRY
  - [`bug-patterns.md`](bug-patterns.md) — per-layer bug catalog
  - [`commit-and-branch.md`](commit-and-branch.md) — branch policy
  - [`session-protocol.md`](session-protocol.md) — agent procedural rules
  - [`docs-index-scheme.md`](docs-index-scheme.md) — 3-tier docs taxonomy
  - [`adr-discipline.md`](adr-discipline.md) — ADR mechanics

---

## §6 — Tip index (the 100 tips, by number)

This index is the **operational counterpart** to the principle
spine in §1. Each tip is a concrete behavior; the principle
is the *why* behind the behavior. The principle spine is what
an agent reads when designing a new feature; this index is what
an agent reads when checking whether a specific commit or
behavior is in compliance.

### When to consult this table

- **Slice planning** (per [`feature-protocol.md`](feature-protocol.md))
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
- ✅ **Enforced** — a [`laws.md`](laws.md) Law, a tier-1
  `core/*.md` rule, an `addenda/*` rule, an `issues/*.md`
  template, a `scripts/*` automation, or a `templates/*.md.tmpl`
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
[`docs/audit/pragmatic-programmer-audit-2026-07.md`](../docs/audit/pragmatic-programmer-audit-2026-07.md)
(the 100-tip map retained as a historical artifact).

| # | Tip | State | Principle | Evidence / how to apply |
|---|---|---|---|---|
| 1 | Care About Your Craft | ✅ | — (philosophy / technique, not a principle) | [`session-protocol.md`](session-protocol.md) §"Bias toward action" + §"Proportional depth" + the entire doc-comment floor + [`commit-and-branch.md`](commit-and-branch.md) §"Push verification" + the CHANGELOG discipline. *How to apply:* read [`AGENTS.md`](../AGENTS.md) first thing in every session; if a session ended without updating the doc when a new pattern emerged, the next session has lost the rule. |
| 2 | Think! About Your Work | ✅ | — (philosophy / technique, not a principle) | [`rpci.md`](rpci.md) RPCI flow explicitly turns off the autopilot: every Plan has a Critique phase the user signs off on before code lands. *How to apply:* before writing the first line of a slice, write the slice plan (files touched, success criteria, regression net) into the issue body. If you can't write those three things, you haven't thought yet. |
| 3 | You Have Agency | ✅ | — (philosophy / technique, not a principle) | [`rpci.md`](rpci.md) §C — Critique gate is the operational form. The user has explicit "approve, start" authority over every plan; the agent never starts work without it. *How to apply:* if a slice feels blocked by a missing requirement, surface the decision in `ask_user_question` with 2-4 options, not by stalling. |
| 4 | Provide Options, Don't Make Lame Excuses | ✅ | — (philosophy / technique, not a principle) | [`rpci.md`](rpci.md) Plan surfaces "decisions to confirm" with options; the user picks, the agent never says "can't be done." *How to apply:* every blocker you hit becomes a 2-4 option question, not a refusal. "Can't do X" → "Can do A, B, or C; which?" |
| 5 | Don't Live with Broken Windows | ✅ | — (philosophy / technique, not a principle) | [`laws.md`](laws.md) — every Law was earned by a real bug. The universal-laws pattern (re-entry, doc-comment floor, glossary, agent-context files, tier-0 size ceiling) is the operational form. *How to apply:* when a slice ships a backend surface without a UI apply-site, the slice is *not done*. Open a follow-up issue the same commit. |
| 6 | Be a Catalyst for Change | ⚠️ | — (philosophy / technique, not a principle) | agent-stack is *literally* a catalyst (`scripts/init.sh` + `addenda/` invite contribution + the per-issue feature template). No written rule beyond "ship the follow-up issue in the same commit." *When violated:* a stale doc, an undocumented pattern, or a workaround that nobody proposed a fix for. *How to apply:* when you find a broken window, file the follow-up issue + propose the slice in the same message; don't wait for someone else. |
| 7 | Remember the Big Picture | ✅ | — (philosophy / technique, not a principle) | [`docs-index-scheme.md`](docs-index-scheme.md) 3-tier progressive-disclosure table is the operational form. Agents know which tier to load for the task. *How to apply:* every session starts by reading the tier table; the 3-tier structure tells you whether to load a doc, just skim it, or skip it entirely. |
| 8 | Make Quality a Requirements Issue | ✅ | — (philosophy / technique, not a principle) | [`issues/feature-template.md`](../issues/feature-template.md) §'Acceptance criteria' makes testability a required bullet; per-addendum quality bar (test floor, smoke probe, adjacent sweep) is the regression net. *How to apply:* the slice plan template makes test + smoke probe mandatory bullets; a plan without them is not a valid plan. |
| 9 | Invest Regularly in Your Knowledge Portfolio | ⚠️ | — (philosophy / technique, not a principle) | [`docs/learning/README.md`](../docs/learning/README.md) + `docs/learning/addenda/go-htmx.md` ship per the four-section pattern (mental model, vocabulary, idioms, anti-patterns). No scheduled reading cadence. *When violated:* a new framework or book is added to the stack without a learning doc. *How to apply:* when a new book or framework is added to the stack, add a learning doc that follows the four-section pattern. |
| 10 | Critically Analyze What You Read and Hear | ⚠️ | §2.1 WISDOM | The framework applies this in the "forgo following fads" framing (per §1.3 Reversibility). *When violated:* a "let's rewrite in X" pitch that arrives without a stated problem to solve. *How to apply:* every architecture choice ships with a 1-line problem statement; a pitch without the problem is a red flag. Ask "what bug does this fix?" before adopting. |
| 11 | English is Just Another Programming Language | ✅ | §1.1 DRY | [`glossary-discipline.md`](glossary-discipline.md) + the 3-tier docs taxonomy. Every doc is reviewed for terminology drift; the "Flagged ambiguities" section is the regression net. *How to apply:* if a term is used in two places, one of them is wrong. Either rename to match the glossary or update the glossary + file the rename in the same commit. |
| 12 | It's Both What You Say and the Way You Say It | ✅ | §2.1 WISDOM | [`commit-and-branch.md`](commit-and-branch.md) §"Commit message shape" mandates 1-3 bullets explaining the *why* + regression net. The CHANGELOG tone is exemplary: long-form bullets explain the *why*, the regression net, and the out-of-scope. *How to apply:* a commit message without the regression net line is incomplete; a CHANGELOG bullet without the *why* is too thin. |
| 13 | Build Documentation In, Don't Bolt It On | ✅ | §1.16 It's All Writing | [`laws.md`](laws.md) §"Doc comments on exported identifiers" + the 3-tier docs taxonomy + [`templates/AGENTS.md.tmpl`](../templates/AGENTS.md.tmpl). Every exported identifier ships with a doc comment; every framework URL is a typed call. *When violated:* a new top-level URL string in a templ file (the architecture test fails the build). |
| 14 | Good Design Is Easier to Change Than Bad Design | ✅ | §1.3 Reversibility | [`complexity.md`](complexity.md) deep-module discipline + per-addendum guard tests are the rule. "Code that's easy to change" lives at the interface, not at the implementation. *How to apply:* a new module lands behind a small facade; the architecture test refuses cross-package deep imports. If your slice needs to reach across 3 packages, the design is wrong; refactor first. |
| 15 | DRY—Don't Repeat Yourself | ✅ | §1.1 DRY | [`glossary-discipline.md`](glossary-discipline.md) (vocabulary DRY) + [`complexity.md`](complexity.md) §"Two-adapter rule" (interface DRY) + per-addendum routebuilder + DOM-ID registries (typed-builder DRY). *When violated:* a URL literal in a templ file (caught by the per-addendum guard test); a duplicated kind label across two switch statements (caught by the per-package snapshot test); a vocabulary term with two spellings (caught by the glossary review). *How to apply:* before writing the second copy, grep for the first; if the first exists, refactor before duplicating. |
| 16 | Make It Easy to Reuse | ✅ | §1.1 DRY | The per-addendum design-system primitives (Button, Card, Pill, EmptyState, Field, Toast, Foldout in `addenda/go-htmx.md`; analogous in other addenda) are the single source for visual patterns; per-component snapshot tests pin byte-stable output. *How to apply:* new visual pattern → new primitive in the per-addendum components directory + per-component snapshot test. A templ file with a hand-rolled class string is a *new primitive waiting to be extracted*. |
| 17 | Eliminate Effects Between Unrelated Things | ✅ | §1.2 Orthogonality | [`complexity.md`](complexity.md) deep-module discipline + the per-stack forbidden-import test pattern (e.g. `addenda/go-htmx.md` HTMX-specific guard tests). *How to apply:* a new import that crosses a boundary fails the architecture test. Fix: move the type to a shared package or expose a facade method. |
| 18 | There Are No Final Decisions | ✅ | §1.3 Reversibility | [`commit-and-branch.md`](commit-and-branch.md) §"Branch policy" supports both single-branch and three-branch models. Releases tag the merge commit on the integration branch; rollbacks promote an older `stable` tag. *When violated:* a direct push to `main` or `stable` (rejected by branch protection); a non-reversible migration without a downgrade SQL path (rejected by the migrations review). |
| 19 | Forgo Following Fads | ⚠️ | §1.3 Reversibility | Implicit in the stack choices (no React, no ORM, no microservices — `addenda/` invites per-stack extension but doesn't mandate any of them) but no written policy. *When violated:* a "rewrite in [framework]" pitch that arrives without a 1-line problem statement. *How to apply:* the architecture choices are listed in [`adr-discipline.md`](adr-discipline.md); a new framework needs its own ADR with the alternatives considered and the rejected option's rationale. |
| 20 | Use Tracer Bullets to Find the Target | ✅ | §1.4 Tracer Bullets | The `tracer-bullets` skill (auto-loaded) + [`feature-protocol.md`](feature-protocol.md) §"Tracer bullets" + the Tier 1/2/3 commit rule. *How to apply:* every Tier 2 vertical slice is a tracer bullet. The slice's RED test is the "fires" check. If the bullet misses (the test is hard to write or passes for the wrong reason), the next slice adjusts the aim. |
| 21 | Prototype to Learn | ⚠️ | — (philosophy / technique, not a principle) | `.scratch/` is the prototype playground (Python scripts, MCP probes) and `repl` skill is a scratch tool. *When violated:* a 200-line prototype landed in `internal/` because nobody created the `.scratch/` shim first. *How to apply:* if the slice's success criteria includes "learn whether X is feasible," the prototype lives in `.scratch/`; only the proven mechanism ports to `internal/`. |
| 22 | Program Close to the Problem Domain | ✅ | — (philosophy / technique, not a principle) | [`complexity.md`](complexity.md) §"Deep-module discipline" mandates domain-shaped public surfaces. [`feature-protocol.md`](feature-protocol.md) §Module discipline: DTO names should read like the requirement ("Person Record", "Display ID"), not like the implementation. *When violated:* an `internal/<domain>/<domain>_infra.go` file with no domain terms in the type names. |
| 23 | Estimate to Avoid Surprises | ⚠️ | — (philosophy / technique, not a principle) | [`rpci.md`](rpci.md) Plan includes "files touched, success criteria, regression net" but no time estimate. The "Bias toward action" rule absorbs this. *When violated:* a slice ships that touches 15+ files when the plan estimated 3. *How to apply:* if a slice's actual footprint is 5x the estimate, the slice is doing two things; split it. |
| 24 | Iterate the Schedule with the Code | ➖ | — (philosophy / technique, not a principle) | N/A. Framework ships docs + scripts; no schedule to iterate. |
| 25 | Keep Knowledge in Plain Text | ✅ | — (philosophy / technique, not a principle) | Every config in agent-stack is plain text (Markdown, shell, JSON in `templates/`). No binary configs. |
| 26 | Use the Power of Command Shells | ✅ | — (philosophy / technique, not a principle) | `scripts/*.sh` (`backfill-labels.sh`, `check-core-stack-agnostic.sh`, `check-mutations.sh`, `check-security.sh`, `dedupe-skills.sh`, `init.sh`, `sync-labels.sh`) + `scripts/build_tip_index.py` + `scripts/splice_tip_index.py` + the per-addendum Makefile / `package.json` targets. *How to apply:* if a step needs to run twice, it belongs in a script + a Makefile target. Manual repetition is the violation. |
| 27 | Achieve Editor Fluency | ➖ | — (philosophy / technique, not a principle) | N/A. Agent-context; not a framework concern. |
| 28 | Always Use Version Control | ✅ | — (philosophy / technique, not a principle) | The entire branching model in [`commit-and-branch.md`](commit-and-branch.md). Every change goes through git; the framework's own commits follow Conventional Commits. *How to apply:* every change goes through git; every commit has a message; every PR has a body. A change outside git is not a change. |
| 29 | Fix the Problem, Not the Blame | ⚠️ | — (philosophy / technique, not a principle) | Implicit in CHANGELOG tone ("two compounding bugs in X" — no person named) but no stated rule. *When violated:* a commit message names a person ("@alice broke this"). *How to apply:* a fix commit names the *bug*, the *root cause*, and the *regression net*. Person names never appear in commit messages. |
| 30 | Don't Panic | ➖ | — (philosophy / technique, not a principle) | N/A. No incident-response flow at framework level. |
| 31 | Failing Test Before Fixing Code | ✅ | — (philosophy / technique, not a principle) | [`tdd.md`](tdd.md) red-green-refactor protocol is the operational form. Step 1 ("RED") explicitly: write the failing test first. *How to apply:* the first commit in a bug-fix slice is the failing test; the second is the fix that turns it green. A fix without a preceding failing test is a Tier 3 maintenance commit, not a Tier 2 vertical. |
| 32 | Read the Damn Error Message | ✅ | §1.6 Dead Programs | [`tdd.md`](tdd.md) §"The failure modes TDD prevents" — failure class #1 (Invoker wiring) mandates asserting the response shape AND the post-click URL AND the DOM state (not "we got an error somewhere"). *How to apply:* a panic with a clear message is the signal; a swallowed panic with a generic toast is the violation. |
| 33 | "select" Isn't Broken | ✅ | §1.6 Dead Programs | [`bug-patterns.md`](bug-patterns.md) §'Debugging workflow' step 5 pins a five-step 'don't blame the framework by default' checklist. *How to apply:* before patching around a framework / compiler / runtime behavior, prove it. The default assumption is *your code is wrong*; the framework is right ~99% of the time. |
| 34 | Don't Assume It—Prove It | ✅ | §1.6 Dead Programs | [`tdd.md`](tdd.md) §"What's the seam?" + the per-layer recipes (handler test, smoke probe, migration test) mandate asserting the actual state, not the expected state. *How to apply:* a function's doc-comment carries the per-iter SQL footprint (count of SELECTs, INSERTs, transactions); the test asserts the footprint, not just the output. |
| 35 | Learn a Text Manipulation Language | ➖ | — (philosophy / technique, not a principle) | N/A at the framework level. Per-adopter concern. |
| 36 | You Can't Write Perfect Software | ✅ | §1.5 Design by Contract | [`laws.md`](laws.md) §"No unguarded re-entrant UI calls" + §"Tier-0 docs have a size ceiling" are earned-by-real-bug laws. *How to apply:* every error path either crashes early or surfaces a clear toast; a silent fallback (returning `nil, nil` on error, swallowing a panic) is the violation. |
| 37 | Design with Contracts | ✅ | §1.5 Design by Contract | [`tdd.md`](tdd.md) §"Contract touch" is the prospective function- and boundary-contract rule; per-addendum architecture tests enforce package contracts. *How to apply:* every new or materially changed public seam documents relevant caller obligations, observable guarantees, failure/state semantics, and retry/concurrency behavior; its RED test proves those claims. Skip mechanical edits and untouched code. Prefer types, constraints, typed errors, and tests over generic runtime assertion helpers. |
| 38 | Crash Early | ✅ | §1.5 Design by Contract | [`laws.md`](laws.md) §"No unguarded re-entrant UI calls" — crashing early preserves the UI thread. Per-addendum: the typed-attribute swap allowlist (e.g. `htmxattr.Mux` in Go) panics at render time on an invalid value. *How to apply:* an unreachable code path should panic, not silently return. The panic is the agent's "the world is broken" signal; swallowing it is the violation. |
| 39 | Use Assertions to Prevent the Impossible | ✅ | §1.5 Design by Contract | Per-addendum typed builders + DOM-ID registries prevent invalid states at construction time. The doc-comment floor enforces the assertion-via-documentation pattern. *How to apply:* prefer types, builders, database constraints, validation, and typed errors. Use a runtime panic only for a developer-created impossible state; never panic for ordinary user input, recoverable I/O, or third-party failure. |
| 40 | Finish What You Start | ⚠️ | — (philosophy / technique, not a principle) | The pattern lives in adopting repos via `defer` (Go) / `try/finally` (Python) / effect-cleanup (React). [`session-protocol.md`](session-protocol.md) names the principle implicitly but no framework-level guard test pins it. *When violated:* a resource opened without a defer / unsubscribe / cleanup. *How to apply:* every `Open()` / `Lock()` / goroutine launch is paired with `defer Close()` / `defer Unlock()` / a context-aware wait. |
| 41 | Act Locally | ⚠️ | — (philosophy / technique, not a principle) | [`complexity.md`](complexity.md) §"Two-adapter rule" prescribes local interfaces, but no named rule for "locality of state." Implicit in the deep-module discipline (variables live at the function or module scope, not at the package scope). *When violated:* a package-level mutable variable. *How to apply:* a `var foo = ...` at the package level is the violation; pass the value into the function or hold it on the per-process struct. |
| 42 | Take Small Steps—Always | ✅ | §1.10 Take Small Steps | [`rpci.md`](rpci.md) §I — Implement: "the first slice is the only slice that runs in the same session." Fresh-context-per-slice is the operational form. *How to apply:* a slice plan that lists >5 files touched is doing two things; split it. |
| 43 | Avoid Fortune-Telling | ✅ | — (philosophy / technique, not a principle) | [`session-protocol.md`](session-protocol.md) §"YAGNI" + [`complexity.md`](complexity.md) §"Strategic programming framework" + [`feature-protocol.md`](feature-protocol.md) §"Two-adapter rule". *When violated:* a slice adds an interface or a config field "for the future." *How to apply:* the rule is "no feature PR ships a parameter that no caller passes." Delete the parameter or file the follow-up issue. |
| 44 | Decoupled Code Is Easier to Change | ✅ | §1.7 Law of Demeter | [`complexity.md`](complexity.md) deep-module discipline is the operational form. The DTO-at-the-seam rule pins the per-package decoupling. *How to apply:* a chain like `result := a.B().C().D()` is a Demeter violation; pass the value or expose a facade method. |
| 45 | Tell, Don't Ask | ⚠️ | §1.7 Law of Demeter | [`feature-protocol.md`](feature-protocol.md) §"Module discipline — service is the seam" prescribes telling the service to do the work, not asking the model for its data. *When violated:* a templ file imports `internal/<pkg>` directly instead of the service's DTO. *How to apply:* the seam is the service interface; expose a DTO, not the persistence struct. |
| 46 | Don't Chain Method Calls | ➖ | §1.7 Law of Demeter | N/A as a stated rule; [`complexity.md`](complexity.md) deep-module discipline covers the same concern implicitly. |
| 47 | Avoid Global Data | ⚠️ | §1.2 Orthogonality | Per-adopter concern. [`complexity.md`](complexity.md) prescribes a model-without-UI-imports boundary; the "no package-level mutable state" rule is implicit in the deep-module discipline. *When violated:* a `var foo = make(...)` at package level. *How to apply:* hold the value on the per-process struct; pass the struct pointer into every consumer. |
| 48 | If It's Important Enough To Be Global, Wrap It in an API | ✅ | §1.2 Orthogonality | `addenda/go-htmx.md` §"Stack laws" gives the worked example: `(*App).guardedSaveFileDialog` wraps the dangerous thing (the OS dialog) in an API that adds re-entry protection. *How to apply:* if the global is unavoidable (a system handle, a process-wide config), wrap it in a struct method that adds the safety invariant. |
| 49 | Programming Is About Code, But Programs Are About Data | ✅ | §1.2 Orthogonality | [`complexity.md`](complexity.md) §"Deep-module discipline" prescribes DTOs as the cross-boundary value type. The audit-probe pattern (per the adopting repo's audit chain) asserts on data shape, not on code paths. *How to apply:* a handler that returns a service struct is the violation; the handler returns a viewmodel DTO, the viewmodel maps the service struct. |
| 50 | Don't Hoard State; Pass It Around | ⚠️ | §1.2 Orthogonality | [`code-changes.md`](code-changes.md) prescribes arguments over global state implicitly, but no named rule. *When violated:* a function reads from a package-level variable instead of taking the value as a parameter. *How to apply:* function arguments over package-level state; the per-addendum `[data-*]` initializer pattern is the recent worked example. |
| 51 | Don't Pay Inheritance Tax | ➖ | §1.2 Orthogonality | N/A as a framework rule; the type-system-agnostic stance means each adopter inherits whatever their language provides. Composition is the only path; the rule is implicit and trivially satisfied by every framework binding. |
| 52 | Prefer Interfaces to Express Polymorphism | ⚠️ | §1.2 Orthogonality | Go interfaces are the operational form (per `addenda/go-htmx.md` worked examples): services expose behavior through interface types, not concrete structs. *When violated:* a consumer that imports the concrete service struct. *How to apply:* the consumer imports an interface, the framework binding wires the concrete. |
| 53 | Delegate to Services: Has-A Trumps Is-A | ➖ | §1.2 Orthogonality | N/A in Go (and most agent-stack target languages). Composition is the only path; the rule is implicit and trivially satisfied by every framework binding. Other languages with inheritance (Python, TS) get this for free by the deep-module discipline ([`complexity.md`](complexity.md) §"Decomplect"). |
| 54 | Use Mixins to Share Functionality | ➖ | — (philosophy / technique, not a principle) | N/A in Go (no mixins). Embedding structs is the closest analog; the per-addendum dialog-guard mutex and the per-handler `inFlight` pattern (per `addenda/go-htmx.md` §"Stack laws") are embedded once and reused. *When violated:* a struct copy-pastes a method instead of embedding the type that owns it. |
| 55 | Parameterize Your App Using External Configuration | ✅ | — (philosophy / technique, not a principle) | The Makefile / `package.json` + `.github/workflows/*.yml` + `templates/CONTEXT.md.tmpl` are the build-time config. Per-adopter external config (env vars, settings files, `local_settings` analog) is a per-stack pattern. *How to apply:* a constant in source code that the user might want to change is the violation; move it to a config file or to the Makefile. |
| 56 | Analyze Workflow to Improve Concurrency | ✅ | §1.9 Temporal Coupling | The per-addendum export flow (PDF / JSON / archive) is jobs-based; the user gets a toast + the jobs page updates in parallel. The toast-header contract decouples the click from the work. *How to apply:* a handler that does the work inline (blocks the response for >500ms) is the violation; move the work to a job, return a 202 with a job ID. |
| 57 | Shared State Is Incorrect State | ✅ | — (philosophy / technique, not a principle) | The dialog-guard mutex + the per-process struct pattern (e.g. Wails `App`, Electron main, Tauri main) + the per-job worker context. [`laws.md`](laws.md) §"No unguarded re-entrant UI calls" is the operational form. *How to apply:* a goroutine / handler / worker that reads/writes a package-level variable is the violation; pass the per-process struct pointer, the worker owns no state of its own. |
| 58 | Random Failures Are Often Concurrency Issues | ✅ | — (philosophy / technique, not a principle) | Per-addendum race-stress workflow (e.g. `audit/race-stress.yml`) + per-adopter property-test gate (e.g. `internal/dates` dates property test). [`bug-patterns.md`](bug-patterns.md) §"Concurrency / dependency correctness" lists the AI-amplification evidence. *How to apply:* a flaky test is concurrency; run with `-race` (Go) or the language's race detector before assuming the test is broken. |
| 59 | Use Actors For Concurrency Without Shared State | ⚠️ | — (philosophy / technique, not a principle) | The per-process struct (Wails `App`, Electron main, Tauri main) is passed by reference; not technically an actor. The per-addendum `jobs.Start` pattern (e.g. `internal/jobs/jobs.go` in the Go addendum) is the closest operational form. *When violated:* a goroutine / worker that mutates a value owned by the caller. *How to apply:* the rule is "the goroutine owns its state; the caller passes inputs and reads outputs through channels or a return-only interface." |
| 60 | Use Blackboards to Coordinate Workflow | ➖ | §1.9 Temporal Coupling | N/A. Single-user single-process apps; no blackboard pattern. |
| 61 | Listen to Your Inner Lizard | ⚠️ | §1.9 Temporal Coupling | Implicit. The "agent inner lizard" surfaced in the over-decomposition anti-pattern ([`commit-and-branch.md`](commit-and-branch.md) §"Anti-patterns"). [`rpci.md`](rpci.md) §I — Implement mandates fresh-context-per-slice. *When violated:* the slice plan says "I'll figure out the shape as I go." *How to apply:* if a plan feels wrong, the plan is wrong; surface the concern in the slice plan's "Principle warnings" block. |
| 62 | Don't Program by Coincidence | ✅ | §1.11 Program Deliberately | The per-adopter property-test gate (e.g. `internal/dates` dates property test) is the operational form. The CHANGELOG entry tone is "root cause: X; fix: Y" — never "happened to work." [`rpci.md`](rpci.md) §P — Plan mandates "Decisions to confirm" surfaced explicitly. *When violated:* a commit message that doesn't explain *why* the fix works. *How to apply:* the slice plan's "regression net" line names the test that proves the fix; a fix without that line is coincidence. |
| 63 | Estimate the Order of Your Algorithms | ⚠️ | §1.12 Algorithm Speed | The per-addendum stress test (e.g. `TestStressEventAttachDetachRoundTrip` in the Go addendum) per-iter SQL footprint is the closest form. Not a stated rule for non-DB code paths. *When violated:* a function in the model's heavy paths (DB queries, batch ops, background jobs) whose doc-comment has no SQL footprint. *How to apply:* the doc-comment lists "O(N) reads, O(1) writes"; a doc-comment without the footprint is incomplete. |
| 64 | Test Your Estimates | ✅ | §1.12 Algorithm Speed | Per-addendum stress-test directory (e.g. `tools/tune/stress/`) + per-adopter race-stress workflow (e.g. `.github/workflows/race-stress.yml`). The race-detector step is the live regression net that catches drift between the estimate and reality. *How to apply:* every slice that touches the model's heavy paths runs the stress suite locally before the PR opens. |
| 65 | Refactor Early, Refactor Often | ✅ | §1.13 Refactoring | [`complexity.md`](complexity.md) is the operational form. The per-adopter Event Records refactor (sibling-table rename) is the canonical worked example. *How to apply:* the slice plan's "When to refactor" checklist (5 triggers: DRY violation, non-orthogonal, knowledge improved, requirements evolve, performance) — a slice that hits one trigger files the refactor as a sibling issue. |
| 66 | Testing Is Not About Finding Bugs | ✅ | §1.13 Refactoring | The audit cadence is the operational form. Per-adopter audit cycles (e.g. the DixieData #531, #539, #540, #542 cluster) each surfaced a *class* of bug the tests themselves couldn't catch. *How to apply:* the audit probe (Playwright or analog) is the second test surface; a slice that passes unit tests but fails the smoke probe is incomplete. |
| 67 | A Test Is the First User of Your Code | ✅ | §1.13 Refactoring | [`tdd.md`](tdd.md) Step 1 is "RED: write the failing test first." Per-addendum RED + GREEN shipping as a single reviewable commit is the worked example. *How to apply:* the slice plan's first commit is the failing test; the second is the fix. A slice with no RED commit is not TDD. |
| 68 | Build End-To-End, Not Top-Down or Bottom Up | ✅ | §1.4 Tracer Bullets | RPCI tracer-bullet slice 1 is the operational form. Every Tier 2 vertical slice crosses every layer (templ + htmx + JS + Go handler + DB). *When violated:* a "backend slice" that ships the handler but no UI, or a "frontend slice" that ships the templ but no handler. *How to apply:* the slice plan template requires both the apply-site URL and the smoke probe bullet; a plan without both is not Tier 2. |
| 69 | Design to Test | ✅ | §1.11 Program Deliberately | [`addenda/go-htmx.md`](../addenda/go-htmx.md) HTMX-specific guard tests (architecture test + orphan-handler probe + smoke-probe per-apply-site contract) — three independent test surfaces. *How to apply:* a new handler without an audit probe entry is the violation; the audit probe is the test that catches the "handler returns 200 but renders nothing" bug class. |
| 70 | Test Your Software, or Your Users Will | ✅ | §1.4 Tracer Bullets | The smoke-probe per-apply-site contract (per [`feature-protocol.md`](feature-protocol.md) §"Backend-first law" + [`tdd.md`](tdd.md) §"Per-layer recipes") catches the "shipped but invisible" bug class. *When violated:* a feature ships without the smoke probe bullet; the user finds the bug. *How to apply:* the slice plan template lists smoke probes per apply-site; a missing probe is the violation. |
| 71 | Use Property-Based Tests to Validate Your Assumptions | ✅ | §1.17 Pragmatic Projects | The per-adopter property test (e.g. `internal/dates/dates_property_test.go` using `pgregory.net/rapid` in the Go addendum) is the operational form. Documented in [`tdd.md`](tdd.md) §"Per-layer recipes." *How to apply:* a function whose doc-comment claims "handles edge cases X, Y, Z" without a property test is the violation; the property test enumerates the input space. |
| 72 | Keep It Simple and Minimize Attack Surfaces | ✅ | — (philosophy / technique, not a principle) | The "no new component primitives" rule from the per-addendum Markdown cheatsheet work is the recent example. [`complexity.md`](complexity.md) deep-module discipline is the standing operational form. *When violated:* a slice adds a new templ primitive when an existing one (Foldout, Pill, EmptyState) would carry the case. *How to apply:* before adding a new primitive, grep for existing primitives + read the per-addendum components/conventions doc. |
| 73 | Apply Security Patches Quickly | ❌ | — (philosophy / technique, not a principle) | [`scripts/check-security.sh`](../scripts/check-security.sh) template ships, but no per-addendum CI workflow runs `govulncheck` or `gosec` on a cadence inside the framework itself. Deps are updated when a PR forces it, not on a schedule. *Open gap:* add `govulncheck ./...` to a weekly workflow; add `gosec ./...` to the audit chain. *How to apply until then:* `go list -m -u all` every Friday; file a follow-up issue per dependency that has a CVE. |
| 74 | Name Well; Rename When Needed | ⚠️ | — (philosophy / technique, not a principle) | The glossary tier-2 rename pattern (per [`glossary-discipline.md`](glossary-discipline.md) §"Renaming a term") is the canonical example. *When violated:* a new type name that's a synonym for an existing one ("Worker" + "JobRunner" + "TaskProcessor" in the same package). *How to apply:* the slice plan's "files touched" line lists the new name; if the name is a synonym, rename one of them in the same slice. |
| 75 | No One Knows Exactly What They Want | ✅ | — (philosophy / technique, not a principle) | RPCI: "Plan → Critique" with explicit user gate. The "the user is the chat" capture rule in [`session-protocol.md`](session-protocol.md) §"Capturing decisions". *How to apply:* a slice plan that ships without a user sign-off is the violation; the Plan phase ends only when the user types "approved". |
| 76 | Programmers Help People Understand What They Want | ✅ | — (philosophy / technique, not a principle) | The slice plan + apply-sites checklist in every feature issue ([`issues/feature-template.md`](../issues/feature-template.md)) is the operational form. The user sees the *full shape* of the change before code lands. *How to apply:* the slice plan template lists the apply-sites (which pages the change touches) and the smoke probe; if either is missing, the user can't visualize the change. |
| 77 | Requirements Are Learned in a Feedback Loop | ✅ | — (philosophy / technique, not a principle) | RPCI's "fresh context per slice" ([`rpci.md`](rpci.md) §I) is the strongest form. The next session picks up the new state and refines. *When violated:* a slice ships with a "complete" spec that was never re-validated. *How to apply:* every slice ends with a `make freshness` + a per-addendum audit run; the next session's slice plan re-reads the previous slice's CHANGELOG bullet and asks "does this still match what the user said?" |
| 78 | Work with a User to Think Like a User | ⚠️ | — (philosophy / technique, not a principle) | Implicit in the user's "go ahead and tackle X" pattern, but no stated cadence. The per-adopter audit cycle is the closest scheduled form. *When violated:* a slice ships without the user manually clicking through the change on a real archive. *How to apply:* the slice plan's "Verification" line lists the manual click-through; a slice without it is incomplete. |
| 79 | Policy Is Metadata | ✅ | §1.8 Metaprogramming | The per-addendum DOM-ID registry (e.g. `internal/uiids` in Go) + the architecture-test forbidden-import map + the linter rule files (e.g. `.mutesting.yaml`) are the operational form. Policy lives in data, not code. *When violated:* a hardcoded list of valid swap targets in the templ layer (the data should live in the registry). *How to apply:* the rule is "if a value appears in 3+ places, it lives in a registry." |
| 80 | Use a Project Glossary | ✅ | §1.8 Metaprogramming | The project glossary (typically `CONTEXT.md` at the repo root, per [`glossary-discipline.md`](glossary-discipline.md)) is the single source. The "Flagged ambiguities" section is the regression net for vocabulary drift. *How to apply:* a new term in a doc or comment that isn't in the glossary is the violation; add the term + the `_Avoid_` list to the glossary in the same commit. |
| 81 | Don't Think Outside the Box—Find the Box | ✅ | — (philosophy / technique, not a principle) | [`complexity.md`](complexity.md) §"Strategic programming framework" + [`rpci.md`](rpci.md) §"Cutting the Gordian Knot" (the 6-question checklist per §2.4). *How to apply:* §2.4 is the 6-question checklist; a slice that answers "yes" on Q6 ("don't have to do it at all") files the abandonment as a sibling issue. |
| 82 | Don't Go into the Code Alone | ⚠️ | — (philosophy / technique, not a principle) | Implicit (the user + agent pairing) but no stated rule. The PR body + the slice plan review are the closest form. *How to apply:* a slice that ships without a PR description is the violation; the PR body is the conversation that catches the "you missed X" finding. |
| 83 | Agile Is Not a Noun; Agile Is How You Do Things | ➖ | — (philosophy / technique, not a principle) | N/A. (Solo / small-team framework; no team-level agile ceremony. The *spirit* is satisfied by the slice cadence + the "ship the smallest useful unit" discipline.) |
| 84 | Maintain Small Stable Teams | ➖ | — (philosophy / technique, not a principle) | N/A. Solo / small-team framework. |
| 85 | Schedule It to Make It Happen | ⚠️ | §1.15 Ubiquitous Automation | The `make freshness` gate (per [`commit-and-branch.md`](commit-and-branch.md) §"Push verification") + the per-PR CI + the per-addendum weekly cron are the closest form. But "scheduled reflection / learning" is not yet on the calendar. *When violated:* a quality improvement ships behind a feature because nobody scheduled the work. *How to apply:* the slice plan template lists a "Cadence" line; a cadence without a calendar entry is the violation. |
| 86 | Organize Fully Functional Teams | ➖ | §1.15 Ubiquitous Automation | N/A. |
| 87 | Do What Works, Not What's Fashionable | ⚠️ | — (philosophy / technique, not a principle) | Implicit in the architecture choices (no React, no ORM, no microservices — `addenda/` invites per-stack extension without mandating any of them). No stated policy. *When violated:* a "rewrite in [framework]" pitch without a 1-line problem statement. *How to apply:* the architecture choices are listed in [`adr-discipline.md`](adr-discipline.md) + the adopting repo's `docs/adr/`; a new framework needs its own ADR with the alternatives considered and the rejected option's rationale. |
| 88 | Deliver When Users Need It | ✅ | — (philosophy / technique, not a principle) | The Tier 3 apply-site rule + the slice-1-only-per-session rule = ship the smallest useful unit as fast as possible. *When violated:* a 2-week polish cycle that ships nothing. *How to apply:* the slice plan's "Verification" line lists the manual click-through; the slice ships when the click-through is green. |
| 89 | Use Version Control to Drive Builds, Tests, and Releases | ✅ | — (philosophy / technique, not a principle) | The per-adopter `.github/workflows/{build,test,audit,race-stress}.yml` are the operational form. Every PR triggers the full chain. *When violated:* a manual build step that runs outside CI. *How to apply:* the workflow YAML files are the source of truth; if a step isn't in a workflow, it doesn't run. |
| 90 | Test Early, Test Often, Test Automatically | ✅ | §1.15 Ubiquitous Automation | Per-PR + per-push + weekly race-stress + per-promotion freshness. *How to apply:* a slice that ships without a CI-green check is the violation; the PR is not mergeable until the green check is in the PR body's status line. |
| 91 | Coding Ain't Done 'Til All the Tests Run | ✅ | §1.15 Ubiquitous Automation | The "RED + GREEN + adjacent-behavior sweep" in [`tdd.md`](tdd.md) + the package-floor + the smoke-probe per-apply-site contract. *When violated:* a slice ships with one passing test + one skipped test + one failing test. *How to apply:* the slice's PR description lists every test status; a slice without the full matrix is not mergeable. |
| 92 | Use Saboteurs to Test Your Testing | ❌ | — (philosophy / technique, not a principle) | No mutation testing. [`scripts/check-mutations.sh`](../scripts/check-mutations.sh) template ships the dispatch logic but no framework package runs it. *Open gap:* add a mutation testing step to the audit chain (e.g., `go-mutesting` for Go, `stryker` for JS). *How to apply until then:* every PR review asks "does this test actually catch the bug it's named for?"; if the test is "expect sum of [1,2] == 3," the test is too trivial to trust. |
| 93 | Test State Coverage, Not Code Coverage | ⚠️ | — (philosophy / technique, not a principle) | The smoke probes assert state (response shape, URL, DOM) not just code paths. But there is no coverage metric on the state surface yet. *When violated:* a test that asserts the handler returns 200 but never reads the response body. *How to apply:* the per-adopter audit probe template asserts the full page state; a probe that asserts only the status code is incomplete. |
| 94 | Find Bugs Once | ✅ | §1.15 Ubiquitous Automation | Every `fix:` commit in CHANGELOG grows a regression test. The per-adopter `fix:` commits with regression nets in [`bug-patterns.md`](bug-patterns.md) are the audit trail. *How to apply:* the slice plan's "regression net" line names the test; a fix commit without a regression test name is the violation. |
| 95 | Don't Use Manual Procedures | ✅ | §1.15 Ubiquitous Automation | [`scripts/init.sh`](../scripts/init.sh) + [`scripts/backfill-labels.sh`](../scripts/backfill-labels.sh) + [`scripts/check-core-stack-agnostic.sh`](../scripts/check-core-stack-agnostic.sh) + [`scripts/check-mutations.sh`](../scripts/check-mutations.sh) + [`scripts/check-security.sh`](../scripts/check-security.sh) + [`scripts/dedupe-skills.sh`](../scripts/dedupe-skills.sh) + [`scripts/sync-labels.sh`](../scripts/sync-labels.sh) + the per-addendum Makefile targets automate the build + probe chain. *When violated:* a step in the README that says "run X then Y then Z." *How to apply:* every multi-step procedure belongs in a script + a Makefile target; a README without a script is the violation. |
| 96 | Delight Users, Don't Just Deliver Code | ⚠️ | §1.17 Pragmatic Projects | [`session-protocol.md`](session-protocol.md) §"Bias toward action" + [`feature-protocol.md`](feature-protocol.md) §"Apply sites" carry the tip. No formal "delight" rule ships at the framework level; the per-addendum docs carry the worked examples. *When violated:* a slice ships the minimum required by the spec and nothing else. *How to apply:* the slice plan's "Verification" line lists the manual click-through; a click-through that ends with "works as specified" but no extra good moment is the violation. |
| 97 | Sign Your Work | ✅ | — (philosophy / technique, not a principle) | The CHANGELOG fixship-by-fixship attribution is the operational form. The "Ticket close-out law" in [`feature-protocol.md`](feature-protocol.md) requires the commit hash + verification output + acceptance criteria on every closing commit. *How to apply:* every closing commit ends with a `Verification:` block that pastes the test output; a closing commit without the block is unsigned. |
| 98 | First, Do No Harm | ✅ | — (philosophy / technique, not a principle) | The dialog-guard Law ([`laws.md`](laws.md) §"No unguarded re-entrant UI calls") + the "no feature PR ships a backend surface without a UI apply-site" Law ([`feature-protocol.md`](feature-protocol.md) §"Backend-first law") + the per-iter SQL footprint pattern. *When violated:* a slice that breaks a non-target surface. *How to apply:* the slice plan's "regression net" line lists every adjacent surface the change could touch; a slice without that list is a harm candidate. |
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
  [`docs/audit/pragmatic-programmer-audit-2026-07.md`](../docs/audit/pragmatic-programmer-audit-2026-07.md)
  — the per-tip *evidence* (historical artifact).
- The regenerator:
  [`scripts/build_tip_index.py`](../scripts/build_tip_index.py)
  — reads the audit doc, writes `.scratch/appendix-final.md`.
  Run after every state change; then run this script to splice.
- The splicer:
  [`scripts/splice_tip_index.py`](../scripts/splice_tip_index.py)
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
chapter structure.