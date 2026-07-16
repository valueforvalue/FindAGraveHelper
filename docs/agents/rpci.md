# RPCI — Research, Plan, Critique, Implement

The default workflow for non-trivial work on a repo that
adopts agent-stack. The acronym "RPCI" is the invocation
form ("do RPCI on this", "run RPCI before implementing").

The flow is procedural, not architectural. It governs *how
the agent works until the code ships*. Architectural shape
comes from the repo's glossary + laws + cross-layer contract.

## When to use

| Task shape | Flow |
|---|---|
| One-line bug fix, clear repro | **Skip RPCI.** Patch + regression test + commit. |
| Multi-file bug, root cause unknown | **R1 + I.** Research enough to confirm the fix, then implement. Skip explicit Plan / Critique. |
| Feature / refactor touching 3+ files | **Full RPCI.** All four phases, even if Plan is one paragraph. |
| Subsystem redesign, 6+ files across layers | **Full RPCI + design artifact.** Write the artifact under `docs/designs/`. The RPCI phases still gate the work; the artifact is the durable output. |

The "Bias toward action" rule from
[`session-protocol.md`](session-protocol.md) still applies:
don't over-procedure a small task. The RPCI overhead is paid
once; under-using it on a big task costs more than over-using
it on a small one.

## The four phases

### R — Research

**Goal:** Understand the problem space well enough to write a
plan that doesn't re-ask the questions you should have
answered in recon.

**Activities:**

- Read the affected files.
- Read the bug-pattern catalog for the area you're touching.
  Recurring bug patterns are documented with `Find it:` greps.
- Read related issues (use the issue tracker CLI for context).
- Read prior commits on the same files (`git log --oneline -- <path>`).
- Bench / measure when the claim is performance.

**Output:** A short prose summary — what's broken (or to be
built), the call sites, the constraints, the bench numbers if
any. Don't write a plan yet.

**Stop when:** You can articulate the root cause (or, for a
feature, the surface area) in two sentences.

### P — Plan

**Goal:** Lay out the change as a sequence of atomic,
testable slices that map to commits.

**Activities:**

- **Tracer-bullet first slice (non-negotiable for any plan
  with 2+ slices).** Slice 1 must be the smallest end-to-end
  slice: schema (if any) → service → handler → ONE UI
  apply-site → regression net → green. If the feature lists
  multiple apply-sites in the issue, Slice 1 covers exactly
  one and the critical path is proven before the others are
  scoped. See [`feature-protocol.md`](feature-protocol.md)
  for the full rule. This prevents the AI-slop pattern of
  horizontal layers built in isolation before the critical
  path is validated.
- Decompose the remaining change into vertical slices. A
  slice is end-to-end across layers and produces something
  a user (or a probe) can verify.
- For each slice, list: files touched, success criteria, the
  regression net.
- Identify the commit/PR boundary. One commit per reviewable
  unit, per [`commit-and-branch.md`](commit-and-branch.md).
- Surface decisions that need user input. **Don't hide them
  in the body of a slice** — list them as `## Decisions` at
  the top so the Critique phase catches them.

**Output:** A plan document. Format:

```markdown
# Plan: <title>

## Decisions to confirm
- Q1: ...

## Principle warnings
- (per [`pragmatic-principles.md`](../pragmatic-principles.md)
  §"warn + cite protocol" — name, cite, rationale, cleanup)

## Slice 1 (tracer bullet — fully detailed)
- Files: <paths>
- Success criteria: <observable>
- Regression net: <test/probe>

## Subsequent slices (stub only)
- Slice 2: <one-line shape>
- Slice 3: <one-line shape>
```

The `## Principle warnings` block is **required** when a slice
violates a principle documented in
[`pragmatic-principles.md`](../pragmatic-principles.md)
(DRY, orthogonality, Law of Demeter, MVC, metaprogramming,
temporal coupling, refactoring, etc.). See that doc's §"warn
+ cite protocol" for the four-part shape. The user signs off
on the violation as part of the Critique gate, and the
rationale + cleanup plan land verbatim in the commit message
+ CHANGELOG bullet. **Undocumented principle violations are
bugs**, same as undocumented legal violations.

**Stub-vs-detailed rule:** Slice 1 is the only slice that
ships in this session. Slice 2+ get one-line stubs because the
agent cannot predict their shape before Slice 1 ships.

### C — Critique

**Goal:** Stress-test the plan before any code moves.

**Activities:**

- Use the grilling skill (or its surface form) to interview
  the user about the plan. Aim for 3-5 focused questions, not
  20. The questions should be about decisions and trade-offs,
  not about things the plan already nailed.
- For each decision in `## Decisions`, present the trade-off
  and ask for the call. Provide a recommended option with
  "(Recommended)" appended.
- For each slice, ask: "Is this slice's success criterion
  testable in 5 minutes? Does the regression net catch a
  future regression, or does it just confirm the fix?"
- Check: does the plan match `commit-and-branch.md`?
  (One commit per reviewable unit? Bug-pattern greps run?
  CHANGELOG updated?)
- If the critique surfaces a missing slice, a wrong commit
  boundary, or a decision the user wants to revisit, revise
  the plan and re-critique. Don't move to Implement with
  open questions.

**Output:** A revised plan, approved by the user. The user's
explicit "Approve, start" or "looks good, go" is the gate.

**Autonomous clause (opt-in per session).** When the user
replies with one of "all recommended" / "take the recommended
defaults" / "yes to all", the agent MAY treat the response as
explicit approval of every decision the agent surfaced in the
Plan or Critique phase of the same session, and proceed to
the Implement phase without re-asking. The agent MUST:

1. Echo the list of approved decisions in the implementation
   commit message or PR body for traceability.
2. Continue to surface any *new* decisions discovered during
   Implementation for explicit approval before acting.
3. NOT treat the autonomous clause as blanket approval of
   future RPCI sessions — it is per-session and per-decision-list.

The agent MUST NOT auto-progress on:

- System reminders about open todos
- Absence of user response (silence is not consent)
- Vague or partial responses

### I — Implement

**Goal:** Execute the plan slice by slice, with regression
tests confirming each slice before the next starts.

**The first slice is the only slice that runs in the same
session.** Once Slice 1 is green and the user has signed off,
close the session and let the next slice start in a fresh
context window. The same agent building six slices
back-to-back is the AI-slop failure mode.

**Activities per slice:**

1. Read the files you'll touch (recon is cheap, do it again).
1.5. **RED: write the failing acceptance test first.** Per
   [`tdd.md`](tdd.md), the test pins the slice's user-facing
   acceptance criterion. Run it; confirm it fails for the
   right reason. No slice code yet.
2. **GREEN: make the change.** Smallest diff that satisfies
   the failing test. No drive-by refactors. Run the RED
   test green. Then run the adjacent-behavior sweep.
3. Add the regression net. Per-layer: unit test, handler
   test, integration test, smoke probe.
4. Run the targeted test + the package's full short suite.
5. Run smoke probes that touch the area.
6. Update CHANGELOG.
7. **Critique sub-step (mandatory before commit).** Before
   committing, run the *self-review pass*: enumerate three
   things that could be wrong with this slice.
   - Run the *deletion test*: would removing this code
     break the acceptance criterion? If no, the
     implementation does not match the spec
     (*intent mismatch*, DAPLab #3).
   - Run the *noise test*: does this slice introduce
     unmotivated complexity? Naming, indirection, or
     abstractions no caller needs? Per [Pocock](https://www.aihero.dev/tracer-bullets),
     AI agents routinely ship "while-I'm-here" code that
     solves no stated problem.
   - Run the *scope test*: does this slice touch code
     outside its stated scope? If yes, split or drop it.
   The critique sub-step is non-negotiable for any slice
   that adds more than one file. Skip it only for
   one-line bug fixes with clear repro. Per
   [Stellman](https://www.oreilly.com/radar/ai-code-review-only-catches-half-of-your-bugs/),
   ~50% of LLM-introduced defects are *intent violations*
   that structural review misses; this sub-step is the
   cheap equivalent of an adversarial review pass.
8. Commit. Subject per Conventional Commits prefix + area
   + imperative summary; body explains *why* and references
   the issue.
9. Push branch + open PR (target integration branch).
10. Watch CI. Hand the merge back to the user; don't
    auto-merge.

## Anti-patterns

- **Skipping Critique.** Past sessions shipped plans the user
  would have rejected if asked. Don't let urgency skip the
  gate.
- **Critique as a monologue.** The plan needs real questions,
  not a summary of what the agent already decided.
- **Plan with 10+ slices.** Decompose into a design artifact
  first. The plan's job is to sequence, not enumerate.
- **Implementing during Plan.** Recon, asking questions, and
  writing a plan are all fine. Running build targets that
  mutate state, writing files, or scaffolding handlers is
  not, until the user approves.
- **One commit per slice is not a rule.** Some slices are
  pure refactors with no user-visible effect; some are
  tightly coupled and land as one commit. Rule of thumb: if
  you can write a one-sentence commit message that doesn't
  need "and", it's atomic.

## References

- [`tdd.md`](tdd.md) — slice-internal red-green-refactor
- [`feature-protocol.md`](feature-protocol.md) — slice
  discipline + 3-tier commit rule
- [`session-protocol.md`](session-protocol.md) — agent
  procedural rules