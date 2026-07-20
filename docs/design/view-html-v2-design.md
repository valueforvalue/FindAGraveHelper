# view.html v2 — layout rework design

> **Status:** paper design. To be implemented after sign-off.
> **Audience:** the user (project owner) and the implementer
> (next agent). The user reacts to this doc; the implementer
> reads it.
>
> **Goal:** rework the existing `scripts/view.html` (1900+ lines,
> FaG-shaped) into a layout that (a) reads better against real
> past runs, (b) is collapsible (a 7,709-record run is unscrollable
> today), and (c) carries the engine-aware scaffolding so a future
> Newspapers.com (or other engine) result can plug in without
> another full rewrite.
>
> **Out of scope for this slice:** the engine-aware data shape
> (a separate v2-schema work). For this slice, view.html is
> refactored to be **engine-agnostic in layout** (the engine
> name appears as a small badge per record; FaG-specific
> details are in a disclosure) but the data still comes from
> today's `state.jsonl` shape (FaG fields). A future slice
> changes the wire format.

---

## Why this rework

The current view.html is 1900 lines, has been growing for
months, and was written before the engine abstraction work
(issues #33-#36). When a Newspapers.com run lands, today the
reviewer would see rows with `name=""`, `slug=""`, no backlink,
no image — useless. Even for FaG, the layout is dense and
hard to scan: 7,709 records × 5-20 candidates each = 50,000+
DOM nodes, every record always fully expanded, score breakdown
bars rendering 7 features × every candidate, no compare mode.

The user wants:
1. The FaG output to look good (the worked case).
2. The layout to be **engine-agnostic in structure** so future
   engines don't require another full rewrite.
3. The page to be **collapsible** so 7,709 records are
   browsable.
4. The reviewer actions (Pick / remove / notes) to be
   **prominent**, not buried.

The "engine-aware scaffolding" point matters: the new layout
should be one function that renders a generic record card,
with engine-specific details behind a disclosure. Adding a
new engine means writing the engine-specific disclosure, not
rewriting the renderer.

---

## Today: the existing card

```
┌──────────────────────────────────────────────────────┐
│ Name (h2)                              [status pill]  │  <- row 1
│ Pensioner #ID | regiment | company | ... | spouse   │
│ → source card link | View source                    │
├──────────────────────────────────────────────────────┤
│ [★ best match]  [⚠ ambiguous]  [REMOVED]  [PICKED]   │  <- row 2
│ ─────────────────────────────────────────────────── │
│ #1                                                    │  <- row 3
│   Candidate name                  ████░ 85%           │     (per
│   Slug, open, image, VETERAN, b.1844 d.1932          │     candidate)
│   [score breakdown bars: last, first, middle, ...]   │
│   Found by: B1-exact ...                             │
│   [Pick] [✕ remove] [notes_________________]        │
│ ─────────────────────────────────────────────────── │
│ #2                                                    │
│   ...                                                 │
└──────────────────────────────────────────────────────┘
```

Issues:
- Always fully expanded (50K+ DOM nodes for the full run).
- Score breakdown is 7 features × every candidate (visual noise).
- Pick button at the bottom of each row (easy to miss).
- No compare mode (the hardest review job is picking between
  two close-score candidates; the layout doesn't help).
- No per-record collapse.
- Engine field name shows nowhere; a Newspapers.com run
  would render as empty fields with no indication why.

---

## Proposed: the new card

```
┌──────────────────────────────────────────────────────────┐
│ ⌃ [FaG]  Name (h2)               #ID       [PICKED] [×]   │  <- row 1: identity + state
│       Regiment · Company · Lifespan                    │
│       → source card   ↗ View source                     │
├──────────────────────────────────────────────────────────┤
│ STATUS  [auto_accept]   |   DECISION  [undecided]        │  <- row 2: status side-by-side
│ CGR 0 matches · DD tracked ✗ · Spouse known ✓           │
├──────────────────────────────────────────────────────────┤
│ TOP CANDIDATES  (3 of 12)               show all ⌄        │  <- row 3: candidates
│ ┌────────────────────────────────────────────────────┐ │     (collapsed by default)
│ │ #1 ★  John Q. Smith · 1844-1932 · Oklahoma          │ │
│ │      0.85  last [████] first [████] year [██]      │ │     inline 3-feature score
│ │      ↗ open  ⌥ image  notes______  [Pick] [×]      │ │     prominent Pick
│ ├────────────────────────────────────────────────────┤ │
│ │ #2    Mary A. Smith · 1846-? · Illinois              │ │
│ │      0.42  last [████] first [░░] year [██]       │ │
│ │      ↗ open  ⌥ image  notes______  [Pick] [×]      │ │
│ └────────────────────────────────────────────────────┘ │
│ [compare top 3]  [show all 12]  [FaG details ⌄]        │
├──────────────────────────────────────────────────────────┤
│ REVIEWER NOTES  [free-text area________________]         │  <- row 4: notes
└──────────────────────────────────────────────────────────┘
```

### Per-row decisions

**Row 1 — Identity + state.**
- A `⌃` collapse triangle on the left collapses the whole
  card. Default: expanded.
- A small engine badge (`[FaG]`, `[Newspapers.com]`) on the
  left. Future engines add their own badge. Default: just
  the engine name, no styling yet.
- The record name (h2), the pensioner ID, and the
  picked/removed state on the right.

**Row 2 — Status, side-by-side.**
- Left: the engine's status (auto_accept, needs_review,
  no_results, low_score, captcha, etc.). Today's single status
  pill moves here.
- Right: the reviewer's decision (undecided, picked,
  unpicked, none_match, follow_up).
- CGR / DD / Spouse corroboration counts in a sub-row. Today
  these are badges inline with the meta; the new layout groups
  them.

**Row 3 — Candidates, collapsed by default.**
- Top 3 candidates visible by default. The full count is
  shown in the header (`3 of 12`); a `show all ⌄` expands to
  the full list.
- Each candidate row is dense: name + lifespan + state on the
  top; an inline 3-feature score (`last`, `first`, `year`);
  action buttons on the right.
- A `compare top 3` button opens a side-by-side comparison
  view (a modal or inline diff).
- A `FaG details ⌄` disclosure shows the engine-specific
  deep data: IIIF image, source card link, the full 7-feature
  score breakdown, the `_found_by` provenance. Other engines
  have their own disclosure (Newspapers.com: iso_date,
  location, paper, page).

**Row 4 — Reviewer notes.**
- The pensioner-level note. Today it's an `<input>` row in
  the meta; the new layout makes it its own row with a
  proper `<textarea>` for longer notes.

### Card collapsed

When the user clicks the `⌃` triangle, the card collapses to:

```
[FaG]  Name (h2)              #ID      [PICKED]    ⌄
       STATUS [auto_accept]    DECISION [undecided]
       TOP 1: 0.85  John Q. Smith · 1844-1932 · OK
```

A 7,709-record run with all cards collapsed renders ~50,000
DOM nodes (vs. ~1M for fully expanded). Scrollable.

### Filter + stats at the top

The header stays sticky. New affordances:
- **Status filter** (today): "all / auto_accept / needs_review /
  no_results / captcha / etc." — unchanged.
- **Engine filter** (new): "all / findagrave / newspapers_com /
  etc." — engine-agnostic; populated from the data, not
  hardcoded.
- **Decision filter** (new): "all / undecided / picked /
  unpicked / follow_up" — reviewer's view of their work.
- **Search** (today): free-text by name/ID — unchanged.
- **Stats bar** (today): decided/auto/ambiguous pills — moved
  to a left-side rail; right side gets the filters.

### Compare mode

The hardest review job: two close-score candidates. The
layout today forces scrolling between them. The new
`compare top 3` button opens a side-by-side diff:

```
┌──────────────────────────────────────────────────────┐
│ COMPARE: Nancy A. Eads (pensioner #272)               │
├──────────────────────────────────────────────────────┤
│ #1 ★  0.85    │ #2     0.42    │ #3     0.31         │
│ John Q. Smith │ Mary A. S. │ Bob J. S.             │
│ 1844-1932 OK │ 1846-? IL │ 1844-? TX               │
├──────────────┼────────────┼─────────────────────┤
│ last  [████] │ last [████] │ last [░░░░]         │
│ first [████] │ first [░░] │ first [██░░]         │
│ year  [██]   │ year  [██] │ year  [██]            │
├──────────────┼────────────┼─────────────────────┤
│ ⌥ open       │ ⌥ open     │ ⌥ open               │
│ [Pick #1]    │ [Pick #2]  │ [Pick #3]            │
└──────────────────────────────────────────────────────┘
```

Closes when any [Pick] is clicked (auto-closes after the
decision is made). Or the user clicks outside.

### What the engine-aware scaffolding looks like

Today, `view.html` accesses `c.memorial_id`, `c.slug`,
`c.backlink`, `c.iiif_url`, `c.score_breakdown` (FaG-shaped).
The new view.html accesses:

- `record.engine.name` — small badge in the header.
- `candidates[i].id` — engine-agnostic primary key.
- `candidates[i].title` — primary display label.
- `candidates[i].url` — link.
- `candidates[i].score` — engine's confidence.
- `candidates[i].evidence.score_breakdown` — generic
  feature names (last_name, first_name, middle_name,
  year_window, state, other). Today's FaG breakdown uses
  `last`/`first`/`middle`/`ok_burial`/`state`/`veteran`/`death`
  — these get remapped to the generic names in a
  `fag_evidence_to_common()` function that lives next to the
  engine.

FaG-specific details (the IIIF image, the full FaG
score breakdown, the `_found_by` provenance) are in a
disclosure that's labeled `FaG details`. Newspapers.com
details (iso_date, location, paper, page) would be in a
`Newspapers.com details` disclosure. The renderer doesn't
care which engine produced the record; it just shows the
engine's disclosure if expanded.

The new renderer is **one function**. The engine-specific
bits are in a separate `render_engine_details(record, engine)`
function that dispatches on `engine.name`. Adding a new
engine = writing a new `render_<engine>_details` function +
providing the engine-agnostic shape. No renderer changes.

### Decisions export: TWO buttons, sidecar persistence

The user requirement: the view.html v2 must serve two
purposes. **(1)** A reviewer needs to see all the candidates,
pick the right one, and have the picks sent to a downstream
application (the user's other app, which reads the
`FindaGraveScraper.user.js` export shape). **(2)** The picks
must persist across sessions and machines, even though the
users can't run Python.

The chosen design:

- **Two export buttons** in the view.html.
- **A sidecar file** (`decisions.json`) next to the existing
  `state.jsonl` + `view.html` for cross-session persistence.

### File layout in `output/<runname>/`

```
output/<runname>/
  results.jsonl            # engine output, immutable after the batch
  view.html                # the review UI (embedded data, self-contained)
  spouse_followups.jsonl   # optional, from J16
  decisions.json           # NEW: the reviewer's decisions
```

`decisions.json` is the durable source of truth for the
reviewer's work. `state.jsonl` is the engine's output, untouched
after the batch.

### `decisions.json` shape

```jsonc
{
  "version": 1,
  "exported_at": "2026-07-20T03:15:00Z",
  "decisions": {
    "272": {
      "memorial_id": "14994932",
      "notes": "Spouse matches; correct person.",
      "removed_candidates": ["14994933"],
      "candidate_notes": {
        "14994932": "correct match"
      },
      "decided_at": "2026-07-20T03:15:00Z"
    },
    "298": {
      "decision": "no_match",
      "notes": "No FaG result; manual check recommended.",
      "decided_at": "2026-07-20T03:15:30Z"
    }
  }
}
```

Same shape as today's `Export` payload's `decisions` map.
Just on disk instead of in localStorage. The view.html
auto-loads it at page open.

### view.html v2 buttons

The header has these actions, left to right:

- **Save decisions** (the big green button the user asked
  for). Writes the in-memory `decisions` map to a Blob and
  triggers a download of `decisions.json`. The user drops
  the file in their `output/<runname>/` directory (overwrite
  if it exists). **This is the only path to disk from the
  view.** No file system lock issues; the browser does a
  Blob download.
- **Export picks (scraper shape)**. Writes a flat list in
  the `FindaGraveScraper.user.js` shape, one record per picked
  FaG memorial. Downloads as `memorials_archive.json`. The
  user sends this to the downstream app.
- **Import** (today's button). Loads a previous export.

### view.html v2 load behavior

1. **On page open**, view.html does `fetch('decisions.json')`
   relative to its own URL. If 200, the `decisions` map is
   loaded; a banner shows: `Loaded 200 decisions from
   decisions.json.`. If 404, the load is silent (no banner).
2. **As the user picks / un-picks / adds notes**, the
   in-memory `decisions` map updates. localStorage is also
   updated so a refresh without reloading `decisions.json`
   keeps the work.
3. The view does **not** auto-save to disk. The user clicks
   "Save decisions" when ready. This avoids the file-locking
   problem the user asked about (auto-save would race with
   the browser's own download handler on Windows).
4. The view's "Decided" / "Undecided" filter view shows the
   picked/none_match/follow_up records vs the rest.

### Picked hides others (within-record)

When the user picks a candidate in a record:
- The record's card shows **only the picked candidate** + a
  "PICKED" badge.
- The other candidates collapse. A "Show all candidates"
  link expands them (for the reviewer's sanity check).
- The picked record is the source of truth for the
  scraper-shaped export; the unpicked candidates are
  excluded from the export.

Across the run:
- A "Decided" filter view shows records with any decision
  (picked / none_match / follow_up / removed).
- The "Undecided" view shows the rest. This is the user's
  working view by default.

### `memorials_archive.json` shape (the scraper-shaped export)

The downstream app reads the scraper's flat list:

```jsonc
{
  "memorial_id": "12345678",
  "name": "Jane Doe",
  "url": "https://www.findagrave.com/memorial/...",
  "birth_date": "12 Jan 1820",
  "birth_location": "Springfield, Illinois, USA",
  "death_date": "3 Mar 1894",
  "death_age": 74,                 // int or null
  "death_location": "Chicago, Illinois, USA",
  "burial_cemetery": "Rosehill Cemetery",
  "burial_location": "Chicago, Cook County, Illinois, USA",
  "biography": "Daughter of ...; wife of ...",
  "family_parents": ["John Doe", "Mary Roe"],
  "family_spouse": "James Smith",
  "family_children": ["Alice Smith", "Bob Smith"],
  "scraped_at": "2026-07-01T14:32:10.000Z"
}
```

The view.html v2 export shape is the same list, with each
record representing one picked FaG memorial. Reviewer
decisions attach as **extra fields** (prefixed with `_` so
they don't collide with the scraper schema):

```jsonc
[
  {
    // Same shape as the scraper record (auto-populated from
    // the FaG candidate's `details` block):
    "memorial_id": "14994932",
    "name": "Nancy Alice Haynes Eads",
    "url": "https://www.findagrave.com/memorial/...",
    "birth_date": "1846",
    "death_date": "1927",
    "death_age": null,
    "burial_cemetery": "",
    "burial_location": "",
    "family_parents": [],
    "family_spouse": "James Miller Eads",
    "family_children": [
      "John Haynes Eads",
      "Mary Velma Eads",
      ...
    ],
    "scraped_at": "2026-07-20T03:00:00Z",

    // Reviewer-decision extensions (the view.html v2 additions):
    "_source_pensioner_id": 272,
    "_source_pensioner_name": "Nancy A. Eads",
    "_source_strategy": "B1-exact",
    "_reviewer_decided_at": "2026-07-20T03:15:00Z",
    "_reviewer_notes": "Looks right; spouse matches.",
    "_removed_candidates": [],
    "_candidate_notes": {},
    "_corroboration": {
      "cgr_match_strength": "none",
      "dd_match": false,
      "spouse_match": true
    }
  },
  // ...
  {
    // A 'no match' pensioner. The user marked this as
    // 'no_match' (no FaG candidate was right). It's exported
    // with a flag so the downstream app can skip it.
    "memorial_id": "",
    "name": "",
    "_source_pensioner_id": 298,
    "_source_pensioner_name": "J. D. Farrar",
    "_reviewer_decided_at": "...",
    "_reviewer_decision": "no_match",
    "_reviewer_notes": ""
  }
]
```

The file is named `memorials_archive.json` (matches the
scraper convention) so `process_ledger.py` and the
downstream app consume it without a rename.

### Mapping the FaG candidate to the scraper shape

A per-engine projection (`fag_candidate_to_scraper_record`).
The FaG-specific fields populated:

- `memorial_id` ← `candidate.memorial_id`
- `name` ← `candidate.name`
- `url` ← `candidate.backlink`
- `birth_date`, `death_date` ← `candidate.details.birth_year`,
  `candidate.details.death_year` (year only; the full
  scraper parses more)
- `burial_cemetery`, `burial_location`,
  `birth_location`, `death_location` ←
  `candidate.details.{cemetery,state}` (limited; the full
  scraper does multi-section extraction; for this slice
  the view.html v2 has the basics and a future slice can
  add the rich extraction)
- `family_parents`, `family_spouse`, `family_children` ←
  empty in this slice (would require a separate memorial
  page fetch)
- `biography` ← empty in this slice (same reason)
- `death_age` ← computed from birth/death years (or null)
- `scraped_at` ← `new Date().toISOString()` (the export time)

The richer extraction (family, biography, full locations)
is a future slice that adds a "deep scrape" pass to the
pipeline. For this slice, the view.html v2 export is
**backward-compatible enough** that the downstream app
works (the optional fields default to empty strings or
empty arrays).

### Test plan

A new test (`test_view_html_v2.py`) checks the new view.html
v2 against a fixture past-run JSONL:

- Open a fixture `output/test-batch-25/results.jsonl`.
- Apply a fixture `decisions.json` with N decisions.
- Verify the picks are loaded; the "Decided" filter view
  shows N; the "Undecided" view shows the rest.
- Pick a candidate in a record; verify the unpicked
  candidates collapse; the "PICKED" badge appears.
- Click "Save decisions" → download a Blob; verify the
  content is the right decisions.json shape.
- Click "Export picks" → download a Blob; verify the
  content is the right scraper-shaped list (one record per
  picked memorial, with `_source_pensioner_id` and friends).

### Why no CLI

The constraint: "users who won't be able to run python." A
CLI writeback command would require Python on the user's
machine. The browser-only flow (download decisions.json,
download memorials_archive.json) works on any machine with
a browser. The user sends the export to the downstream
app; the downstream app consumes the same shape as the
scraper. **No Python required in the review workflow.**

The Python pipeline is for running the batch. The review
workflow is browser-only.

### What I am NOT doing in this slice

- **No wire-format change.** The `state.jsonl` shape is
  unchanged. The new view.html adapts to the old shape; a
  v2 wire format is a separate work.
- **No Newspapers.com details.** The disclosure is a stub.
  A future slice fills it in.
- **No engine-agnostic projection in the engine code.** Today
  FaG produces FaG-shaped candidates; the view.html does the
  remap. A future slice moves the remap into the engine's
  `search_one` (per the design plan from the prior turn).
- **No "compare" modal polish.** The compare view is
  functional but the styling is minimal.
- **No new filter facets.** The status / engine / decision
  filters are the three; future slices can add more.
- **No multi-engine mixed runs.** A run is one engine; a
  future slice can show a side-by-side view.

---

## Implementation slice plan

4 commits. Each is independently reviewable; the user can
react to each one. Past runs in `output/` provide the
test fixtures.

### Commit 1: layout rework (engine-agnostic in structure, FaG data still)

- New `view.html` (replaces the current one). ~1500 lines.
- Reads the existing `state.jsonl` shape.
- The engine-agnostic projection layer is a single function
  `fag_evidence_to_common(candidate)` that maps FaG's
  `score_breakdown` to the common feature names.
- All existing tests pass (the wire format is unchanged).
- A new test (`test_view_html_layout.py`) checks the new
  layout against a few past runs (es-fresh-run, test-batch-25).

### Commit 2: collapse + filter + compare

- Per-record collapse (`⌃` triangle).
- Engine filter (engine-agnostic; populated from the data).
- Decision filter (picked / none_match / follow_up / undecided).
- `compare top 3` button + modal.
- "Picked hides others" within-record UX.
- Test that the new affordances work.

### Commit 3: two export buttons + sidecar persistence

- New "Save decisions" button (the big green one). Downloads
  `decisions.json` with the in-memory decisions map.
- New "Export picks (scraper shape)" button. Downloads
  `memorials_archive.json` in the scraper shape.
- Auto-load `decisions.json` on page open (with banner).
- A test (`test_view_html_v2.py`) checks the new buttons
  + sidecar against a fixture.

### Commit 4: engine-agnostic scaffolding for future engines

- A new `render_engine_details(record, engine)` function that
  dispatches on `engine.name`.
- FaG's details are in a `render_fag_details(record)` function.
- Newspapers.com gets a stub `render_newspapers_details(record)`
  that shows a "UI coming" placeholder.
- The new view.html renders these details in a disclosure.
- A test that the dispatcher works for both engines.

---

## Open questions for the user

1. **Should the engine-agnostic data shape work happen in
   this slice, or as a follow-up?** My recommendation:
   follow-up. The current slice is layout-only; the engine
   shape work is a separate ~1-2 week slice.

2. **Should the `score_breakdown` features be the generic
   names (last_name, first_name, year_window) or the FaG
   names (last, first, year) for now?** My recommendation:
   generic, with a remap layer. A future Newspapers.com
   details disclosure will use the generic names naturally.

3. **Should the per-record collapse be a user setting
   (default expanded) or a user-driven click?**
   My recommendation: default expanded (matches today's
   behavior), click to collapse. A "collapse all" / "expand
   all" button at the top is a small addition.
