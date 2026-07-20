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
5. The picks to be exportable in a shape the user's other
   app already consumes (the `FindaGraveScraper.user.js`
   export shape).
6. The picks to persist across sessions and machines
   **without** running Python (the user base can't run it).

The "engine-aware scaffolding" point matters: the new layout
should be one function that renders a generic record card,
with engine-specific details behind a disclosure. Adding a
new engine means writing the engine-specific disclosure, not
rewriting the renderer.

### What the user workflow actually looks like

1. User runs a batch (today: 7,709 pensioners → FaG search →
   `results.jsonl`).
2. User opens `view.html` in a browser.
3. The view auto-loads `decisions.json` from the same dir if
   it exists; shows a banner: "Loaded N decisions."
4. User reviews the records. For each, they pick the right
   candidate (or mark "no match"). Notes and removes are
   available.
5. When the user is done with a session, they click
   "Save decisions" → a `decisions.json` file is downloaded.
6. The user moves the file to the output dir (overwriting
   the previous one).
7. The user clicks "Export picks (scraper shape)" → a
   `memorials_archive.json` file is downloaded. They send
   this to their downstream app.
8. On the next session, the user reloads `view.html`. The
   picks load from `decisions.json`. Their work is
   preserved.

**No Python is involved in any of the review steps.** The
pipeline is for running the batch; the review is
browser-only.

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
│ [show all 12]  [FaG details ⌄]                          │
├──────────────────────────────────────────────────────────┤
│ REVIEWER NOTES  [free-text area________________]         │  <- row 4: notes
└──────────────────────────────────────────────────────────┘
```

The header at the top of the page has the action buttons:

```
┌──────────────────────────────────────────────────────────┐
│ Search results — es-fresh-run (7,709 records)            │
│ Stats: 200 decided · 500 auto · 1,200 needs_review ...  │
│ Filters:  [engine ▾] [status ▾] [decision ▾]  search:   │
│           [findagrave ▾] [auto_accept ▾] [undecided ▾] [ ]│
│ [ Save decisions ]  [ Export picks (scraper shape) ]    │  <- two export buttons
│ [ Import ]          [ Collapse all ]  [ Expand all ]    │  <- import + collapse
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
  none_match / follow_up" — the reviewer's view of their
  work. Implemented as a single-select filter dropdown.
- **Search** (today): free-text by name/ID — unchanged.
- **Stats bar** (today): decided/auto/ambiguous pills — moved
  to a left-side rail; right side gets the filters.

A **Decided / Undecided** toggle is part of the decision
filter. The Undecided view is the user's working view by
default; switching to Decided shows records the user has
picked / none_match / follow_up. (Not a separate page; just
a filter state.)

### What the engine-aware scaffolding looks like

The state.jsonl that today ships from the pipeline is
**FaG-shaped** (no `engine` field; fields are `memorial_id`,
`slug`, `backlink`, `iiif_url`, `score_breakdown` with FaG
feature names). The new view.html is **engine-agnostic in
layout** (one renderer, one normalization layer, engine-
specific details behind a disclosure) but it **reads the
FaG-shaped data unchanged**. The engine abstraction lives
inside the view, not in the data.

**One normalization function at the top of the view.html**
is the single point of FaG→common mapping. Everything
downstream uses the normalized shape:

```javascript
// Single point of FaG→common mapping. The renderer never
// sees c.memorial_id; it sees c.id.
function normalizeRecord(rec) {
    const cands = (rec.fag_records || []).map(c => ({
        id:         c.memorial_id,
        title:      c.name,
        url:        c.backlink,
        score:      c.score || 0,
        evidence: {
            score_breakdown: fagEvidenceToCommon(c.score_breakdown),
            // Engine-specific data lives in `raw` for the
            // engine-specific disclosure.
            raw: c,
        },
    }));
    return {
        id:    rec.pensioner_id,
        title: rec.pensioner_name,
        // Engine name: today's records are all FaG, so we
        // hardcode the default. When the v2 wire format lands,
        // this reads from `rec.engine`. A one-line change.
        engine: rec.engine || 'findagrave',
        attributes: {
            // FaG-specific fields live in `attributes` for the
            // engine-specific disclosure.
            first: rec.pensioner_first, last: rec.pensioner_last,
            regiment: rec.regiment, /* ... */
        },
        status: rec.fag_status || 'unknown',
        best_score: rec.best_score || 0,
        candidates: cands,
        corroboration: {
            cgr: rec.cgr_records || [],
            dd_match: rec.dd_match || null,
            spouse_match: rec.spouse_match || null,
        },
    };
}

// Map FaG's score_breakdown feature names to the common
// names. Today's features: last, first, middle, ok_burial,
// state, veteran, death. Common: last_name, first_name,
// middle_name, year_window, state, ok_burial, other.
function fagEvidenceToCommon(bd) {
    if (!bd) return {};
    return {
        last_name:   bd.last || 0,
        first_name:  bd.first || 0,
        middle_name: bd.middle || 0,
        year_window: bd.death || 0,
        state:       bd.state || 0,
        ok_burial:   bd.ok_burial || 0,
        veteran:     bd.veteran || 0,
    };
}
```

The renderer downstream uses `record.candidates[i].id`,
`record.candidates[i].title`, `record.candidates[i].url`,
`record.candidates[i].score`, `record.candidates[i].evidence.score_breakdown`
— engine-agnostic names. The FaG-specific fields (IIIF image,
`_found_by`, full `score_breakdown` feature list) live in
`record.candidates[i].evidence.raw` and are shown in the
**`FaG details`** disclosure.

The engine badge in the card header reads `record.engine`.
Today's records are all FaG; the field defaults to
`"findagrave"` if missing. When the v2 wire format lands,
this becomes `record.engine.name` from the wire format.

The new renderer is **one function**. The engine-specific
bits are in a separate `render_engine_details(record, engine)`
function that dispatches on `engine.name`. Adding a new
engine = writing a new `render_<engine>_details` function.
The renderer itself doesn't change.

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

The sidecar is the **same shape as today's `Export` payload**
so users with existing tooling keep working. The view.html
that produced it stays the same; only the storage target
changes (localStorage → disk file).

```jsonc
{
  "version": 1,
  "exported_at": "2026-07-20T03:15:00Z",
  "source_file": "results.jsonl",
  "stats": {
    "total_pensioners": 50,
    "decided": 12,
    "by_status": {
      "auto_accept": 4,
      "needs_review": 6,
      "no_results": 40
    },
    "by_cgr_dedup": {}
  },
  "decisions": {
    "272": {
      "decision": {
        "memorial_id": "14994932",
        "slug": "nancy-alice-eads",
        "by": "user",
        "at": "2026-07-20T03:15:00Z",
        "notes": "Spouse matches; correct person.",
        "removed_candidates": ["14994933"],
        "candidate_notes": {
          "14994932": "correct match"
        }
      },
      "pensioner": { /* full pensioner record, self-contained */ },
      "candidates": [ /* full candidate list, self-contained */ ],
      "cgr_dedup_status": "follow_up_candidate",
      "cgr_match_summary": null
    },
    "298": {
      "decision": {
        "memorial_id": null,
        "slug": null,
        "by": "user",
        "at": "2026-07-20T03:15:30Z",
        "notes": "No FaG result; manual check recommended.",
        "removed_candidates": [],
        "candidate_notes": {}
      },
      "pensioner": { /* ... */ },
      "candidates": [],
      "cgr_dedup_status": null,
      "cgr_match_summary": null
    }
  }
}
```

The view.html that produces this is the same as today's
`Export` button — no JS change. The new "Save decisions"
button just calls the existing `exportDecisions()` function
and triggers a download of the resulting JSON as
`decisions.json`. The view.html's existing `Import` button
already knows how to load this shape (via `parseInput` +
`applyLoaded`).

**Why the full record context is preserved:** if the user
later loses `state.jsonl` (corruption, deletion), the picks
are still recoverable from `decisions.json` because each
record has the full pensioner + candidates snapshot. This
matches the existing v1 export's design intent.

**Filename handling.** The download's suggested filename is
`decisions_<runname>.json` (e.g. `decisions_test-batch-25.json`)
so the user can identify which run it belongs to. The
view.html also accepts a sidecar named just `decisions.json`
when the run is single-run (e.g. the user dropped the file
in a run-specific dir). On page open, the view auto-loads in
this order:
1. `decisions_<basename>.json` (where basename matches the
   current `results.jsonl`'s path), if present.
2. `decisions.json` in the same dir, if present.
3. localStorage (legacy, for backward compat with v1 sessions).

If the user downloaded to their Downloads folder and
forgot to move the file, the view shows a banner: "No
decisions file found in this directory. Save and re-load, or
move the downloaded file here and reload."

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

Four layers of tests. The view.html is a single static
file; tests run it through a headless browser (Playwright
already a project dep) and assert on rendered output +
button behaviors.

**Unit tests** (`tests/test_view_html_normalize.py`):

- `normalizeRecord(rec)` produces the expected engine-agnostic
  shape for a typical FaG record (id, title, engine, attributes,
  status, best_score, candidates[], corroboration).
- `fagEvidenceToCommon(bd)` maps the FaG feature names to the
  common names. `last` → `last_name`, `death` → `year_window`,
  etc. Empty bd returns empty object.
- `candidateToScraperRecord(cand, source_pensioner)` produces
  the scraper-shaped record from a FaG candidate. Required
  fields (`memorial_id`, `name`, `url`) populated; review
  extensions (`_source_pensioner_id`, `_reviewer_decided_at`)
  attached. `no_match` records produce a record with empty
  scraper fields and a `_reviewer_decision` flag.
- `pensionersToScraperExport(pensioners, decisions)` produces
  the full export list (one record per picked FaG memorial +
  one per `no_match` pensioner).

**Integration tests** (`tests/test_view_html_v2.py`):

- Open a fixture `output/test-batch-25/results.jsonl` in
  Playwright; verify the page renders N record cards.
- Auto-load a fixture `decisions.json`; verify N records
  show the PICKED badge; verify the Decided filter view
  shows N; the Undecided view shows the rest.
- Click "Save decisions" → the page triggers a download;
  the downloaded Blob's content matches the v1 export shape.
- Click "Export picks" → the downloaded Blob's content is
  the scraper-shaped list; one record per picked FaG
  memorial; `_source_pensioner_id` is the pensioner_id from
  the source record.
- Pick a candidate in a record; verify the unpicked
  candidates collapse; the "PICKED" badge appears; the
  "Show all candidates" link re-expands them.
- Click the ⌃ triangle on a card; verify the card collapses
  to the summary line; click again to expand.
- Apply the Engine filter "findagrave"; verify only FaG
  records show. (Today: all records. After the v2 wire
  format: a Newspapers.com run has a different badge.)
- Click the Import button with a fixture decisions.json
  file; verify the picks load and the records show the
  PICKED badge.

**Backward-compat tests:**

- Old `view.html` runs (the existing test suite, which
  passes today, stays passing) — the refactor is in a new
  `view_v2.html`; the old `view.html` is unchanged.
- Old `decisions` envelope export (the v1 shape with
  `kind: 'export'`) loads correctly in v2.

**Visual regression tests** (manual, not automated for this
slice):

- Render the new view.html against a real past run
  (`output/es-fresh-run/`); eyeball that the layout reads
  well. Iterate on the CSS until the user signs off.
- Test the "save decisions" flow end-to-end: open the view,
  make a pick, save, move the file, reload, verify the pick
  is back.
- Test the "export picks" flow end-to-end: open the view,
  make picks, export, hand the file to the user's downstream
  app, verify it consumes it.

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
- **No "compare" side-by-side view.** The hardest review job
  is picking between two close-score candidates; a future
  slice adds a "compare top 3" modal. Out of scope for now.
- **No new filter facets.** The status / engine / decision
  filters are the three; future slices can add more.
- **No multi-engine mixed runs.** A run is one engine; a
  future slice can show a side-by-side view.
- **The "no_match" decision does not hide candidates** (the
  rule is "picked hides others", not "decided hides others").
  A no_match record still shows the full content.

---

## Implementation slice plan

4 commits. Each is independently reviewable; the user can
react to each one. Past runs in `output/` provide the
test fixtures.

**Important constraint:** the refactor is in a NEW file
`scripts/view_v2.html` (or a path like `scripts/view/v2.html`
if we want a folder). The existing `scripts/view.html` stays
unchanged for backward-compat with old runs. The pipeline
generates the new view.html (or the user copies it into the
output dir).

A flag in `scripts/run_unified.py` controls which view.html
is generated. Default: v2 for new runs. Old runs in the
output dir still have the v1 view.html from the previous
batch; the user can opt-in to v2 for those by re-running.

### Commit 1: layout rework (engine-agnostic in structure, FaG data still)

- New `scripts/view/v2.html` (~1500 lines).
- Reads the existing `state.jsonl` shape.
- A `normalizeRecord(rec)` function at the top: the single
  point of FaG→common mapping.
- A `fagEvidenceToCommon(bd)` function: maps FaG feature
  names to generic names.
- The renderer uses the normalized shape; FaG-specific
  fields live in `record.attributes` and
  `record.candidates[i].evidence.raw` for the engine
  disclosure.
- Engine badge in the card header (default "findagrave").
- All existing tests pass (the wire format is unchanged).
- New tests:
  - `tests/test_view_html_normalize.py` (unit tests for the
    normalize + remap functions).
  - `tests/test_view_html_v2_layout.py` (Playwright
    integration tests against a fixture past run).

### Commit 2: collapse + filter + "hide others"

- Per-record collapse (`⌃` triangle; default expanded).
- "Collapse all" / "expand all" buttons at the top.
- Engine filter (engine-agnostic; populated from the data).
- Decision filter (all / undecided / picked / none_match /
  follow_up).
- "Picked hides others" within-record UX (the picked
  candidate is shown; others collapse; "Show all
  candidates" expands them).
- New tests:
  - `tests/test_view_html_v2_filters.py` (Playwright).

### Commit 3: two export buttons + sidecar persistence

- New "Save decisions" button (the big green one). Downloads
  `decisions.json` in the v1 export shape. Suggested filename
  is `decisions_<runname>.json`.
- New "Export picks (scraper shape)" button. Downloads
  `memorials_archive.json` in the scraper shape.
- Auto-load `decisions.json` (or `decisions_<runname>.json`)
  on page open. Banner shows: "Loaded N decisions from
  <filename>."
- A `candidateToScraperRecord(cand, source_pensioner)` and
  `pensionersToScraperExport(pensioners, decisions)` function
  in the view.html.
- New tests:
  - `tests/test_view_html_v2_exports.py` (Playwright:
    trigger the download, parse the Blob, assert the
    content).
  - `tests/test_view_html_v2_sidecar.py` (load + reload
    flow: write a fixture decisions.json, open the view,
    verify the picks load).

### Commit 4: engine-agnostic scaffolding for future engines

- A new `render_engine_details(record, engine)` function that
  dispatches on `engine.name`.
- FaG's details are in a `render_fag_details(record)` function.
- Newspapers.com gets a stub `render_newspapers_details(record)`
  that shows a "UI coming" placeholder.
- The new view.html renders these details in a disclosure.
- A test that the dispatcher works for both engines.

---

## Decisions log

The user-facing decisions baked into this design (signed off
during the design review):

- **Engine-agnostic data shape** (v2 wire format) is a
  follow-up, not this slice. The view.html v2 reads today's
  FaG-shaped data via a `normalizeRecord()` layer.
- **`score_breakdown` features** use generic names
  (`last_name`, `first_name`, `year_window`, `state`,
  `ok_burial`, `other`) with a remap from FaG's
  `last`/`first`/`middle`/`ok_burial`/`state`/`veteran`/`death`.
- **Per-record collapse** is a user-driven click, default
  expanded. A "collapse all" / "expand all" button is a small
  addition.
- **Picks hide others** applies to picks only, not to
  "no_match" decisions. A no_match record still shows the
  full content; the user explicitly decided "no result here."
- **Exports are two buttons**: "Save decisions" (downloads
  `decisions.json` in the v1 export shape) and "Export picks"
  (downloads `memorials_archive.json` in the scraper shape).
- **State persistence is browser-only** (no Python). The
  sidecar is `decisions.json`; localStorage is the legacy
  fallback. The view auto-loads the sidecar at page open.
- **Compare mode is not in this slice.** It's a useful
  feature but a 1-2 day add. Deferred to a follow-up.

## Future work (out of scope for this slice)

- v2 wire format (engine-agnostic `state.jsonl`).
- Newspapers.com details disclosure (today: stub).
- "Compare top 3" side-by-side view for close-score candidates.
- Richer extraction in the scraper-shaped export (family,
  biography, full locations). Today: minimal; a future slice
  adds a "deep scrape" pass to the pipeline.
- Per-engine UI badges: today the badge is just text
  (`[FaG]`, `[Newspapers.com]`); a future slice adds engine
  icons + colors.
