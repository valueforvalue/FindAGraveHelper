# ADR 0003 — OK burial is a tiebreaker, not a hard requirement

## Status

`Accepted` (2026-07-15). Earned by Phase 1 local-data
analysis. See
[`docs/learnings/README.md` §"The goal is OK-connection, not specifically OK burial"](learnings/README.md#2-the-goal-is-ok-connection-not-specifically-ok-burial).

## Context

The project goal is to find Confederate soldiers associated
with Oklahoma. The OK Board of Pension Commissioners
documented that applicants had to provide proof of at least
1 year's residency in OK. So every pensioner **lived in OK**.

But **burial state** could be anywhere — many veterans were
buried where they died, not where they lived. A soldier who
spent his last years in OK may be buried in TX, MO, or AR.

The first scoring weight (Phase 2 v1) was `ok_burial_score`
with weight 0.15 and was used as a *primary* signal in the
auto-accept threshold. Validation on the local 577 pairs
showed:

- With OK burial as primary: 86% rank-1 hit rate, 0
  auto-accepts (the threshold was unreachable without OK
  burial).
- With OK burial as tiebreaker (weight 0.15, not in the
  threshold gate): 88% rank-1 hit rate, 29 auto-accepts
  (100% precision on the auto-accepts).

The current code uses OK burial as a tiebreaker. This ADR
documents that decision.

## Context (forces in tension)

- **Goal precision vs. goal recall**: requiring OK burial
  makes matches more precise (no TX-buried soldier gets
  auto-accepted) but tanks recall (most pensioners are
  buried wherever they died).
- **Project intent vs. literal burial state**: the user's
  research said the goal is "OK-connection" (residency +
  family ties), not "OK burial". The pension residency
  requirement establishes residency; burial is downstream.
- **Auto-accept threshold reachability**: requiring OK
  burial for auto-accept means the threshold is gated on
  data that may not exist in the FaG candidate card.

## Decision

OK burial is one feature in the per-feature scoring function
with weight 0.15. It is **not** in the auto-accept threshold
gate. The auto-accept threshold (0.85) is reachable without
OK burial.

`OK-connection` (residency + family ties) is the operational
form of "OK association" in this project. It is not
equivalent to "OK burial".

### Alternatives rejected

- **OK burial as primary signal (weight 0.40, in threshold
  gate)** — rejected, 0 auto-accepts, 86% rank-1.
- **OK burial removed entirely** — rejected, OK burial is
  still useful as a tiebreaker between close-scored
  candidates.
- **State residency as a hard requirement** — rejected, the
  pension records don't have residency dates; we have
  "applied for an OK pension" as a proxy.
- **State list configurable** — deferred to T008 (multi-
  state expansion). The OK-specific logic stays; the
  flag makes it TX/AR/MO-aware.

## Consequences

**Positive:**

- The 88% rank-1 hit rate is the production baseline.
- 29 auto-accepts at 100% precision (Run #0 validation).
- The scoring function generalizes — when multi-state
  expansion lands (T008), `ok_burial_score` becomes
  `target_state_burial_score` with no other code change.

**Negative:**

- A TX-buried OK pensioner may be auto-accepted. The HTML
  reviewer catches the false positives.
- The 0.15 weight is calibrated to the local 577 pairs; the
  full 7,758 set may need a re-tune.

**When to revisit:**

- The 88% rank-1 hit rate drops below 85% on the full 7,758
  set. Re-tune the weight.
- Multi-state expansion lands (T008). The weight transfers
  but the name changes.
- The user clarifies the project goal to be "OK burial"
  (not "OK connection"). Add OK burial back to the threshold
  gate.

**Related:**

- [`CONTEXT.md` §"Language" §OK-connection](../../CONTEXT.md) (term to be added in T012)
- [`docs/learnings/README.md` §"Hit-rate progression"](learnings/README.md#hit-rate-progression)
- [`docs/learnings/strategy-tuning.md`](learnings/strategy-tuning.md)
- Task T012 (document the weight decision in `CONTEXT.md`)