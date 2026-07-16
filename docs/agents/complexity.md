# Managing Complexity in a Growing Codebase

> Pair with [`session-protocol.md`](session-protocol.md) Rule 3 (YAGNI) and
> [`feature-protocol.md`](feature-protocol.md) §Module discipline (deep-module).
> This document carries the *why* behind both; the others carry the *what* and
> *how*. Read on first adoption, then as cited.

A growing codebase's failure mode is not bugs. It is that **change becomes
linear in global system size instead of local module size.** This doc
collects the wisdom that keeps the cost of change proportional to the
component being changed, not to the system surrounding it.

## The reconciliation: YAGNI for features, broad-but-shallow for interfaces

YAGNI ("You Aren't Gonna Need It") forbids speculative *features*. John
Ousterhout's *A Philosophy of Software Design* (2018) argues that YAGNI was
*never* about interface shape — only about behavior. The two camps agree on
one failure mode: code written only for today's feature, with no thought for
tomorrow's reader. They disagree only on where the line sits.

**The reconciliation rule that this framework adopts:**

- **Implement** the smallest set of methods/cases that today's acceptance
  criterion demands. No methods nobody calls. No branches nobody exercises.
- **Design the interface** slightly broader than today's needs, when doing so
  *removes* complexity from callers, future tests, or future readers — not
  when it merely *anticipates* a feature.

This matches Ousterhout's "somewhat general-purpose" principle (PoSD Ch. 6)
and Beck's original C3-team rationale (which always paired YAGNI with
refactoring-and-test infrastructure). See §1 below.

---

## 1. The net-complexity-gain test

**Principle.** Before adding an abstraction, hook, parameter, or extension
point, ask: *does this design element remove more complexity than it adds?*

> "In order for an element to provide a net gain against complexity, it must
> eliminate some complexity that would be present in the absence of the
> design element." — John Ousterhout, *A Philosophy of Software Design* Ch. 1

**In this repo.** Pair this test with the two-adapter rule in
[`feature-protocol.md`](feature-protocol.md) §Module discipline:

- 0 callers → pass-through, refactor into the caller.
- 1 caller → borderline; justify or drop.
- 2+ callers → earning its keep; keep the module.

**Sources.** Ousterhout, PoSD Ch. 1, 6, 19. jmoiron's
[notes](https://jmoiron.net/blog/notes-on-philosophy-of-software-design)
include the pragmatic counter — tactical when unknowns are many, strategic
when unknowns are few.

## 2. Tactical vs. strategic programming

**Principle.** Tactical programming optimises the current task; strategic
programming optimises the system's long-term structure. Tactical accumulates
complexity faster than refactoring can pay it down.

> "Agile development tends to focus developers on features, not abstractions,
> and it encourages developers to put off design decisions in order to
> produce working software as soon as possible. … This can result in a
> rapid accumulation of complexity." — Ousterhout, PoSD Ch. 19

> "Developing incrementally is generally a good idea, but the increments of
> development should be abstractions, not features." — Ousterhout, PoSD,
> summary chapter

**In this repo.** Each feature slice in
[`feature-protocol.md`](feature-protocol.md) ends with a check for
*prefactor opportunities* — modular shapes that make future slices easier.
That check is the strategic-programming moment. Don't skip it because the
slice "already works."

**Sources.** Ousterhout PoSD Ch. 3 ("tactical tornado"), Ch. 19. Refactoring
2nd ed. names Speculative Generality as the code smell that mirrors the
opposite failure — too much strategic design up front.

## 3. Pull complexity downward; design interfaces once

**Principle.** The implementer should suffer so the caller does not have to.
A module with a simple interface and rich implementation is "deep"; a
module with an interface as wide as its implementation is "shallow."

> "The best modules are those whose interfaces are much simpler than their
> implementations." — Ousterhout, PoSD Ch. 4

> "Most modules have more users than developers, so it is better for the
> developers to suffer than the users." — Ousterhout, PoSD Ch. 4

**In this repo.** The deep-module discipline in
[`feature-protocol.md`](feature-protocol.md) is the operational form: write
the public service interface + DTO contracts before any internal code.
Internal helpers stay private. If a caller needs to reach into internals,
the seam is wrong — fix it before shipping the slice.

**Sources.** Ousterhout PoSD Ch. 4, 6, 8. "Define errors out of existence"
is the related trick — redesign the interface so invalid states cannot be
expressed.

## 4. Decomplect: prefer one-dimensional abstractions

**Principle.** Complect (interweave) is the structural failure mode opposite
to decompose. A system of many small single-purpose pieces is easier to
reason about than one file that does five things, even if it spans more
files.

> "Simplicity is a great victory over complexity. … Complecting multiple
> concerns in one place guarantees that any later change ripples through
> unrelated logic." — Rich Hickey, "Simple Made Easy" (Strange Loop 2011)

**In this repo.** Apply as a tiebreaker when two module shapes both look
reasonable: prefer the one that separates concerns along orthogonal axes
(persistence shape vs. domain shape, request vs. response, validation vs.
business rule). The deep-module discipline already enforces this at the
interface boundary; decomplecting enforces it inside modules.

**Sources.** Hickey, [Simple Made Easy](https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/SimpleMadeEasy.md) (2011).

## 5. Wait for the third use: the rule of three

**Principle.** Duplication is cheaper than the wrong abstraction. An
abstraction chosen from two cases predicts wrong about the third; extracting
too early produces both the indirection *and* the duplication it was meant
to remove.

> "Duplication is far cheaper than the wrong abstraction." — Sandi Metz,
> "The Wrong Abstraction" (2016)

**In this repo.** When two apply-sites share logic, write the duplication
and add a comment noting the candidate for extraction. Extract on the third.
The "deletion test" in [`feature-protocol.md`](feature-protocol.md) §Module
discipline is the post-extraction sanity check — count callers before
keeping the abstraction.

**Sources.** Metz, [The Wrong Abstraction](https://sandimetz.com/blog/2016/1/20/the-wrong-abstraction).
Rule of Three across
[Coding Horror](https://blog.codinghorror.com/the-big-ball-of-mud-and-other-architectural-disasters/)
and Fowler's *Refactoring*.

## 6. Enforce boundaries, don't honour them

**Principle.** Architectural boundaries that rely on code-review discipline
erode. Boundaries must be mechanically checkable — by the compiler, the
type system, the verifier, the test suite, or a build-time lint.

> "If everything is marked `public`, all four architectural approaches
> presented before are exactly the same." — Simon Brown (paraphrased),
> [Modular Monoliths](https://simonbrown.je/modular-monolith/)

**In this repo.** Where the language allows, mark internals as internal.
Where it doesn't, the budgeted next-best is a lint rule or an architectural
test that fails CI on a leak. "UI depends on the service's DTOs, never on
the persistence struct" is the canonical mechanical rule — a test on the
import graph turns it from convention to gate.

**Sources.** Brown, *Modular Monoliths*. Lattner et al., *MLIR: A Compiler
Infrastructure for the Rise of ML* (verifier-driven extensibility). Ford,
Parsons, Kua, *Building Evolutionary Architectures* — fitness functions
turn architecture into a CI failure when it drifts.

## 7. Code is the artifact; the theory is the deliverable

**Principle.** A codebase encodes a shared *theory* of the system — why it
behaves the way it does, how to safely extend it. The source text alone
cannot transfer a theory. New joiners onboard by sitting with people who
hold it, by reading the *decisions* about it, and by exercising it under
guidance — not by reading code in isolation.

> "The theory of a program … has to be possessed by [the] members of the
> programming team, since it cannot be embodied in the program text." —
> Peter Naur, "Programming as Theory Building" (1985)

**In this repo.** ADR practice lives in
[`adr-discipline.md`](adr-discipline.md) — full filename and section
contract, lifecycle states, the agent-reads-it protocol. Cross-reference
here is by purpose, not by repetition: this principle names *why*
[`session-protocol.md`](session-protocol.md) §Capturing decisions exists;
[`adr-discipline.md`](adr-discipline.md) names the *how*. Treat a missing
first-draft C4 System Context + Container view as itself a source of
drift.

**Sources.** Naur, *Programming as Theory Building*
([PDF](https://pages.cs.wisc.edu/~remzi/Naur.pdf)). Nygard,
[Documenting Architecture Decisions](https://adr.github.io/). Brown, *C4
Model* — the missing "first draft of architecture" (System Context +
Container views) is itself a source of drift.

## 8. Choose boring technology; spend innovation tokens deliberately

**Principle.** Every line of code is a maintenance commitment. Exotic
dependencies are future costs in cognitive load, upgrade pain, and bus-factor
risk. Choose boring for the parts that don't differentiate; reserve
innovation tokens for the parts that do.

> "Innovation is costly, so you should choose standard, well-understood,
> rock-solid technologies insofar as you possibly can. You only get a few
> innovation tokens to spend, so you should spend them on technologies that
> can give you a true competitive advantage." — Dan McKinley, *Choose Boring
> Technology*

**In this repo.** The session-protocol rule on tool usage applies: prefer
subagents specialised at the task; treat exotic libraries with the same
skepticism as exotic build tools. Boring wins on the day you need to
reproduce an incident at 2am.

**Sources.** McKinley, *Choose Boring Technology*
([club](http://boringtechnology.club/)). Charity Majors,
[Honeycomb blog](https://charity.wtf/) — observability + boring infra.

## 9. Indirection is paid for only at boundaries that actually change

**Principle.** Stroustrup/Wheeler: "Any problem in computer science can be
solved with another layer of indirection, except of course for the problem
of too many indirections." A growth-managing architecture adds indirection
*only* at boundaries that actually change — persistence, transport, UI
framework, third-party integration. Never inside stable logic.

> "The most fundamental problem in software development is complexity. There
> is only one basic way of dealing with complexity: divide and conquer." —
> Bjarne Stroustrup

**In this repo.** The hexagonal / ports-and-adapters boundary earns its
indirection only when there is a second delivery mechanism (CLI, queue,
test) on the inside. A single delivery does not need the seam.

**Sources.** Stroustrup quotes
[index](https://www.stroustrup.com/quotes.html). Freeman & Pryce, *Growing
Object-Oriented Software, Guided by Tests* — the walking skeleton surfaces
unknowns on day one instead of at go-live panic.

## 10. Entropy is the default; allocate complexity budget

**Principle.** Lehman's laws: large systems in use *must* change or become
progressively less useful; complexity grows unless work is invested to fight
it; global activity rates are constant. Rewrites on average fail or stall.

> "Almost every system that *works* today will be wrong tomorrow, because
> the environment in which it operates will change." — paraphrased from
> Lehman, *Laws of Software Evolution*

**In this repo.** Allocate complexity budget per slice. If a slice exceeds
it (long prefactor, sprawling test matrix, broad churn in unrelated modules),
decompose before shipping — the slice is bigger than
[`feature-protocol.md`](feature-protocol.md) §Tracer-bullets allows. The
"deletion test" and "two-adapter rule" together form the budget guard.

**Sources.** Lehman & Belady,
[Laws of Software Evolution](https://en.wikipedia.org/wiki/Lehman%27s_laws_of_software_evolution).

---

## How to use this document

- **On adoption.** Read end to end once. Skim the *In this repo* bullets
  before each slice.
- **During slicing.** Cross-reference the principle the slice most tests
  (often §1 net-complexity-gain or §5 rule of three) before declaring done.
- **On suspicion of YAGNI violation.** Run the net-complexity-gain test
  against the proposed abstraction. If it doesn't pass, drop it.
- **On reviewing a PR.** Cite principle numbers in review comments; do not
  re-argue the foundations.
- **When in doubt.** "Working code isn't enough" — but don't take that to
  the opposite extreme. Every rule has its exceptions. Match depth to the
  task ([`session-protocol.md`](session-protocol.md) Rule 5).

## Cross-references

- [`session-protocol.md`](session-protocol.md) — Rule 3 (YAGNI, refined to
  read with this doc), Rule 5 (proportional depth), §Capturing decisions.
- [`feature-protocol.md`](feature-protocol.md) — §Module discipline,
  §Tracer-bullets, §Prefactor before slicing, §Issue template.
- [`rpci.md`](rpci.md) — Design phase enforces the strategic-programming
  increment, not the feature increment.

## References (consolidated)

- John Ousterhout, *A Philosophy of Software Design*, 2nd ed. (2021) — primary
  source for §1–3.
- Kent Beck, *Extreme Programming Explained* (1999); Ron Jeffries,
  [practices/pracnotneed](http://ronjeffries.com/xprog/articles/practices/pracnotneed/)
  (1998) — YAGNI origin and the refactoring-as-prerequisite caveat.
- Rich Hickey, "Simple Made Easy," Strange Loop (2011) —
  [transcript](https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/SimpleMadeEasy.md).
- Sandi Metz, "The Wrong Abstraction" (2016) —
  [link](https://sandimetz.com/blog/2016/1/20/the-wrong-abstraction).
- Martin Fowler, *Refactoring* 2nd ed. — "Speculative Generality" code
  smell.
- Peter Naur, "Programming as Theory Building" (1985) —
  [PDF](https://pages.cs.wisc.edu/~remzi/Naur.pdf). Theoretical anchor
  for §7; ADR mechanics live in [`adr-discipline.md`](adr-discipline.md).
- Michael Nygard, "Documenting Architecture Decisions" —
  [adr.github.io](https://adr.github.io/).
- Simon Brown, *Modular Monoliths* and *C4 Model* —
  [je/](https://simonbrown.je/modular-monolith/),
  [c4model.com](https://c4model.com/).
- Bjarne Stroustrup, [quotes](https://www.stroustrup.com/quotes.html).
- Chris Lattner et al., "MLIR: A Compiler Infrastructure for the Rise of
  ML" — [arXiv](https://arxiv.org/pdf/2002.11054).
- Neal Ford, Rebecca Parsons, Patrick Kua, *Building Evolutionary
  Architectures* (O'Reilly).
- Freeman & Pryce, *Growing Object-Oriented Software, Guided by Tests*
  (O'Reilly) — walking skeleton.
- Dan McKinley, *Choose Boring Technology*
  ([club](http://boringtechnology.club/)).
- Lehman & Belady, *Laws of Software Evolution*
  ([Wikipedia](https://en.wikipedia.org/wiki/Lehman%27s_laws_of_software_evolution)).
- Fred Brooks, "No Silver Bullet" (1986) —
  [PDF](https://worrydream.com/refs/Brooks_1986_-_No_Silver_Bullet.pdf).
- Charity Majors, [charity.wtf](https://charity.wtf/) — observability and
  boring infra.
- jmoiron, [Notes on A Philosophy of Software Design](https://jmoiron.net/blog/notes-on-philosophy-of-software-design)
  — practitioner critique.

## Operationalising §1, §5, §10

The principles in this doc are abstract; their operational form
lives elsewhere in the framework:

- §1 (net-complexity-gain test) — operationalised in the two-adapter
  rule in [`feature-protocol.md`](feature-protocol.md) §Module discipline.
- §5 (rule of three) — operationalised in the two-adapter rule; same
  file.
- §7 (theory as deliverable) — operationalised in
  [`adr-discipline.md`](adr-discipline.md).
- §10 (entropy as default) — operationalised in the historical risk
  ledger built by [`../skills/consensus-hunter/`](../skills/consensus-hunter/).
  See [`../skills/consensus-hunter/OPERATIONS.md`](../skills/consensus-hunter/OPERATIONS.md)
  for the calibration methodology and the per-coord drift pattern
  that gives the lead indicator this principle references.

For the runbook that maps each § to day-to-day work on a target
repo, see [`../docs/run-on-your-codebase.md`](../docs/run-on-your-codebase.md).
