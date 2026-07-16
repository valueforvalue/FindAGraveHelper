# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — single-context repo, no `CONTEXT-MAP.md`.
- **`docs/agents/adr/`** — read ADRs that touch the area you're about to work in. This repo scopes architectural decisions under `docs/agents/adr/` rather than the top-level `docs/adr/` used by the upstream skill defaults.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo:

```
/
├── CONTEXT.md
├── docs/
│   └── agents/
│       └── adr/
│           ├── 0001-playwright-stealth-over-requests.md
│           ├── 0002-state-jsonl-format.md
│           ├── 0003-ok-burial-as-tiebreaker.md
│           └── 0004-view-html-as-review-layer.md
└── scripts/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_

## Repo-specific notes

- **`AGENTS.md` is the per-repo agent contract** — `CONTEXT.md`, hard rules, and doc index live separately. Read `AGENTS.md` before any schema-touching or copy-writing work.
- **Test command**: `pytest tests/` (or `pytest tests/test_<name>.py` for one file).
- **Stack**: Tampermonkey userscripts + Python harness (Playwright + stealth) + static `scripts/view.html` review UI.