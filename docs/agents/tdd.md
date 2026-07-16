# Test-Driven Development

The truth anchor for every slice that lands on a repo that
adopts agent-stack. It does not replace the vertical-slice
discipline in [`feature-protocol.md`](feature-protocol.md);
it sits *inside* it, in the gap between "the slice is
well-shaped" and "the slice ships what we said it would."

This doc is the agent-stack port of the TDD skill. The
generic red-green-refactor loop lives in the skill; this
doc captures the per-layer recipes and anti-patterns that
recur across stacks.

## The failure modes TDD prevents

Three classes of bug recur across every codebase. Each is
preventable by a single test written *before* the slice
lands.

### 1. Invoker wiring (most common)

**Symptom:** UI button calls a helper that queries the DOM
for a target element, gets `null`, and silently early-returns.
The feature is fully implemented server-side (handler +
route + state) but the user sees no feedback.

**RED test:** drive the live binary (or a smoke harness),
click the button, assert the target element is in the DOM
AND not in a hidden state. This test fails BEFORE the slice
because the target doesn't exist.

### 2. Adjacent race / state-machine collision

**Symptom:** The slice's own click handler does the right
thing, but a different handler attached to a higher-priority
event (document, window, ancestor element) reacts to the same
event and undoes the work. The slice passes its own smoke
probe because the probe only checks the slice's own outcome.

**RED test:** smoke probe that clicks the trigger, waits
50–200ms, then asserts the panel is still in the expected
state. For native-host runtimes (webview hosts, Electron,
Tauri, etc.) the 50ms window is the
right delay — the event loop is slower than headless Chromium.

### 3. Orphan handler / response-shape mismatch

**Symptom:** A handler is registered (Go route, Express
endpoint, Django URL) but the response shape doesn't match
what the client expects. The client follows a redirect to
raw HTML, or parses JSON as a navigation, or vice versa.

**RED test:** handler test that asserts the response status,
content-type, and key body fields. Plus: an orphan-handler
probe that walks the route table against the client
invokers, flags any handler with no caller.

## The loop

This is the slice-internal protocol. It runs *inside* one
slice, not across the whole feature.

### Step 0 — Read the slice's acceptance criterion

The slice plan states "the user can X" or "the user sees Y
when Z." That criterion is what the test will pin. If the
slice plan doesn't have one, the plan is incomplete — go
back and add it. An implementation criterion ("the service
exposes method `Foo(int64)`") is not an acceptance criterion;
it's an implementation step.

### Step 1 — RED: write the failing test first

Write the test that **pins the acceptance criterion.** Do
not write the slice code yet. Do not write other tests yet.

The test fails for the **right reason.** If the test fails
for an unrelated reason (missing import, test setup
mistake), fix the test, not the code. A passing test that
wasn't actually pinning the criterion is worse than no test.

### Contract touch

TDD is the agent-stack executable form of Design by Contract,
but it is not a formal Meyer-style contract system. Tests
express and verify caller obligations, observable guarantees,
and invariants; framework source does not gain a generic
`Require`, `Ensure`, or `Invariant` runtime helper.

Apply a contract touch when a slice:

- adds behavior at a public seam;
- materially changes behavior at an existing public seam; or
- fixes a bug caused by an implicit or violated seam contract.

A public seam includes an exported service method or helper,
HTTP handler, DTO, typed builder, persistence boundary,
framework-native adapter (HTMX endpoint, JSX component prop,
Wails binding, etc.), and user-visible DOM interaction. Apply
the rule to existing code when the slice materially touches
that seam. Do not start a backlog-wide retrofit or expand a
slice into unrelated code. Formatting, generated output,
mechanical renames, and other behavior-preserving edits do
not trigger contract churn.

For each affected seam, document and test whichever
dimensions apply:

- **Preconditions** — what callers must provide or
  establish.
- **Postconditions** — observable result after success.
- **Failure modes** — typed error, status/header/body, toast,
  or other caller-visible failure behavior.
- **State effects** — what changes, what remains unchanged
  on failure, and whether the operation is atomic.
- **Idempotency and concurrency** — whether retries,
  duplicate actions, or simultaneous calls are safe.

Omit dimensions that do not apply; do not write boilerplate
such as "no side effects" on every pure helper. Exported
doc comments state the source-level contract. The RED test
proves relevant claims at the seam. For cross-layer slices,
the handler test proves the server contract and the smoke
probe proves the user-visible postcondition.

Choose the strongest enforcement site that removes invalid
states with the least runtime risk:

1. Typed languages' type system, enums, and typed builders
   prevent invalid representation.
2. Database constraints protect durable data invariants.
3. Service validation and typed errors reject user or caller
   input.
4. Architecture tests protect package boundaries.
5. Handler, service, property, render, and smoke tests prove
   observable postconditions.
6. Panics protect developer-created impossible states only.
   Never panic for ordinary user input, recoverable I/O, or
   third-party failures.

The contract is complete enough when a caller can answer
"what must I provide, what may change, and what can fail?"
and a failing test identifies which promise broke. More
prose or assertions after that point add noise, not safety.

Example:

```pseudo
// AttachSourceRecord attaches sourceID to personID.
//
// personID and sourceID must identify existing records. On
// success, the attachment is persisted exactly once.
// Duplicate attachment is idempotent. ErrNotFound identifies
// either missing record; all errors leave archive state
// unchanged.
func (s *Service) AttachSourceRecord(personID, sourceID int64) error
```

Tests then cover success, either missing record, duplicate
calls, and unchanged state after failure. They do not assert
private call order unless that order is itself a documented
performance contract.

### Step 2 — GREEN: write the minimum slice code

Implement the smallest diff that satisfies the RED test. No
drive-by refactors. No "while I'm here" cleanup. No
speculative surface.

- Package test suite green.
- Smoke probe green.
- Full short suite green.

If a slice makes another test in the same package turn red,
**stop.** The slice is touching code outside its seam.

### Step 3 — Adjacent behavior sweep

Before the commit, run the smoke probes and tests for
**adjacent surfaces** — anything in the same screen family,
anything that shares a JS dispatcher, anything that the
slice's render touches.

If any turn red, the slice has crossed a seam it shouldn't
have. **Fix or escalate; do not silence.**

### Step 4 — REFACTOR (only after green)

Extract duplication the slice revealed. Deepen modules.
Two-adapter check before adding any new public method.

**Never refactor while RED.** Get to GREEN first.

### Step 5 — Commit the RED test + GREEN slice together

The RED test lives in the same commit as the slice code it
pins. Inline, atomic, reviewable.

## What's the seam?

Per [`feature-protocol.md`](feature-protocol.md) §"Module
discipline", the seam is the **service interface + DTO**.
Tests cross the seam. The persistence layer is private to
the service; the test does not import it.

For slices that don't add a service, the seam is the **DOM
surface ID** (or its stack-equivalent — schema name, route
name, etc.). The render test asserts the surface ID is
present (or absent) in the rendered output; the smoke probe
asserts the same ID is reachable from a click.

If a test needs to mock the service, the test is testing
the wrong thing. The service is the seam; mocking it hides
the failure mode where the JS calls a real method that
quietly early-returns.

Exception: when the service itself depends on a hard-to-
fake boundary (native dialog, host runtime, native
API), mock
the boundary, not the service.

## Per-layer recipes

### Backend (handler + service)

- **Handler test:** asserts status code, response shape,
  headers (especially any redirect / toast / content-type
  contract).
- **Service test:** uses a real DB (or in-memory fixture).
  No mocks. Reach for property-test patterns when the input
  domain is interesting.
- **Migration test:** if the slice ships a schema change,
  the RED step extends the existing reversibility catalogue.

### View template

- **Render test:** calls `Render` (or equivalent) into a
  buffer, asserts the rendered output contains (or doesn't
  contain) specific surface IDs.
- **Attribute test:** if the slice introduces a new
  framework-specific attribute (hx-target, react-router path,
  etc.), the validator fails fast in dev builds.

### Frontend (JS / interaction)

- **Smoke probe:** Playwright (or equivalent) driving the live
  binary, asserting response shape AND `page.url()` AND the
  relevant DOM state. The response-only assertion is
  insufficient (that is how the silent-swallow bug class
  ships).

## Anti-patterns

- **Horizontal slicing.** Writing all the tests first, then
  all the implementation. AI-slop failure mode. Right move:
  one test → one impl → repeat, even within one slice
  commit.
- **Test-after-the-slice-is-done.** Catches future
  regressions but not the slice's own drift. TDD adds the
  test that pins the acceptance criterion *before* the slice
  lands.
- **Mocking the seam.** Writing a test that mocks the
  service to assert "the handler called `Foo(int64)` with
  X." This pins the implementation, not the behavior.
- **Pinning the response shape but not the post-click URL.**
  Smoke probes MUST assert `page.url()` after every click
  that expects navigation.
- **Speculative tests.** Writing a test for behavior the
  acceptance criterion doesn't mention.

## When NOT to TDD

- One-line bug fix with clear repro — bug protocol applies.
- Pure doc change.
- Pure build / CI change.
- Refactor with characterization tests — when the slice
  preserves behavior but rearranges code, the RED step is a
  characterization test.

## References

- [`feature-protocol.md`](feature-protocol.md) — slice
  discipline this protocol sits inside
- [`rpci.md`](rpci.md) §I — Implement phase wiring
- [`bug-patterns.md`](bug-patterns.md) — per-layer bug
  patterns to read alongside