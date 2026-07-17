# ADR 0004 — `view.html` as the human-review layer (not a CLI)

## Status

`Accepted` (2026-07-15). Earned by Phase 2 → Phase 3
transition when the ranked-candidates field was added to
the state.jsonl. See
[`CONTEXT.md` §L6](../../CONTEXT.md#l6-userscript-edits-are-user-facing).

## Context

The harness's auto-accept threshold (0.85) is reachable for
~10% of pensioners. The remaining ~88% need human review.
The review surface must support:

- **Per-pensioner decision**: pick one candidate, or mark
  no match.
- **Bulk actions**: skip, mark-all-ambiguous, export.
- **No build step**: contributors edit it directly; users
  open it from disk.
- **Round-trip with dixiedata**: the decisions.csv must
  schema-match `dd_marker_run.py`.

The forces in tension:

- **Web UI vs. CLI**: a CLI (`pick --pensioner 1234 --choice
  50923719`) is scriptable but tedious for 6,500+ decisions.
  A web UI is faster for the human but harder to script.
- **Single-file vs. framework**: React/Vue adds a build
  step. Single-file HTML + vanilla JS works on `file://`.
- **Server-backed vs. local-only**: a server (Flask +
  WebSocket) adds operational complexity. localStorage +
  file-picker is enough.

## Decision

The review layer is a single static HTML file at
`scripts/view.html`. It:

- Opens in any modern browser via `file://` (no server)
- Loads `state.jsonl` via the browser's File picker
- Stores partial decisions in `localStorage` for crash
  recovery (the file is also re-read on every pick)
- Exports `decisions.csv` via `URL.createObjectURL` +
  `<a download>`
- Has no build step (vanilla JS, no transpile)

The CLI is `scripts/pipeline/dd_marker_run.py` for the write-back
step. CLI-driven pick is out of scope (scripting the
decisions is a separate concern).

### Alternatives rejected

- **Flask + WebSocket server** — rejected, adds operational
  complexity; user already has a browser open.
- **React + Vite build** — rejected, build step in a
  single-file tool is friction.
- **Tampermonkey userscript for review** — rejected, the
  decisions need to be exportable as CSV for the
  dd_marker_run.py round-trip; userscript GM_download works
  but the UX is worse than a static page.
- **CLI picker** — rejected, 6,500+ decisions in a terminal
  is a bad UX.

## Consequences

**Positive:**

- Zero install. User opens the file in Chrome, picks a
  file, picks decisions, downloads CSV.
- The HTML + JS source is committed; changes are diffable
  in code review.
- `dd_marker_run.py` is a separate tool with a single
  concern (write-back); the review surface stays simple.

**Negative:**

- The browser is the only review surface. Mobile / tablet
  is possible but not designed-for.
- `localStorage` is per-browser; switching browsers loses
  partial decisions (mitigated by re-reading state.jsonl
  on every pick and writing back via download).
- The 7,758-record load freezes the tab for 30+s.
  Tracked as T002 (lazy-load).

**When to revisit:**

- T002 lands (lazy-load) and the tab-freeze goes away.
- Mobile / tablet review is requested.
- The CSV schema needs more columns than a static-HTML
  export can reasonably produce.

**Related:**

- [`CONTEXT.md` §L6](../../CONTEXT.md#l6-userscript-edits-are-user-facing)
- [`cross-layer-contract.md` §"The review-UI output: decisions.csv"](cross-layer-contract.md)
- [`bug-catalog.md` §"Review UI layer"](bug-catalog.md)
- Task T002 (lazy-load), T011 (CSV column rename protocol)