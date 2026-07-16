# Feature Add Protocol

The canonical procedure for adding a new feature to a repo
that adopts agent-stack. Pairs with [`rpci.md`](rpci.md)
(procedural flow) and the issue framework in
`../issues/` (issue filing); this doc owns the
feature-specific decisions, commit shape, and module
discipline.

## Pre-flight checklist

Tick these before any recon:

- [ ] **Glossary** — read the repo's glossary end-to-end. If
      the feature adds a domain concept, propose a glossary
      entry in the issue body.
- [ ] **Flow** — read [`rpci.md`](rpci.md). The four phases
      (Research → Plan → Critique → Implement) apply.
      Features default to **full RPCI** unless one-line
      bug-fix-shaped.
- [ ] **Bug patterns** — read [`bug-patterns.md`](bug-patterns.md)
      §layer for every layer the feature touches.
- [ ] **Cross-layer contract** — read
      [`code-changes.md`](code-changes.md) when the feature
      touches multiple layers.
- [ ] **Index** — read the repo's docs-index to know which
      tier-1/2 docs to load for this task.
- [ ] **TDD + contract anchor** — read [`tdd.md`](tdd.md).
      Every slice pins its user-facing acceptance criterion
      with a failing test BEFORE the slice lands. New
      behavior and materially changed public seams also get
      a contract touch: document caller obligations and
      observable guarantees, then prove relevant claims at
      the seam (see [`tdd.md`](tdd.md) §"Contract touch").
      The TDD protocol sits inside the vertical-slice
      discipline above; it does not replace it.

## When to use

| Task shape | Flow |
|---|---|
| One-line bug fix, clear repro | Skip the protocol. Bug protocol applies. |
| One-commit feature | Lightweight. Issue body has Use case + Acceptance + Regression net. No slice plan. |
| Multi-file feature, 2-3 layers | Full protocol. Use case + Decisions + Apply-sites + Acceptance + Slice plan in the issue body. |
| Subsystem feature, 4+ files | Full protocol + design artifact. Issue body + `docs/designs/<slug>.md`. |
| Cross-cutting, 6+ files, design questions | Full protocol + heavy artifacts (`RESEARCH.md` → `PRD.md` → `TASKS.csv`). |

## Tracer bullets (vertical-slice discipline)

Build a tiny, end-to-end slice first, get feedback, then
expand. AI agents are prone to outrunning their headlights —
building whole layers in isolation before the critical path
is validated. The 3-tier commit rule below is the
enforcement mechanism: every commit is one slice, every
slice crosses every layer, no slice ships without a
regression net running green.

**Hard rule:** do not start the next slice until the
previous commit is green AND the user has seen the working
surface. A fresh context window for each slice is ideal.

**Slice-size rules.** A slice is valid iff all of the
following hold. Cite: [Pocock on tracer bullets](https://www.aihero.dev/tracer-bullets)
("context window constraints make the discipline
non-negotiable") and
[Miller on the codebase as the prompt](https://jeremydmiller.com/2026/06/04/the-codebase-is-the-prompt-wolverine-vertical-slices-and-ai-assisted-development/)
("a slice must fit entirely in one context window").

- The slice's full file set loads into ≤ 50% of the model's
  effective context. If you can't quote every file you'll
  touch from memory, the slice is too big.
- The diff stays under 500 LOC. Above that, the diff
  becomes unreviewable and the acceptance test becomes a
  smoke test rather than a behavioural assertion.
- Each slice has exactly one observable end-to-end user
  behaviour. "Refactor + new feature" is two slices.
- Slice starts in a fresh context. Prior session's working
  memory contaminates plan-vs-implementation reasoning;
  the green/red signal is sharper in a clean window.

These rules are descriptive of successful slices in
practice (per [CodeRabbit's PR audit](https://coderabbit.ai/blog/state-of-ai-vs-human-code-generation-report),
AI PRs above 500 LOC have 1.7× the issue density of
human PRs). Treat them as a heuristic, not a law — but
violating them in a slice plan needs justification in the
plan body.

## The 3-tier commit rule

One commit = one of:

### Tier 1 — user-visible outcome

The whole feature lands in one commit because no
intermediate state is shippable. Rare in single-binary
single-user apps; more common in libraries where one
breaking change is the deliverable.

### Tier 2 — vertical slice across one boundary

A backend vertical (schema + service + handler) OR a UI
vertical (view + JS + audit probe) in one commit, because
alone it doesn't compile or doesn't surface to the user.
**Always paired with at least one matching UI apply-site in
the same PR** (see "Backend-first law" in the repo's laws
doc).

### Tier 3 — apply-site unit

One apply-site = one commit, when each apply-site is
independently significant.

**The rule:** if you can write a one-sentence commit subject
that doesn't need "and", it's atomic. If it needs "and"
twice, decompose.

**Anti-patterns:**

- Per-layer micro-commits (one for schema, one for service,
  one for handler, one for UI). Each independently
  uncompilable. Bundle into a Tier 2 vertical.
- Mega-commit (everything for a feature in one commit).
  Hides the apply-site unit; impossible to revert one slice
  without losing the others.

## Module discipline (deep-module)

### Define the facade before the internals

Write the **public service interface** + **DTO contracts**
BEFORE any internal code. UI and tests cross this seam; the
implementation is invisible behind it.

```pseudo
// Service signature (public seam) — write this first
interface TagService {
    NormalizeName(raw string) string
    UpsertByName(raw string) (Tag, error)
    Attach(personID int64, tagID int64) error
    // ... only methods demanded by acceptance criteria
}

// DTO returned to UI (boundary mapping)
struct TagDTO {
    ID, Name, NormalizedName, CreatedAt
}
```

Internal helpers are private to the package and not in the
interface. If a caller needs them, the seam is wrong.

### Service is the seam

- UI depends on the service's DTOs, never on the persistence
  struct.
- Tests cross the service's interface, not the persistence
  layer.
- If a view file imports the DB / model package to reach a
  struct directly, the seam is broken — add a DTO.

### Deletion test

Would deleting this module break N callers?

- **N == 0** → pass-through, refactor into the caller.
- **N >= 2** → earning its keep, keep the module.
- **N == 1** → borderline; often premature extraction.

### The two-adapter rule

Before adding a new public method to an existing service,
ask: "Does an acceptance criterion demand this method, OR
is there a second adapter that needs it?"

If neither, the method is speculative. Drop it.

### Don't return persistence structs to UI

Map to a DTO at the boundary. Persistence structs can grow
columns without breaking UI.

## Prefactor before slicing

"Look for opportunities to prefactor the code to make the
implementation easier. Make the change easy, then make the
easy change."

Run a lite explore before writing the slice plan: look for
module shapes that will force the slices to take
workarounds, look for facades that the new feature will
leak across, look for existing tests that the new feature
will silently break.

If a prefactor is identified, it ships as a separate slice
*BEFORE* the feature slices. The prefactor is not Tier 1
(no user-visible outcome) — it lands in `### Maintenance`
CHANGELOG and gets its own atomic commit.

## Issue template

The full feature template lives in `../issues/feature-template.md`.
This section summarizes what goes in each section of the
issue body.

**User story** is for the next maintainer, not for the
agent. "I want to organise X by ad-hoc categories" — not
"add a tag table with a many-to-many join."

**Apply sites** is a checklist, not prose. Prose hides
gaps; checkboxes make them visible.

**Glossary changes** are required when the feature
introduces a new domain term, even if it feels obvious. The
glossary is the contract.

**Acceptance criteria** are testable in 5 minutes by a
human with the build.

**Contract touch** names each new or materially changed
public seam (service method, handler, DTO, builder, exported
helper, or durable data boundary), its caller obligations,
and its observable guarantees. Use `N/A — mechanical change`
for formatting, renames, generated output, and other edits
that do not alter behavior. Do not expand the slice to
retrofit untouched code. The matching RED test proves
relevant claims at the seam; see [`tdd.md`](tdd.md)
§"Contract touch".

**Slice plan** mirrors the 3-tier commit rule. Each slice
names its tier in the subject and ships the whole tier in
one commit.

**Principle warnings** are required when a slice is about to
violate a principle documented in
[`pragmatic-principles.md`](pragmatic-principles.md). The
block carries four pieces of information — see
[§"Principle warnings block" below](#principle-warnings-block).
The user signs off on the warning as part of the Plan approval
gate ([`rpci.md`](rpci.md) §C — Critique). Undocumented
violations are bugs.

### Principle warnings block

When a slice is about to **violate a principle** documented in
[`pragmatic-principles.md`](pragmatic-principles.md), the slice
plan carries a `## Principle warnings` block with four pieces
of information. The block makes the violation reviewable;
undocumented violations are bugs.

```markdown
## Principle warnings

- **Principle**: §1.X — <name> (e.g. §1.1 DRY, §1.2
  Orthogonality, §1.13 Refactoring). If no §-number applies,
  name the principle verbatim.
- **Operational form**: which doc / guard test / rule is being
  violated (e.g. "the deep-module rule in `complexity.md`",
  "the forbidden-import test").
- **Rationale**: why this case is a known-and-intentional
  exception. What forces the violation here?
- **Cleanup plan**: when + how the violation gets resolved.
  Usually a follow-up issue filed in the same slice commit,
  with the issue number. If the violation is permanent, say
  so explicitly and cite the principle's "when you might
  violate" entry that covers the case.
```

The rationale + cleanup plan land **verbatim** in the commit
message and the CHANGELOG bullet so the next agent sees the
documented violation when reading the work. When a violation
is the kind that *will recur*, the slice's follow-up commit
extends [`pragmatic-principles.md`](pragmatic-principles.md)
with a "when you might violate" bullet. The doc grows with the
codebase.

## When to load what

| If you're working on... | Read these (in order) |
|---|---|
| Any feature | This file, then the repo's glossary |
| Backend handler / service | `code-changes.md`, `bug-patterns.md` backend section |
| View template / framework wiring | `bug-patterns.md` view section |
| Frontend JS | `bug-patterns.md` frontend section |
| Native dialog | The addendum that owns the stack |
| Database schema | The migration history (latest two) |
| Audit smoke probe | The audit playbook |

## Anti-patterns

- **Ship the backend first, UI later.** Violates the
  backend-first law. Don't ship "backend-only" PRs for
  features.
- **One mega-commit.** Hides slice boundaries; impossible
  to revert one surface.
- **Per-layer micro-commits.** Each uncompilable.
- **Speculative public API.** Adding methods that no
  acceptance criterion demands.
- **Returning persistence structs to UI.** Breaks the seam.
- **Glossary drift.** Adding a feature without updating the
  glossary.
- **Smoke probe missing.** Every UI apply-site needs a
  probe that checks both response shape AND `page.url()`
  after the click.

## References

- The repo's glossary — read first
- [`rpci.md`](rpci.md) — Research → Plan → Critique → Implement
- [`pragmatic-principles.md`](pragmatic-principles.md) — the
  principle spine; loaded when designing, refactoring, or
  auditing a violation
- `../issues/feature-template.md` — full issue body template
- [`bug-patterns.md`](bug-patterns.md) — per-layer bug patterns
- [`code-changes.md`](code-changes.md) — cross-layer contract