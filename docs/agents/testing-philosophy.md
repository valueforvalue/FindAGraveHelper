# Testing Philosophy — Which Tests to Keep, Which to Cut

> **Status:** Active. Derived from the Pragmatic Programmer (2nd ed.)
> + modern Go testing guidance + the 2026-07 appshell test audit
> (issue #626). Read alongside [`tdd.md`](tdd.md) — TDD is *how*
> to write tests (red-green-refactor); this doc is *which* tests
> to keep and *which* to cut.

## The one-sentence rule

**A test earns its place by catching a real bug that the type
system, the compiler, or another test doesn't already catch.**
If you can't name the bug class the test prevents, it's dead
weight.

## Principles (from the Pragmatic Programmer)

### 1. Test state coverage, not code coverage (Tip 65)

> "Identify and test significant program states."

100% line coverage with trivial assertions proves nothing about
correctness. A test that calls `handler(w, r)` and asserts
`rec.Code == 200` without checking the body is coverage
inflation — it catches a panic, nothing else. Every test should
assert on a **distinct program state** (the output shape, the
side effect, the error message) that a broken implementation
would produce differently.

**Decision rule:** if the test's assertion can pass even when
the code is wrong (e.g., the handler returns 200 but renders the
wrong page), the test is not testing state coverage. Either
strengthen the assertion or delete the test.

### 2. Test your software, or your users will (Tip 49)

> "Test your software, or your users will."

Tests exist to catch bugs before users do. A test that can't
catch a real bug — because its assertions are too weak, because
it tests a stdlib primitive, or because it verifies a compile-time
property — is wasted code that gives false confidence.

**Decision rule:** ask "what bug does this catch?" If the answer
is "none" or "the compiler already catches that," cut the test.

### 3. Use saboteurs to test your testing (Tip 64)

> "Introduce bugs deliberately; if your tests don't catch them,
> the tests are insufficient."

The inverse of Tip 49: if you can't make a test fail by breaking
the code it claims to test, the test is dead weight. This is the
"saboteur test" — mentally (or actually) introduce a bug and
check whether the test catches it.

**Decision rule:** for each test, imagine breaking the production
code in the most realistic way (wrong return value, missing side
effect, off-by-one). Does the test fail? If not, cut or
strengthen it.

### 4. Find bugs once (Tip 66)

> "Once a human tester identifies a bug, automated tests should
> verify it's fixed from then on."

Tests are regression insurance, not badge-counting. A test that
duplicates what another test already covers (same code path,
weaker assertions) adds maintenance burden without adding safety.

**Decision rule:** if another test already exercises the same
code path with equal or stronger assertions, cut the weaker
duplicate.

### 5. Go's type system handles many guarantees

Go is compiled and strongly typed. The compiler enforces:
- Struct fields exist and have the right type
- Interface satisfaction (`var _ Foo = &bar{}`)
- Nil-safety for pointer dereferences (at compile time for
  typed nils in simple cases)

Tests that re-verify these are testing the compiler, not your
code. In dynamically-typed languages these tests make sense; in
Go they're cargo cult.

**Decision rule:** if the test would fail at compile time, not
runtime, it's not a test — it's a build check. Move it to a
package-level `var _` declaration or delete it.

## What doesn't belong in the Go test suite

### Static / structural checks → move to linters

Tests that grep source files, AST-walk handlers, or check file
existence are **lints**, not tests. They couple the Go test binary
to the `docs/` or `frontend/` directory trees, they're brittle to
source formatting changes, and they run on every `go test`
invocation even when the code under test hasn't changed.

**Move to:** `audit/*.mjs` Node scripts, `go/analysis` analyzers,
pre-commit hooks, or `make lint-*` targets.

Examples from the audit (issue #626):
- Grepping `docs/adr/*.md` for `## Author` headings
- Grepping `frontend/index.html` for `<script>` tags
- Scanning all `.go` files for a specific Unicode literal
- AST-walking handlers to verify method-guard conventions (when
  a runtime test already fires real HTTP requests)

### Tests of stdlib primitives → cut

`sync.Map.LoadOrStore`, `strings.Contains`, `fmt.Sprintf` —
these are tested by the Go team, not by us. A test that wraps a
stdlib call and asserts its documented behavior is testing Go,
not appshell.

**Decision rule:** if the test's core assertion is "the stdlib
function works as documented," cut it. Test the **wiring** (your
code calls the stdlib function with the right arguments), not
the function itself.

### Compile-time checks masquerading as runtime tests → cut

`var _ viewmodel.AboutView = view` inside a `func Test...` body
is a compile-time interface-satisfaction check. It fails at
compile time, not runtime. It's a valid pattern — but it belongs
as a package-level `var _`, not as a test function that inflates
the test count and runs `go test` machinery for zero runtime
value.

### Diagnostic tests that always skip → move to build tags

Tests that skip when a file is absent (`.dixiedata/dixiedata.db`),
when a binary isn't built, or when an env var isn't set are
**manual diagnostic probes**. They don't cost CI time (they skip
fast) but they clutter the test file list and confuse contributors
who expect them to run.

**Move to:** `//go:build diag` tag, a separate test target, or a
`cmd/diag` subcommand.

## Consolidation — table-driven tests

The Go community standard for testing multiple inputs against the
same code path is the **table-driven test**:

```go
func TestFoo(t *testing.T) {
    cases := []struct {
        name     string
        input    string
        want     string
    }{
        {"empty", "", "default"},
        {"normal", "abc", "abc"},
        {"whitespace", "  ", "default"},
    }
    for _, tc := range cases {
        t.Run(tc.name, func(t *testing.T) {
            got := Foo(tc.input)
            if got != tc.want {
                t.Errorf("Foo(%q) = %q, want %q", tc.input, got, tc.want)
            }
        })
    }
}
```

If you have N standalone test functions that each call the same
function with different inputs and assert the same kind of output,
consolidate them into one table-driven test. This:
- Reduces test-count inflation
- Makes it obvious which cases are covered (the table IS the
  coverage map)
- Adds new cases by appending a struct literal, not writing a
  new function

**When NOT to consolidate:** if each test exercises a genuinely
different code path (not just different inputs to the same
path), keep them separate. Table-driven tests are for
same-path-different-input, not for unrelated scenarios.

## Brittle tests — flag, don't necessarily cut

Tests that pin implementation details (exact CSS hex codes, exact
HTML tag strings, exact URL query formats) are brittle: they break
on cosmetic refactors that don't change behavior. They're not
wrong — they catch drift — but the cost of maintaining them is
real.

**Mitigation:**
- Assert on **structural properties**, not exact strings (e.g.,
  "body contains `data-theme=\"high-contrast\"`" not "body
  equals `<html lang=\"en\" data-theme=\"high-contrast\"...>`")
- Use `strings.Contains` for substrings, not `==` for full
  matches
- If the test pins a color hex code, also pin the semantic intent
  in a comment so the next contributor knows whether the hex or
  the semantics is the invariant

## The cut checklist

Before adding a new test, verify it passes the saboteur test:
1. **What bug does this catch?** Name the bug class.
2. **Does another test already catch it?** If yes, don't add.
3. **Does the compiler already catch it?** If yes, don't add.
4. **Can I make it fail by breaking the code?** If no, don't add.
5. **Could this be a linter instead?** If it's a source-grep,
   it's a linter.

Before keeping an existing test, ask the same questions. Tests
that fail the checklist are cut candidates.

## Relationship to TDD

[`tdd.md`](tdd.md) defines the **process** (RED → GREEN →
REFACTOR). This doc defines the **quality bar** for the RED
test (which tests earn their place). Together:

- **TDD** — the test exists before the code (timing)
- **Philosophy** — the test catches a real bug (quality)

A RED test that asserts `rec.Code == 200` with no body check
satisfies the TDD process but fails the quality bar. See
[`tdd.md`](tdd.md) §"Anti-patterns" for the named TDD-side
violations (“Mocking the seam”, “Speculative tests”, etc.).

## Sources

- [The Pragmatic Programmer, 2nd ed.](https://pragprog.com/titles/tpp20/) — Tips 49, 64, 65, 66
- [Prefer Table Driven Tests (Dave Cheney)](https://dave.cheney.net/2019/05/07/prefer-table-driven-tests)
- [Go Wiki: TableDrivenTests](https://go.dev/wiki/TableDrivenTests)
- [Delete Cargo Integration Tests (matklad)](https://matklad.github.io/2021/02/27/delete-cargo-integration-tests.html)
- [Code Coverage Best Practices (Google Testing Blog)](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)
- Repo audit: issue #626, `docs/audit/pragmatic-programmer-principles-audit-2026-07.md` §1.14 + §1.22