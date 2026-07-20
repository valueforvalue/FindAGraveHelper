---
template_version: 2
date: 2026-07-20T00:00:00-05:00
author: Jeremy Morris
repository: FindAGraveHelper
branch: master
commit: a3fc257cbeee2b9924f23d05b9b69db22396b7f3
review_type: staged
scope: "Issue #38 Commit 1 — view.html v2 layout normalization"
scope_strategy: working-tree
in_scope_files_count: 5
status: ready
severity: { critical: 0, important: 0, suggestion: 1 }
verification: { verified: 5, weakened: 0, falsified: 0 }
blockers_count: 0
tags: [code-review, view-v2, browser-ui]
---

# Code Review — Issue #38 Commit 1

**Commit:** `a3fc257` · **Status:** `ready` · **Findings:** 0🔴 · 0🟡 · 1🔵 · **Verification:** 5✓ / 0− / 0✗

## Top Blockers

None.

---

## Legend

```text
Severity    🔴 fix before merge   🟡 fix soon   🔵 nice to have   💭 discuss
ID prefix   I interaction   Q quality   S security   G gap
Verify      ✓ verified   − weakened (demoted)   ✗ falsified (dropped)
```

---

## 🔵 Suggestions

### Q1 🔵 Full-run rendering remains synchronous

**Where**
`scripts/view/v2.html:985-986`

**Code**
```javascript
results.innerHTML = records.length
    ? records.map(renderRecord).join('')
```

**Why**
All records and candidates render in one synchronous DOM replacement. Full 7,709-record runs may retain v1 tab-freeze behavior. Commit 1 intentionally leaves collapse/visibility optimization to Commit 2, so this does not block current slice.

**Fix**
Implement Commit 2 collapse and candidate limiting before making v2 default.

---

## Impact

| Consumer | Change | Findings |
| --- | --- | --- |
| `tests/test_view_html_normalize.py:17` | Loads `scripts/view/v2.html` and tests normalization helpers | — |
| `tests/test_view_html_v2_layout.py:81` | Loads v2 and tests rendered behavior/actions | Q1 |
| `scripts/pipeline/run_unified.py:1553` | Configurable view source still defaults to v1 by design | — |

---

## Precedents

| Commit | Subject | Follow-ups |
| --- | --- | --- |
| `eeb34e9` | Add F7: view.html unified display with normalize layer | `0bfbe24` fixed dropped DD/spouse fields |
| `3d3e3bb` | J8 reviewer UX and candidate layout | `2d20de6`, `a01198a` fixed file/loading and flex-layout defects |
| `2d20de6` | J9 layout fix + embedded JSONL | `7e6e5c7`, `6ef707c` hardened embed detection |
| `a01198a` | J11 candidate-row layout hardening | No later same-area fix |

**Recurring lessons (most → least frequent)**

1. Exercise normalization against real rendered records, not source-shape checks alone.
2. Browser layout and file-loading behavior need Playwright coverage.
3. Keep v2 additive; preserve v1 and current JSONL wire format during migration.

---

## Recommendation

| # | ID | Action | Alt / Note |
| - | -- | ------ | ---------- |
| 1 | Q1 | Proceed with Commit 1; address full-run DOM cost in planned Commit 2. | Do not make v2 runner default before then. |

Security review found no concrete source-to-XSS path: dynamic text uses `escapeHtml()`, and URLs pass through `safeUrl()` with `http:`/`https:` allowlisting. File-picker same-path retry and record accessible naming were fixed during review and covered by Playwright tests.
