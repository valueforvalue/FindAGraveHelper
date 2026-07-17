# Changelog

All notable changes to this project.

## [Unreleased] — 2026-07-17

### es-fresh-run: 177 E-last-name pensioners, end-to-end pipeline

First run with ALL features enabled (auto-relax + spouse scrape
+ top-N=3) on a fresh batch. The 177 pensioners whose last name
starts with E (Eads ... Ezell).

Headline results (1.5s throttle, 41 minutes wall clock):

  - 177/177 processed, 0 errors, 66 outliers
  - 37 BOTH MATCH (CGR corroborated)
  - 6/177 already in dixiedata (DD match)
  - 47/132 spouse captures (35.6% fill rate)
    27 strong + 20 medium + 0 weak
  - 88 auto-relax events; 28 widened to US, 16 kept OK
  - 3 spouse matches at rank > 1 caught by top-N=3:
      - #4257 Belli Earls (rank 2, strong)
      - #7547 Sarah S Ellis (rank 2, strong)
      - #8727 Margaret C. Ellis (rank 3, medium)

### view.html second-pass embed: regex fix

The second-pass embed check used a naive substring search
for 'id="embedded-..."'. The source view.html has the literal
string inside JS comments (in the docstring explaining how
the embed works), so the check returned True even when no
<script> tag existed. The second pass then SKIPPED embedding
results.jsonl, dd_match.json, and spouse_match.json into the
per-run view.html. The page loaded with zero pensioner cards.

  - scripts/pipeline/run_unified.py: the second-pass embed
    check now uses a regex that requires both the
    <script type="application/json" id="..."> opening AND a
    JSON `{` brace immediately after. Comments never have
    both adjacent.
  - tests/test_per_run_isolation.py: the byte-identical
    comparison now strips actual embed blocks using the same
    strict regex.
  - tests/test_embed_detection_bug.py: 5 new regression tests
    pinning the bug and the fix.

The fix was discovered when es-fresh-run's view.html loaded
with 0 cards instead of 177; the J9 embed had been silently
skipped for several previous runs (it would only have been
correct when the source happened to be an empty placeholder,
which it never is in practice).

### SPOUSE_SCRAPE_TOP_N env var

scripts/pipeline/run_unified.py now reads SPOUSE_SCRAPE_TOP_N
(default 1) to pass through to the spouse scrape subprocess.
This lets the runner pick top-N for the gold-badge matching
without code changes. Used as 3 in es-fresh-run.

### Enhancement #14: top-N>1 in scripts/cgr/spouse_compare.py

When the top-1 FaG candidate is a same-name modern person
(name collision) and the ACW-era veteran is at rank 2+, the
previous top_n=1 cap dropped that match silently. Now:

  - scripts/cgr/spouse_compare.py:annotate_records iterates
    top_n candidates in rank order; first match wins.
  - Each candidate's outcome is recorded in a new
    `spouse_candidates` array on the per-record state:
    `[{rank, memorial_id, slug, captured_first/middle/last,
    captured_display, match: {matched, matched_via,
    match_strength, matched_via_rank, skipped}}]`
  - Once a match is found, remaining candidates in the
    top-N window are marked `match.skipped: true` (no
    wasted cycles, but the audit trail shows what we tried).
  - The stats sidecar now includes `matched_rank_histogram`
    so the reviewer can see how many matches came from
    each rank position.
  - scripts/view.html:renderSpouseMatchBadge surfaces rank
    > 1 with a "matched at rank N" note in both the badge
    text AND the tooltip. The reviewer sees explicitly that
    the top candidate was different.

Live behavior unchanged at top_n=1 (default).

Tests: tests/test_spouse_compare_topn.py (6 new) — top_n=1
default skips non-top, top_n=3 finds rank-2 match, top_n=3
with no match records all 3 candidates as None, top_n caps
at fag_records length, no spouse data writes empty
candidates, view.html rank note pin.

Issue: https://github.com/valueforvalue/FindAGraveHelper/issues/14

### Enhancement #15: auto-relax FaG state filter

When --fag-state-filter OK returns nothing useful (no
high-score candidate AND not auto_accept), retry the search
with state_filter="US" and use whichever candidate set is
larger. Opt-in via env var FAG_AUTO_RELAX=1. Skipped
silently otherwise.

  - scripts/fag/fag_browser.py:
    - New helper _should_broaden(record, threshold=0.3):
      returns True when the narrowed search returned no
      useful candidate (status != auto_accept AND no
      candidate scored >= 0.3).
    - New auto-relax block in fag_search(): gated on
      FAG_AUTO_RELAX=1 AND state_filter == "OK" AND
      _should_broaden(record). When triggered, runs a
      second search_one_pensioner with state_filter="US",
      compares candidate set sizes, and replaces the OK
      record with the broader one only when US returned
      strictly more candidates.
  - Why env-var-gated: legacy OK-only behavior is
    preserved by default. Operators who want auto-relax
    opt in.
  - Why US (country_4) and not global: US-wide is the
    smallest broadening step that's still meaningful for
    an ACW-vet search; global would include international
    candidates that are almost certainly wrong.

Tests: tests/test_auto_relax_j15.py (14 new) —
_should_broaden happy paths + edge cases (missing score,
non-numeric score, custom threshold), env-var gating
(default off, =1 on, =true on, =0 off), source-code pins
for FAG_AUTO_RELAX gating + US scope + length comparison.

Issue: https://github.com/valueforvalue/FindAGraveHelper/issues/15

### J15-S2: FaG memorial-page scrape + spouse comparison (gold badge data)

The gold "♥ Spouse match" badge is now populated by an
actual end-to-end scrape of the top-1 candidate's memorial
page. Read-only on FaG; opt-in via `FAG_SCRAPE_SPOUSE=1`.

**Pipeline:**

  - scripts/fag/spouse_scrape.py (new, ~19KB):
    - parse_spouse_from_html(html): walks a memorial page's
      Family Members section. Handles BOTH the legacy
      `<p><strong>Spouse</strong></p>` markup AND the current
      `<b id="spouseLabel" class="label-relation">Spouse</b>`
      pattern (verified 2026-07 from a real memorial fetch).
    - _split_name (first/middle/last), _norm (lowercase +
      suffix strip), _strip_tags (HTML cleanup).
    - compare_spouses(local, captured): returns a compare dict
      on match, None otherwise. Three match strengths:
        - `strong` (first + last + middle all match)
        - `medium` (last name + first-initial match; tolerates
          middle variations and 'Mitchel' vs 'Mitchell'
          spelling drift)
        - `weak` (last name only)
    - scrape_and_compare(page, candidate, local_spouse): the
      top-level helper. Navigates the page, parses, compares,
      returns the match dict.
    - CLI: `python -m scripts.fag.spouse_scrape --memorial
      <id> [--expected "Name Last"]` for one-off smoke tests.

  - scripts/cgr/spouse_compare.py (new, ~9KB):
    - The post-pipeline orchestrator. Walks results.jsonl,
    reads top-1 fag_records for each pensioner that has
    pensioner_spouse_* populated, scrapes the memorial,
    writes `spouse_match` back to the record.
    - Spins a fresh chromium+stealth+warmup browser (the
      per-record search loop's browser has already closed
      by this point; reusing sync_playwright in the same
      process fails with 'Playwright Sync API inside the
      asyncio loop').
    - Opt-in via env var `FAG_SCRAPE_SPOUSE=1`. No-op
      otherwise.

  - scripts/pipeline/run_unified.py:
    - Wires the spouse scrape via SUBPROCESS so it gets a
      fresh asyncio event loop + python interpreter
      (avoids the playwright-sync-asyncio reuse bug).
    - Added EMBEDDED_SPOUSE_MATCH_PLACEHOLDER + sidecar
      embed mirroring the dd_match.json pattern.

  - scripts/view.html:
    - renderSpouseMatchBadge reads m.dd_memorial_id OR
      m.captured_memorial_id (both paths supported).
    - Renders captured_display (full name) over the
      reconstructed first+last, so the tooltip shows
      'Mitchell Ward Slemp' not 'Mitchell Slemp'.
    - New <!--EMBEDDED_SPOUSE_MATCH_JSON--> placeholder +
      id="embedded-spouse-match" script block (J15-S2).

**Live verification on test-batch-spouse (25 widow records):**

  $ time FAG_SCRAPE_SPOUSE=1 ... python scripts/run_unified.py ...

  Scrape: 11 / 25 matched in 33 seconds at 1.5s throttle
  Breakdown: 5 strong, 6 medium, 0 weak

  Strong hits (first + last both exact):
    - Lucinda M. Whatley -> 'Jonathan Sanders Whatley' (mem 76424346)
    - Leah Beckett        -> 'James Beckett' (memorial ID)
    - Palmira Brown       -> 'Andrew Alfred Brown'
    - Martha Calhoun      -> 'Samuel Calhoun' (mem 18498537)
    - Emley Carnes        -> 'Richard H. Carnes' (mem 33157274)

  Medium hits (last + first-initial):
    - Margaret Slemp      -> Mitchell Ward Slemp (mem 42943226)
    - Nancy H. Smith      -> Martha J. Lemasters Smith
    - Isabella R. Ward    -> Oscar Leland Alexander Ward
    - Ann Williams        -> Sarah Philena Stickleman Williams
    - Victoria T. Bean    -> Sgt Mark P. Bean
    - Emily M. Bowlin     -> Pvt David Russell Bowlin

  Remaining 14: top-1 candidate's memorial doesn't have a
  Family Members > Spouse section (record's spouse_match
  stays None; the 'Spouse known' badge still renders).

Cost: ~33s for 25 pensioners at 1.5s throttle. For a
7,709-record full run with ~50% having spouse data =
~3,800 extra page hits = ~95 min added. Future: cull
already-confirmed-strong matches, batch throttles, allow
top-N > 1 (compare against more than just the top-1).

**Tests:**

  - tests/test_spouse_scrape_j15.py (new, 21 tests): parser
    unit tests on a canonical fixture of Margaret McClure
    Slemp's memorial + 6 other fixtures + the compare_spouses
    + _split_name + _norm helpers. End-to-end via a fake
    page stub.
  - tests/test_spouse_badge_j15.py: +2 new tests pinning
    renderSpouseMatchBadge's field-name flexibility
    (dd_memorial_id + captured_memorial_id + captured_display).
  - tests/test_per_run_isolation.py: updated to strip the
    new EMBEDDED_SPOUSE_MATCH_JSON placeholder (alongside
    the existing J9/J14 placeholders) for fair comparison.
  - Tests: 21 + 2 = 23 new pass; 878 adjacent pass.

**Laws honored:**
  L4 stable key order: only ADDS `spouse_match` per record;
  no existing keys reorder.
  L7 docstrings: every new public function carries an
  L7-spec docstring with Args/Returns.
  Backward compat: when FAG_SCRAPE_SPOUSE isn't set, the
  scrape is silently skipped (records end with spouse_match=None).
  No DB writes. Read-only on FaG.

### J15-S3: spouse-match badge + filter in view.html

The user's headline ask: 'i want spouse match to have a
special badge in view.html'. Wired.

**Two badges in the pensioner card h2 row:**

  1. **Spouse known** (grey pill): shown when ok_pensioners
     carried spouse_first_name + spouse_last_name for this
     pensioner. Sourced from new pensioner_spouse_*
     fields that J15-S1's URL filter relied on (and that
     scripts/pipeline/run_unified.py::result_to_dict now
     copies into the per-pensioner JSONL record). Hover
     shows the local spouse name + (if S2 has populated
     it) the captured FaG spouse for at-a-glance compare.

  2. **Spouse match** (gold pill with ♥): shown when a
     post-pipeline comparison found the FaG-captured
     spouse AND it agrees with the pensioner's known
     spouse. Hover shows the captured name, captured
     memorial #id, and match strength. This is the badge
     the user asked for. The data field is `p.spouse_match`
     on each pensioner record; populated by the J15-S2
     memorial-page scrape (slice not yet built; see next
     steps).

**Filter dropdown:**

  - `spouse_matched` - shows only pensioners whose
    `spouse_match` field is set. Reviewer can scope to the
    verified-across-FaG set.
  - `spouse_pending` - shows only those WITHOUT a match.
    Useful for first-pass triage ('we know their spouse;
    not yet verified').

**Stats bar:** two new pills - 'Spouse matched N' (gold)
and 'Spouse known N / M' (grey; M = total).

**Pipeline plumbing:**

  - scripts/pipeline/run_unified.py::result_to_dict now
    copies pensioner.get('spouse_first_name'),
    ['spouse_middle_name'], ['spouse_last_name'] into the
    output record (previously dropped). Without this the
    badge had nothing to render.

  - view.html reads `p.pensioner_spouse_first` /
    `p.pensioner_spouse_last` for the known badge; reads
    `p.spouse_match` for the match badge. Both return ''
    when empty (no crash on old records).

**Tests:** 12 new pass in tests/test_spouse_badge_j15.py
(pinning badge presence, filter dropdown options, filter
logic, stats pills, the no-crash contract when fields are
missing).

Plus a one-off `tests/spouse_badge_smoke.py` that headlessly
renders 3 fixture pensioners and confirms:
  - With spouse_match set: BOTH badges render with correct
    memorial id + heart symbol.
  - With only pensioner_spouse_*: only the grey 'Spouse
    known' badge renders.
  - Without any spouse data: neither renders.

The next slice (J15-S2) will populate `p.spouse_match` by
scraping the top-1 candidate's memorial page for Family
Members > Spouse and comparing to the pensioner's known
spouse. Until then, the gold badge never actually appears
in real runs - the JS contract is correct but the data
isn't yet filled.

Files:
- scripts/view.html: 4 changes (badges, CSS, filter
  dropdown, filter handler, stats pills)
- scripts/pipeline/run_unified.py: result_to_dict copies
  pensioner_spouse_* (3 lines)
- tests/test_spouse_badge_j15.py (new, 12 tests)
- tests/spouse_badge_smoke.py (new; manual / on-demand)

Laws honored:
  L4 stable key order: pensioner_spouse_* added at end of
    per-record dict (insertion-order semantics).
  L7 docstrings: both new badge renderers have L7-spec
    docstrings explaining the trigger field, the local
    data source, and when the badge is silent.
  Backward compat: records that lack pensioner_spouse_*
    or spouse_match render no badge (no crash). Old
    results.jsonl without these fields still loads +
    renders cleanly.

### J15-S1: spouse name URL-param pre-filter (ok_pensioners -> FaG search)

ok_pensioners.json has spouse data on ~49% of pensioners
(3,497 of 7,709 with both first + last). We can use this
to PRE-FILTER FaG candidates via the `linkedToName` URL
parameter (FaG's spouse/parent/child/sibling-name filter,
verified 2026-07 from data/probe/search_page_advanced.html).

A candidate that comes back with linkedToName=Spouse is a
stronger match than one that doesn't - someone has already
linked the candidate's family tree to that name.

Live verification (Sarah Adams, OK, spouse Garnett Adams):
  - WITHOUT linkedToName: hundreds of candidates
  - WITH linkedToName=Garnett+Adams: 1 match
    (Sarah Elizabeth Gaines Adams 1853-1927, memorial 83891522;
    her son "Frank Garnett Adams" confirms the family link)

Implementation:

  - scripts/fag/filters.py: new `apply_spouse_filter(params,
    *, spouse_first=, spouse_last=, spouse_middle=)` returns a
    NEW dict with `linkedToName` set when both first+last
    are non-empty. Doesn't overwrite caller-set value.
    Whitespace-normalized (handles ' Garnett   Adams ').
  - apply_location_filter / apply_location_only now accept
    the same kwargs and forward to apply_spouse_filter.
  - scripts/fag/search.py: search_one_pensioner reads
    `pensioner.get('spouse_first_name')`,
    `pensioner.get('spouse_middle_name')`,
    `pensioner.get('spouse_last_name')` and threads them into
    apply_location_filter (per-strategy, after the strategy
    builds its URL params).

Tests: 10 new pass; 844 adjacent pass; 1 unrelated pre-existing
failure (test_per_run_isolation.py::test_view_html_copy_skipped_if_exists
asserts the old 'no second pass' contract; updated to match
the new 'second pass may append sidecars but never overwrites
user content' contract from J14).

Next slices (planned):
  - S2: scrape top-1 candidate memorial page for Family
    Members > Spouse; compare with ok_pensioners spouse;
    agree = strong piece of evidence.
  - S3: post-pipeline comparison + scoring boost + view.html
    badge/filter.

Laws honored:
  L4 stable key order: linkedToName added at end of params
    dict (insertion order semantics; doesn't disturb existing
    keys).
  L7 docstrings: apply_spouse_filter has an L7-spec docstring
    explaining the param, the partial-match behavior, and
    when it skips.

### J14: replace auto-enrichment with post-pipeline DD comparison

The user uses a parallel SQLite research DB (`dixiedata.db` or its
.ddbak backup) where they've already paired ~611 Confederate
vets with verified Find a Grave memorials. We previously tried
**auto-enriching** `ok_pensioners.json` from that DB at the start
of the pipeline (J13-script enrich/dixiedata_dates.py). That
approach was wrong: silent bad joins could poison the input
without the reviewer realizing.

**Replacement: a READ-ONLY post-pipeline comparison.**

  - `scripts/cgr/dixiedata_match.py` (NEW, ~10KB, 19 tests).
    Reads the user's dixiedata DB or .ddbak backup, then walks
    every results.jsonl record. For each pensioner, checks if
    the top-ranked FaG candidate's memorial_id matches one of
    the FaG IDs already tracked in DD (in any of the 3 storage
    conventions DD uses: `app_id = "FaG ID: 9121410"`, bare
    integer `app_id`, or `details = https://.../memorial/.../`).
  - Writes `dd_match: {...}` to each matched results.jsonl
    record in place. Sidecar summary at `output/<runname>/dd_match.json`.
  - Wired into `scripts/pipeline/run_unified.py` as a new step
    AFTER `cgr_fag_dedup.py`. Triggered by env vars
    `DIXIEDATA_ZIP_BACKUP` / `DIXIEDATA_DB`; silently skipped
    when neither is set. Reads dixiedata as read-only;
    **never mutates it**.
  - Match-strength: `weak` (memorial_id only) or `strict`
    (also requires DD-side slug to match - guard against
    memorial collisions/merges).

**view.html changes (J14):**
  - New `DD ✓ (mem #)` badge on pensioners whose top FaG
    match is already tracked in DD. Hover shows the DD row
    info (memorial_id, source record type, matched candidate
    rank).
  - Stats bar gets two new pills: `DD tracked N` (blue) and
    `DD pending N` (grey).
  - Status filter dropdown gets two new options:
    `DD tracked` and `DD pending`. Reviewer can hide DD-tracked
    rows for a fast first pass, or scope to them for verification.
  - New view.html placeholder (`<!--EMBEDDED_DD_MATCH_JSON-->`)
    embedded as a `<script type="application/json">` block by
    the runner (second pass, after the sidecar exists). This
    makes the page work from `file://` like the results.jsonl
    embed.

**Cleanup (J14):**
  - DELETED `scripts/enrich/dixiedata_dates.py` + the
    `ok_pensioners.dixiedata_match.json` sidecar (auto-enricher).
  - Removed 6 enricher tests from `tests/test_date_filter_j13.py`.
  - pipeline: imports `os` (was missing).

**Why this approach is safer than the old enricher:**
  - **Post-pipeline**: the comparison runs AFTER results.jsonl
    is final. The input (`ok_pensioners.json`) is never touched.
  - **Read-only on dixiedata**: the script only reads from
    the source sqlite file (or extracts the .ddbak to a temp
    dir). No writes.
  - **Visible to the reviewer**: every pensioner that the
    comparison marked gets a `dd_match` field + a badge.
    If a row was wrongly marked, the reviewer sees it
    immediately and can disagree (the badge doesn't make
    auto-decisions; it's a flag).
  - **Filterable**: the reviewer can show or hide DD-tracked
    rows at will. No silent data flow.

**Files:**
- `scripts/cgr/dixiedata_match.py` (NEW, ~10KB)
- `tests/test_dixiedata_match_j14.py` (NEW, 19 tests)
- `scripts/pipeline/run_unified.py`: wire dd match step +
  import os
- `scripts/view.html`: dd badge + filter + sidecar embed
- `tests/test_date_filter_j13.py`: remove enricher tests
- DELETED: `scripts/enrich/dixiedata_dates.py`,
  `docs/research/digitalprairie/ok_pensioners.dixiedata_match.json`,
  `docs/research/digitalprairie/ok_pensioners.with_dates.json`

**Tests:** 19 new pass; 834 adjacent pass; 1 pre-existing
failure unrelated.

**Laws honored.**
  L3: dd match writes results.jsonl in place via tmp+rename.
  L4: only ADDS `dd_match` field per record. No existing
    keys reordered or removed.
  L7: every new public function has an Args/Returns docstring
    + a "why this is safer than the old way" paragraph where
    relevant.

### J13-research: ACW-vet date ranges from real local data

The date-window constants that drive J13's URL filter and
score-zero gate were originally chosen from general
historical knowledge (1820/1870/1861/1950). After running
the full pipeline and looking at the actual distribution in
our ground-truth data, those bounds were **too narrow on
both ends**, dropping real ACW veterans and not catching
the worst modern name-collisions.

Curated artifact: `docs/research/acw-vet-date-ranges.md`
(~7.8KB), with full distribution tables and the rationale
for each bound. Highlights from the data:

**Death-year distribution (577 known-good local pairs):**
```
1860s:   11    1890s:   62     1920s:  337  (peak)
1870s:   10    1900s:  200     1930s:  138
1880s:    2    1910s:  359  (peak)  1940s:   20
                   1950s:    4     2020s:    2  <-- anomalies
```

**Birth-year distribution (1,135 records with both years):**
```
1800s:    5   1830s:  309   1850s:   42   1870s:    4
1810s:   27   1840s:  680   1860s:   10   1880s:    1
1820s:   62   (peak)         1930s:    3   (data errors)
```

**Age at death:** median 78, p10=62, p90=89, max=115.
Confirms a real ACW vet is almost certainly dead by 95.

**Updated constants:**
```python
ACW_BIRTH_YEAR_MIN = 1810  # was 1820; widened to keep 27
ACW_BIRTH_YEAR_MAX = 1880  # was 1870; widened per local data
ACW_DEATH_YEAR_MIN = 1861  # (unchanged; war starts here)
ACW_DEATH_YEAR_MAX = 1955  # was 1950; widened to keep 7 deaths 1940-55
```

This keeps 100% of the 577 ground-truth matches while
still rejecting modern same-surname candidates (the 2020s
entry was a name-collision; the 1950s+ entries are
long-lived widows or data errors worth flagging for
review but not silently dropping).

**Strict follow-up window** for "too_many" results:
`birthyear=1820&birthyearfilter=after&deathyear=1940&deathyearfilter=before`.
Survives 94% of real matches but cuts the modern
name-collision noise further.

**Files:**
- `docs/research/acw-vet-date-ranges.md` (NEW, ~7.8KB) -
  the artifact
- `scripts/fag/filters.py` - widened ACW_* constants + comment
- `tests/test_date_filter_j13.py` - 3 test updates to pin
  the new bounds

**Tests:** 822 adjacent pass; 1 pre-existing failure unrelated.

**Laws honored.** L4 stable key order. L7 docstrings on the
updated filter function explain the data-driven rationale
and point to the research artifact.

### J13: filter impossible-date candidates from FaG search (3 layers)

**Problem.** A scan of the test-batch-25 results.jsonl found
that **300 of 420 FaG candidates (71%) had death years
incompatible with an American Civil War Confederate
pensioner** (e.g. `Ralph Michael Adair 1949–2020`,
`Harold Don Akers 1920–1977`). These are modern
same-surname name-collisions, not the pensioner. They
inflate the candidate set the reviewer must triage, and
bias scoring toward noise.

**Root cause.** Three layers stacked:

1. **Source data has no dates.** `ok_pensioners.json` has
   0/7,709 records with `birth_year` or `death_year`
   populated. The DC pension roll metadata has only
   `coverage: "1910s-1950s"` (record date range), not
   the veteran's life dates.

2. **Score zero is gated on local date.**
   `scripts/fag/scoring.py:88-101` reads the
   death-year component as `if local_dy and cand_dy`.
   When `local_dy` is empty (all our pensioners), the
   death-year component is 0, making a 1920s death and
   a 2020s death indistinguishable.

3. **No URL-level date filter.** `apply_location_filter`
   scoped to OK but did NOT pass through to FaG a
   `birthyear=1820&birthyearfilter=after&deathyear=1950&deathyearfilter=before`
   URL filter. So 99%+ of candidates from a global
   search are modern by construction.

**Fix (5 layers, defense in depth).**

- **Layer 0 (data enrichment).** New
  `scripts/enrich/dixiedata_dates.py`. Joins the user's
  `C:/development/dixiedata/dixiedata-backup-*.ddbak`
  SQLite (with 662 ACW vets) against `ok_pensioners.json`
  on `(last_name, first_initial)`. Adds `birth_year` +
  `death_year` where the join succeeds. **636/7,709
  pensioners (8%) now have authoritative ACW-era dates**.
  Includes guards against dixiedata's known data-quality
  issues (e.g. one row has by=1933, dy=1926 - rejected).
  Output: `docs/research/digitalprairie/ok_pensioners.with_dates.json`
  + a count report at `docs/research/dixiedata/enrich_report.json`.

- **Layer 1 (URL filter).**
  `scripts/fag/filters.py:apply_location_filter` now
  ALSO injects the ACW date window by default
  (`birthyear=1820&birthyearfilter=after&deathyear=1950&deathyearfilter=before`).
  Verified working: `John Smith OK` returns 1,087
  candidates unfiltered; with the ACW window, 373
  candidates. `apply_location_only()` escape hatch for
  tests / strategies that bring their own scope.

- **Layer 2 (defensive score zero).**
  `scripts/fag/scoring.py:score_candidate` now returns
  `0.0` for any candidate with `birth_year` outside
  [1820, 1870] OR `death_year` outside [1861, 1950],
  regardless of local date. Defense in depth against
  anything that slips through the URL filter.

- **Layer 3 (parse-time drop).** New
  `scripts/fag/filters.py:apply_date_filter(candidates)`
  drops out-of-window candidates at the parse step.
  Conservative: candidates with no dates are KEPT.

- **Layer 4 (reviewer UI).** view.html meta row now
  shows the pensioner's `Dates: b.YYYY–d.YYYY` when
  available, or a greyed "Dates: unknown (ACW window:
  b.1820-1870, d.1861-1950)" badge otherwise. Reviewer
  immediately sees which pensioners are date-anchored
  vs date-blind.

**Single source of truth.** ACW window constants
(`ACW_BIRTH_YEAR_MIN = 1820`, etc.) live in
`scripts/fag/filters.py` and are exported; both
scoring and date-filter read from there.

**Files:**
- `scripts/fag/filters.py` — `apply_location_filter`,
  new `apply_location_only`, new `apply_date_filter`,
  new `_parse_int`, new `_in_acw_window` private helpers,
  new ACW_* constants
- `scripts/fag/scoring.py` — early-return 0.0 for
  out-of-window candidates
- `scripts/enrich/dixiedata_dates.py` (NEW, ~10KB) —
  join script with CLI, batch-mode, doc-qualified
- `scripts/view.html` — meta-row dates + missing-badge CSS
- `tests/test_date_filter_j13.py` (NEW, ~9KB, 19 tests)

**Tests:** 19 new pass; 800+ adjacent pass; 1
pre-existing failure unrelated.

**Laws honored.**
- L4 stable key order: only added fields, none reordered.
- L7 docstrings: every new public function has a L7-spec
  docstring with Args, Returns, and a "when to use this"
  paragraph.
- L3 flush-per-pensioner: enrichment is a separate
  one-shot step, not a per-pensioner hot path.

### J12: replace "source card" / "application" anchor links with JSON-modal buttons

User feedback: the per-pensioner "source card" and
"application" links opened a new browser tab to the
digitalprairie URL (which now returns a soft-404 page per
issue #13), instead of showing the parsed JSON inline. The
"View source" button in the actions row did the right thing
(loaded the JSON into a modal) but the user expected the
in-line links to behave the same.

Fix: convert both anchor tags to buttons that trigger the
existing JSON modal. The buttons live in the meta row; their
data-url points at the corresponding digitalprairie record
(pensioncard_backlink for "source card", backlink for
"application"). Clicking either button calls the same
fetchSourceJson() handler the "View source" button uses.

The buttons are styled to look like the links they replaced
(no border, underline, link color) so the meta row layout is
visually unchanged.

Verified with headless Chrome: 48 view-source buttons across
the 25 records (one per backlink per pensioner), 0 plain
anchors. Clicking the first source-card button opens the
modal with the parsed digitalprairie pension fields
(Application Number, Pension Number, Company, Regiment,
Publisher, Subject, Physical Description, Coverage, Type,
Rights, etc.).

- scripts/view.html: 2 anchor tags → 2 buttons (with
  data-action="view-source"); CSS for `.meta
  button[data-action="view-source"]` to preserve the link
  look
- tests/test_view_ux_j8.py: 2 new tests pinning the source
  card + application buttons

Tests: 2 new pass; 802 adjacent pass; 1 pre-existing failure
unrelated.

Laws honored:
  L4 stable key order: no JSONL key order changes.
  L7 docstrings: existing fetchSourceJson + renderSourceJson
  functions handle the new buttons without changes.

### J11: fix candidate-row layout (per-candidate notes squashing info column to 0 width)

User feedback (with screenshot): the candidate row was
broken — the `.info` column had `width: 0px` (verified via
headless inspection), causing the name + slug + breakdown
to wrap character-by-character while the Pick / ✕ remove
buttons took the visible space.

Root cause: `.candidate` is a flex row. `.info` had
`flex: 1; min-width: 0`, allowing it to shrink to 0. The
`.score` and `.pick` siblings had intrinsic widths
(60px + 124px) that consumed all the space. The
`.candidate-notes` was supposed to wrap onto a new row via
`flex-basis: 100%` but without `order` or `flex-shrink: 0`
the flex algorithm kept everything on one row.

Fix:
- `.candidate .info`: `flex: 1 1 auto; min-width: 280px`
  (was `flex: 1; min-width: 0`)
- `.candidate .rank`: added `flex-shrink: 0`
- `.candidate .candidate-notes`: `order: 99; flex: 1 0 100%`
  (forces a new row regardless of sibling widths)
- `.candidate .slug`: added `word-break: break-all` (so the
  monospace slug doesn't overflow the narrow info column)
- Removed the orphan `.candidate-notes` / `.candidate-notes input`
  rules that conflicted with the new `.candidate .candidate-notes`
  rules

Verified with headless Chrome: the candidate row now has
`.info` at 280px, `.score` at 60px, `.pick` at 124px, and
`.notes` on its own row at 1288px (the full card width).

- scripts/view.html: 5 CSS rule changes
- tests/test_view_layout_j11.py (new): 6 tests pinning
  the layout fixes

Tests: 6 new pass; 800 adjacent pass; 1 pre-existing failure
unrelated.

Laws honored:
  L7 docstrings: the CSS rules carry comments explaining the
    fix + the J11 history.
  L4 stable key order: no JSONL key order changes.

### J10: rich JSON export + view-mode for re-loading your own export

User feedback after J9: the CSV export was lossy (didn't
include the full FaG candidates reviewed, the full pensioner
metadata, or the CGR match summary). Reviewer needs a
self-contained export that can be reopened in a separate
session without losing context.

Two changes in one slice:

1. **Switch export to rich JSON.** The export now emits a
   self-contained payload per pensioner:

   ```json
   {
     "version": 1,
     "exported_at": "<iso8601>",
     "source_file": "results.jsonl",
     "stats": {
       "total_pensioners": 25, "decided": 2,
       "by_status": {"too_many": 14, ...},
       "by_cgr_dedup": {"duplicate": 1, ...}
     },
     "decisions": {
       "<pensioner_id>": {
         "decision": {
           "memorial_id": "...", "slug": "...", "by": "user",
           "at": "...", "notes": "...",
           "removed_candidates": ["..."],
           "candidate_notes": {"<memorial_id>": "note"}
         },
         "pensioner": { ...full pensioner record... },
         "candidates": [ ...full FaG candidates reviewed... ],
         "cgr_dedup_status": "...",
         "cgr_match_summary": {...} or null
       }
     }
   }
   ```

   Downloads as `fag-decisions-YYYY-MM-DD.json`. Import accepts
   both the new rich shape AND the old flat shape (back-compat)
   AND the pre-J8 shape. The import merges into the local
   decision store without clobbering existing edits.

2. **view.html can load + view its own export.** A new
   `loadFromText(text, sourceLabel)` helper detects the export
   shape (top-level `version` + `decisions`) and switches the
   page into a read-only "view mode" with a banner showing:
   - version + exported_at + source_file
   - stats (total pensioners, decided count, by status, by
     CGR dedup)
   - "Read-only; picks/notes are loaded from the export"

   The pensioner records are reconstructed from
   `decisions[pid].pensioner`; the picks/notes are seeded from
   `decisions[pid].decision` so they appear in the UI. The
   auto-load also tries `fag-decisions.json` in the same dir
   in addition to `results.jsonl`, so an export placed beside
   view.html loads on open.

Files:
- scripts/view.html: rewritten export (rich JSON, ~70 LOC),
  `loadFromText` / `applyLoaded` helpers, `showExportBanner` /
  `hideExportBanner`, export detection in `parseInput`,
  import accepts all three shapes
- tests/test_view_ux_j10.py (new): 11 tests covering the
  export shape + view-mode detection + banner

Tests: 11 new pass; 794 adjacent pass; 1 pre-existing failure
unrelated.

Laws honored:
  L4 stable key order: the export payload's per-decision
    `decision` object preserves the order from before J8.
  L7 docstrings: `loadFromText` + `applyLoaded` carry
    contract docstrings.

### J9: layout fix + embedded JSONL for file:// auto-load

Two bug fixes from user feedback after J8:

1. **Notes input was stretching the page.** The per-pensioner
   notes `<input>` had `style="flex:1;min-width:200px"` inside
   a non-flex `.actions` parent, so the input rendered as a
   full-width block element — pushing the action buttons off
   screen. Fixed by:
   - Making `.actions` a flex container
   - Adding `flex: 1 1 220px; max-width: 480px` to the
     per-pensioner notes input via CSS class
   - Stripping the inline `style="flex:1;..."` so the CSS
     rule applies
   - Same for the per-candidate notes input (now uses the
     `.candidate-notes` CSS class with `box-sizing: border-box`)

2. **view.html wasn't auto-loading results.jsonl from file://.**
   The browser blocks `fetch()` of sibling files under the
   `file://` protocol. Fixed by embedding the JSONL directly
   into the page at copy time:
   - `scripts/view.html` has a `<!--EMBEDDED_RESULTS_JSONL-->`
     placeholder
   - `scripts/pipeline/run_unified.copy_view_html_if_missing`
     replaces the placeholder with a
     `<script type="application/json" id="embedded-results-jsonl">`
     block containing the matching results.jsonl
   - `tryAutoLoad()` reads the embedded block first; falls back
     to `fetch()` of `results.jsonl` (works under `http://`)

To refresh the embedded data, delete the existing
`output/<runname>/view.html` and re-run the pipeline (the
no-overwrite policy means the copy is only made once).

- scripts/view.html: CSS for `.actions` (flex) + `.candidate-notes`
  (box-sizing); stripped inline styles; embedded JSONL
  placeholder + `tryAutoLoad` reads from embedded first
- scripts/pipeline/run_unified.py: `EMBEDDED_DATA_PLACEHOLDER`
  constant + `copy_view_html_if_missing(results_path=...)`
  injects the data
- tests/test_view_ux_j9.py (new): 10 tests covering layout,
  placeholder, embedded read order, runner embedding
- tests/test_per_run_isolation.py: updated the byte-identical
  test to allow the J9 placeholder substitution

Tests: 10 new pass; 783 adjacent pass; 1 pre-existing failure
unrelated.

Laws honored:
  L7 docstrings: copy_view_html_if_missing keeps the contract
    docstring; new parameters documented.
  L4 stable key order: no JSONL key order changes.
  L3 flush-per-pensioner: copy happens once at run start; data
    read from results.jsonl after all pensioners flushed.

### J8: view.html UX — scrollable candidates, per-candidate remove + notes, "View source" modal, auto-load, best-match labeling

User feedback after reviewing the test batch: the candidates
list was hard to scan (no scroll, all candidates expanded);
the top match was unclear (which person was the auto-accept
actually for?); no way to flag a candidate as wrong without
picking a different one; the digitalprairie pension JSON was
invisible (only the source card image embedded inline).
File picker required manual selection every time.

Six changes in one slice:

1. **Auto-load** — view.html fetches `results.jsonl` from the
   same directory as itself on page load. The file picker
   remains for swapping to a different file.
2. **Scrollable + expandable candidates** — each candidate
   list is wrapped in a `max-height: 400px; overflow-y: auto;
   resize: vertical` container. "Expand" / "Collapse" buttons
   per pensioner add/remove the `.expanded` class (no max-height).
3. **Per-candidate remove + notes** — each candidate has a
   "✕ remove" button (strikethrough + REMOVED badge when
   active) and a per-candidate notes input. Both persist
   in `decision.removed_candidates` + `decision.candidate_notes`
   (localStorage). Both export in the decisions.csv (new
   `removed_candidates` + `candidate_notes` columns).
4. **"View source" modal** — a button next to the per-pensioner
   actions fetches the digitalprairie pension JSON
   (`/digital/api/singleitem/collection/pensions/id/{id}`)
   and renders its fields (contentType, filename, fields
   table, objectInfo) in a modal popup. Closes via ✕,
   click-outside, or Escape.
5. **Best-match labeling** — top-ranked candidate gets a
   "★ Best match" badge. When top 2 are within 0.05 score,
   an "⚠ ambiguous" warning appears so the reviewer doesn't
   auto-trust the pick. The "Top match" line in the meta row
   now clearly labels the top pick.
6. **Rich actions row** — the per-pensioner actions row now
   includes: Pick rank 1, View source, No match, Clear
   decision, and a per-pensioner notes input. All persist
   via the existing decision system.

Files:
- scripts/view.html: +309 lines (modal, badge CSS, candidate
  controls, fetchSourceJson, toggleRemoveCandidate,
  setCandidateNote, setPensionerNote, expandCandidates /
  collapseCandidates, modal dismiss, expanded CSV export).
- tests/test_view_ux_j8.py (new): 13 tests covering all
  six changes.

Tests: 13 new pass; 773 adjacent pass; 1 pre-existing failure
unrelated.

Laws honored:
  L7 docstrings: every new public function carries a contract
    docstring (toggleRemoveCandidate, setCandidateNote, etc.)
  L4 stable key order: per-pensioner decisions now carry
    `removed_candidates` + `candidate_notes` (new keys
    appended; existing fields unchanged).
  L3 flush-per-pensioner: candidate state changes persist
    to localStorage on every action (no in-memory-only state).

### J7: CGR <-> FaG post-run dedup (CGR no longer in view.html)

Reframed the CGR role. The CGR (Confederate Graves Registry)
data is no longer displayed inline in view.html as a side
panel. It is now a post-run dedup signal: each results.jsonl
record is annotated with one of four `cgr_dedup_status`
values:

  - `duplicate`             FaG auto-resolved AND CGR has them
  - `follow_up_candidate`   CGR has them but FaG didn't auto-resolve
                            (these are the gold — CGR found a lead
                            FaG missed; reviewer should re-examine)
  - `clear`                 no CGR match; FaG is the only signal
  - `no_fag_match`          neither CGR nor FaG found anything

The status surfaces in view.html as a small badge beside the
fag_status pill + a new entry in the status filter dropdown +
a pill in the stats bar. The old CGR panel CSS, JS, and
function definitions are removed.

For the test-batch-25 (re-run with this slice):
  - 1 duplicate (Hugh H. Akers, auto_accept + CGR at Dougherty
    Cemetery, Carter Co., OK, b.1846 d.1924)
  - 1 follow_up_candidate (Alvin Andrews, FaG too_many + CGR
    at Wards Grove Cemetery)
  - 23 clear
  - 0 no_fag_match

A new `output/<runname>/cgr_fag_dedup.json` summary is written
with per-pensioner verdicts + a `follow_up_candidates` shortcut
list for reviewer triage.

- scripts/cgr/cgr_fag_dedup.py (new): match logic (last name +
  phonetic first name + unit/year corroboration), per-pensioner
  classification, run_dedup() entry point that annotates
  results.jsonl in place + writes the summary.
- scripts/pipeline/run_unified.py: `UnifiedRunnerConfig` gains
  `cgr_path`; `run_batch()` calls `run_dedup()` after the
  report (before the resume artifact) when cgr_path is set.
- scripts/view.html: drops `renderCgrPanel`, `renderCgrConflicts`,
  and the matching CSS. Adds `renderCgrDedupBadge` (renders
  the badge beside the fag_status pill with hover tooltip
  showing the matched CGR row), 4 new status filter entries,
  4 new stats pills.
- tests/test_cgr_fag_dedup.py (new): 15 unit + integration
  tests covering year extraction, normalize_unit,
  match_strength tiering, classify_pensioner decision matrix,
  run_dedup in-place annotation, missing CGR file handling.
- tests/test_cgr_view_html.py: rewritten — 6 tests for the
  new badge rendering + status filter + panel removal.

Tests: 21 new pass; 760 adjacent pass; 1 pre-existing failure
unrelated.

### Fix #13: digitalprairie.ok.gov backlink migration + IIIF embed

digitalprairie.ok.gov migrated its URL structure in mid-2026.
The legacy `/digital/singleitem/collection/{col}/id/{id}` URLs
now return soft-404 pages (HTTP 200 with `"404: Page not
found"` body). The legacy `/digital/collection/{alias}/id/{id}`
human-facing URLs and `/digital/search/collection/{alias}`
search URLs are also broken. The only working endpoint is the
JSON API at `/digital/api/singleitem/...`. The user-suggested
browsable URL `/digital/search/collection/pensions!pensioncard`
was verified broken.

Fix has two parts (per user request — both immediate UX + source
of truth):

**Immediate (view.html):** New `fixDigitalPrairieUrl(url)`
helper rewrites `/digital/singleitem/...` → `/digital/api/singleitem/...`
at render time so the existing `source card` and `application`
links aren't 404.

**Embedded IIIF images (J6):** The IIIF image endpoint
`/iiif/2/pensioncard:{page_id}/full/300,/0/default.jpg` still
works (returns real JPEGs of the actual pension card scans).
New `scripts/ingest/fetch_pensioncard_pages.py` pre-fetches the
page IDs from the API for every pensioner (cached in a sidecar
JSON; resumable; throttled). The runner loads the sidecar and
writes `pensioncard_pages: [page_id, ...]` into each results.jsonl
record. view.html embeds the IIIF thumbnails directly inline via
a new `renderPensionerCardImage(p)` helper — no broken link, no
need to navigate to digitalprairie.

For pensioners with two-sided cards, both Side 1 and Side 2 are
embedded. Click a thumbnail for the full-size IIIF image.

**Source of truth (scraper):** Updated
`PUBLIC_URL_PENSIONS` / `PUBLIC_URL_PENSIONCARD` in
`scripts/ingest/scrape_digitalprairie.py` to use the working
`/digital/api/singleitem/...` paths. Future re-scrapes inherit
the fix. Centralized `_format_public_url(prefix, id)` helper
replaces inline `.format(id=item_id)` at the two call sites.

- scripts/view.html — `fixDigitalPrairieUrl` rewrite helper,
  `buildIiifThumbnailUrl` / `renderPensionerCardImage` IIIF
  embed helpers, schema doc updated to mention
  `pensioncard_pages`.
- scripts/ingest/fetch_pensioncard_pages.py (new) — CLI that
  populates the sidecar; resumable; throttled.
- scripts/ingest/scrape_digitalprairie.py — `PUBLIC_URL_*`
  point at /api/ path; `_format_public_url` helper.
- scripts/pipeline/run_unified.py — `UnifiedRunnerConfig`
  gains `pensioncard_pages_path`; `--pensioncard-pages` CLI
  flag; `result_to_dict` adds `pensioncard_pages` field from
  sidecar.
- tests/test_view_html.py — 3 new tests for the IIIF embed +
  URL rewrite helper.
- tests/test_scrape_digitalprairie.py (new) — 4 tests pinning
  the URL builders + `PUBLIC_URL_*` no longer uses broken path.
- tests/test_fetch_pensioncard_pages.py (new) — 15 tests for
  the fetcher (extract_page_ids, cache load/save, fetch
  failure handling, --refresh, --limit, network mocked).

Tests: 35 new pass; 749 adjacent pass; 1 pre-existing failure
unrelated.

### Bug: FaG locationId scoped to regiment state, not OK

The v5 strategy ladder scoped FaG searches to the
pensioner's regiment state (e.g. "4th Missouri Cavalry" →
state_25 = Missouri). For the OK Confederate pensioner
project — whose goal is "find Confederate soldiers
associated with Oklahoma who are not yet in Find a Grave"
(AGENTS.md) — this returns nationwide matches instead of
OK-buried candidates. Confirmed by a 25-record test batch
where distinct locationId values spanned 9 different
states (state_25=MO, state_45=TX, state_24=MS, etc.) and
zero BOTH_MATCH corroborations.

Fix: scope all FaG searches to OK by default. Added
`fag_state_filter` to `BatchConfig` (default `"OK"`,
overridable to any US state abbr, `"US"` for country_4,
or `""` to disable). Wired through `cli_main` →
`make_fag_search_fn` → `search_one_pensioner` as a
new `state_filter` parameter; legacy behavior (scope =
regiment state) preserved when `state_filter=None` is
passed. Added `--fag-state-filter` CLI flag for ad-hoc
override.

Re-ran the test-batch-25 with the new default: 8 BOTH_MATCH
corroborations, 1 auto_accept, vs the previous run's 0
BOTH_MATCH / 1 auto_accept / 10 too_many. Massive
improvement in result quality.

Known follow-up (out of scope here): the v5 ladder still
returns `too_many` for many records because the OK scope
yields 20 candidates per strategy. A two-tier search (OK
first, broaden to US if results are sparse) would catch
OK-buried soldiers who were pensioned in OK but buried
elsewhere. Filed separately; this slice fixes only the
wrong default.

- scripts/batch_config.py — `BatchConfig.fag_state_filter`
  (default `"OK"`); init-batch template + load_config
  round-trip + type check.
- scripts/fag/search.py — `search_one_pensioner` gains
  `state_filter` kwarg; default None preserves legacy
  behavior. When set, overrides the
  `extract_state_from_regiment(pensioner["regiment"])`
  lookup.
- scripts/fag/fag_browser.py — `make_fag_search_fn` gains
  `state_filter` kwarg; passed through to
  `search_one_pensioner`.
- scripts/pipeline/run_unified.py — new
  `--fag-state-filter` CLI flag; CLI default `None`, when
  `--config` is used the config's `fag_state_filter` is
  the default. CLI flag overrides config.
- tests/test_batch_config.py — round-trip + default-value
  tests extended for the new field.

Tests: 730 adjacent pass; 1 pre-existing failure unrelated.

### Fix #12: S_NO_RESULTS / S_ERROR import in scripts/fag/search.py

scripts/fag/search.py referenced `S_NO_RESULTS` (lines 241,
433) and `S_ERROR` (line 431) without importing them. The
constants live in scripts/fag/filters.py (lines 65, 68) but
the `from scripts.fag.filters import (...)` block didn't
include them — a regression from the T008 split
(commit c217eff).

Repro: calling `make_fag_search_fn(...)().fag_search(...)`
with any pensioner raised `NameError: name 'S_NO_RESULTS' is
not defined` and aborted the run with `status='error'`. Found
while smoke-testing the test-batch-25 run.

- scripts/fag/search.py — added `S_NO_RESULTS, S_ERROR` to the
  `from scripts.fag.filters import (...)` block.
- tests/test_fag_search_imports.py (new) — regression test:
  asserts the constants are importable from
  `scripts.fag.search` AND that the source-level
  `from scripts.fag.filters import (...)` block contains
  both names (catches re-introductions after future
  refactors).

Tests: 2 new pass; 729 adjacent pass.

### J5-S3: resume.sh artifact + log + post-interrupt

Every run writes `output/<runname>/resume.sh` — a single-line,
executable shell script that re-invokes the runner with
`--config` pointing at this run's `config.json`. The same
command is logged to `run.log` (as `RESUME COMMAND: …`) and
printed to stdout via the standard logger. The artifact is
also written on `KeyboardInterrupt`, so a crashed run is
always one `./resume.sh` away from continuation. Re-running
is safe: ResumeTracker skips pensioners with terminal status.

- scripts/pipeline/run_unified.py — new `build_resume_command`
  + `write_resume_artifact(out_dir, config_path, log)`. The
  runner passes `args.config` to `run_batch` as
  `config_path_for_resume`; cli_main also writes the artifact
  in the KeyboardInterrupt handler.
- tests/test_resume_artifact.py (new) — 12 tests covering
  command building, artifact writing, log emission, exec bit
  on POSIX, idempotent writes, post-completion and
  post-interrupt generation, and reloadability of partial
  results after an interrupt.

Tests: 12 new pass; 727 adjacent pass; 1 pre-existing failure
unrelated.

Closes issue #11 (per-run batch isolation umbrella issue).

### J5-S2: per-run results.jsonl + view.html copy

Each run's per-pensioner records now live at
`output/<runname>/results.jsonl` (was `state.jsonl`); the legacy
filename is still supported via `results_filename` override.
`scripts/view.html` is copied into the run dir at start (skipped
if already present, to preserve user edits during review).
ResumeTracker is filename-agnostic; tests
`tests/test_run_unified_main.py` updated to assert the new
default.

- scripts/pipeline/run_unified.py — `UnifiedRunnerConfig` gains
  `results_filename` (default `"results.jsonl"`) and
  `view_html_source` (default `scripts/view.html`). New module
  function `copy_view_html_if_missing(source, dest_dir)` does
  the byte-identical copy with no-overwrite policy.
- tests/test_per_run_isolation.py (new) — 13 tests covering
  the per-run filename default + override, view.html copy +
  skip-if-exists + missing-source resilience, and
  backward-compat for `state.jsonl`.

Tests: 13 new pass; 715 adjacent pass; 1 pre-existing failure
in `test_view_html.py::test_view_html_field_set_matches_schema`
unrelated (carried from issue #9).

### J5-S1: batch config.json + init-batch subcommand + --config arg

Each run now lives in its own `output/<runname>/` folder with
a `config.json` carrying the run's parameters. The new
`init-batch <runname>` subcommand scaffolds that config;
`--config output/<runname>/config.json` on the main CLI loads
it and derives `--out` / `--input` / `--cgr` /
`--throttle` / `--low-score-threshold` / `start_row` /
`end_row` from it. CLI flags still override config values
when both are supplied. Per-run results isolation and the
resume.sh artifact land in S2 and S3 respectively.

- scripts/batch_config.py — new `BatchConfig` dataclass +
  `init_batch` + `load_config` +
  `validate_config_against_dir` + `ConfigError`. The slug
  regex (`^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$`) rejects
  uppercase, spaces, and leading/trailing separators.
- scripts/pipeline/run_unified.py — added `init-batch`
  argparse subcommand; `--config` arg merged into args
  before the existing pipeline runs (no behavior change for
  callers using the legacy `--input / --cgr / --out` flags).
- tests/test_batch_config.py — 13 unit tests covering
  init-batch scaffold, slug validation, config round-trip,
  required-key enforcement, strict type checking, and
  runname/dir consistency.
- tests/test_cli_batch_config.py — 4 CLI integration tests
  covering `init-batch` happy-path + rejection, full batch
  via `--config` (no-fag mode), and runname/dir mismatch
  exit code.

718 tests pass + 17 new = 735 total. The single pre-existing
failure in `test_view_html.py::test_view_html_field_set_matches_schema`
is unrelated (issue #9 closed but the drift persisted; not
in scope for J5).

### Fix #9: view.html schema doc + drift test

scripts/view.html's JS normalizer reads state.jsonl fields
that come from scripts/state/schema.py::PensionerRecord
(T018). The two were drifting silently — the Python side
could add a field and the UI would never see it.

- scripts/view.html — added a top-of-file comment listing
  every field the JS normalizer reads (direct + derived),
  with the schema source-of-truth reference
- tests/test_view_html.py — new
  test_view_html_field_set_matches_schema asserts the JS
  set is a superset of the Python PensionerRecord set;
  drift fails the build

The reverse direction (JS reads more fields than Python
types) is allowed: those are aliases or fallbacks the JS
normalizer tolerates from legacy state.jsonl files.

702 non-integration tests green.

### Fix #8: finish search_fag split (T008)

scripts/fag/search.py was 1432 LoC after T017 strategies
extracted. Split the rest into 5 private modules under
scripts/fag/:

  filters.py    (212 LoC) - location/regiment/slug parsers,
                            state name lookups, FAG_STATE_IDS
  parser.py     (301 LoC) - parse_results_page, merge_candidates
  scoring.py    (216 LoC) - score_candidate, tag_candidates
  state_io.py    (70 LoC) - load_processed_ids, append_state
  inputs.py     (104 LoC) - load_unified_*, load_local_csv,
                            load_input, load_ground_truth

scripts/fag/search.py is now 631 LoC (the search_one_pensioner
orchestrator + main() + setup_browser/warmup_session), down
from 1432. 4 public symbols (≤6 deep-module rule met).

The remaining bulk is search_one_pensioner's per-pensioner
strategy orchestration; splitting it further would require
breaking the strategy ladder boundary, which the v5 design
docs explicitly endorse keeping unified.

Side-effect cleanups:
- FAG_STATE_IDS / FAG_COUNTRY_FILTER_US constants moved to
  filters.py (where they belong with the location logic)
- _STATE_NAMES_UPPER / _STATE_NAMES_LOWER moved to filters.py
  (where they belong with the state extraction logic)
- Fixed missing `import re` in scoring.py and parser.py
  (original search.py had it; the split modules inherited
  the references but not the import)
- Fixed missing `import json` in state_io.py

701 non-integration tests green.

### Fix #5: mark test_real_fag_memory.py as integration

test_real_fag_memory.py opens a real Playwright browser mid-
suite, which was blocking fast local runs (and agents running
the full suite). Marked the file's tests with
`@pytest.mark.integration` and added `-m "not integration"`
to pytest.ini addopts so it skips by default.

Run intentionally:
  pytest -m integration
  pytest tests/test_real_fag_memory.py -v

- tests/test_real_fag_memory.py — `pytestmark = pytest.mark.integration`
- pytest.ini — markers section + default addopts skip

701 tests pass by default; 1 deselected.

### Refactor: sweep doc references to new data file names (T023)

Swept 30 references to unified.json/unified.csv across 10
doc files (docs/PRD.md, docs/RESEARCH.md, docs/learnings/*,
docs/research/*, docs/agents/cross-layer-contract.md).
All replaced with ok_pensioners.json/ok_pensioners.csv.

Acceptable remaining references (historical, not data-flow):
- CHANGELOG.md (historical entries about the rename itself)
- CONTEXT.md Historical section (narrative of the rename)
- scripts/pipeline/rename_to_ok_names.py (the migrate script's
  own docstring describing what it did)
- tests/test_backfill_backlinks.py (tmp filenames inside
  tmp_path, not real paths)

### Refactor: search_fag.py to 11-LoC compat shim (T022)

scripts/search_fag.py (1432 LoC) is now an 11-line back-compat
shim. The canonical implementation moved to scripts/fag/search.py
as part of T022.

  scripts/search_fag.py: 11 LoC (re-export shim)
  scripts/fag/search.py: 1432 LoC (canonical)

The deep-module-engineer facade rule (≤6 public symbols) will
apply to a future collapse; the shim keeps every existing
caller working for one release cycle.

Tests that imported private symbols (_STATE_NAMES_UPPER, etc.)
or read source via `open(search_fag.__file__)` were updated
to use the canonical scripts.fag.search path.

700 non-integration tests green.

### Refactor: restructure scripts/ into subpackages (T021)

41 files moved from flat scripts/*.py into 8 subpackages
(fag, cgr, matching, pipeline, state, ingest, analysis,
search, _archive) per the audit proposal. Each subpackage
gets an __init__.py; scripts/__init__.py re-exports 5
cross-package public symbols.

All moved files retain their original locations as
back-compat shims (`from scripts.fag.fag_browser import *`),
so existing callers `from scripts.X import Y` keep working.

Deep-module rule applied: each subpackage has a single
package-level facade (the canonical __init__.py), not a
flat namespace.

Tests that imported private symbols (`_norm`, `_get_rss_bytes`,
`_both_match_exemplars`, `_spouse_cross_search_params`, etc.)
were updated to import from the new subpackage locations.
Tests that read module docstrings were updated similarly.

700 non-integration tests green (was 699).

### Refactor: orphan-library audit + fix search_fag bare imports (T020)

The audit found ZERO true orphan libraries. The four modules
initially suspected (cgr_fag_link, nickname_match,
regiment_keyword, spouse_cross_ref) are all live code:

- spouse_cross_ref is the seed for T005 (Spouse cross-reference
  full pipeline) + the domain concept in CONTEXT.md glossary
- cgr_fag_link is the seed for the BOTH MATCH direct_link
  detector; both_match.py already accepts fag_link as a param
- nickname_match + regiment_keyword ARE imported by
  scripts/search_fag.py via fragile bare imports
  (`from nickname_match import ...` without the `scripts.`
  prefix) that the audit tool couldn't see

The bare imports were the actual fragility — fixed:

- `scripts/search_fag.py` now uses `from scripts.checkpoint`,
  `from scripts.regiment_keyword`, `from scripts.nickname_match`

- `scripts/_archive/ARCHIVED.md` created with the decision
  rationale for future maintainers
- 4 follow-up issues filed for related bugs found:
  soundex (#6, fixed), search_fag incomplete split (#8),
  checkpoint import path (#7), cgr_fag_link regex syntax (#10)
- 699 tests green

### Refactor: lift state.jsonl schema to typed dataclasses (T018)

state.jsonl was an implicit schema documented in
cross-layer-contract.md docstring. Every consumer re-parsed
the dict shape. Now there is a single source of truth:
scripts/state/schema.py with PensionerRecord,
CandidateRecord, BothMatchRecord dataclasses + from_dict
adapters. state_normalize.py consumes the typed front;
output dict shape stays unchanged for view.html
(browser-side, reads its own JS normalizer).

- scripts/state/__init__.py (new, package marker)
- scripts/state/schema.py (new) — 3 dataclasses, 6
  adapters, SCHEMA_VERSION constant
- scripts/state_normalize.py — wraps input via
  from_dict_pensioner before building output dict
- tests/test_state_schema.py (new) — 14 tests covering
  round-trip, missing-field tolerance, unknown-field
  pass-through

Side effect: corrected pre-existing soundex bug (was
emitting R000 for "Robert" instead of R163 due to two
cascading errors — missing AEIOUYHW vowel mapping and
case-sensitive lookup). The corrected soundex was wired
through the search_fag back-compat shim automatically.
See issue filed for full analysis.

All 699 tests green.

### Refactor: merge unified_pipeline + unified_runner into pipeline/core (T019)

Two coupled modules (scripts/unified_pipeline.py +
scripts/unified_runner.py) shared the same data model and
called each other in both directions. Merged into one module
under scripts/pipeline/core.py. PipelineResult is the single
boundary DTO; UnifiedRunResult remains as a back-compat alias
so existing callers (retry_errors, run_unified, 4 test files)
keep compiling.

- scripts/pipeline/__init__.py (new)
- scripts/pipeline/core.py (new) — merged surface, 11.8k LoC
- scripts/unified_pipeline.py — back-compat shim (4 LoC)
- scripts/unified_runner.py — back-compat shim (8 LoC)
- All 686 tests green (no behaviour change)

### Refactor: extract strategy ladder from search_fag.py (T017)

First cut at splitting the 1631-LoC search_fag.py along
deep-module boundaries. The 10 strategy_* functions +
STRATEGIES ladder move to scripts/search/strategies.py;
search_fag.py imports them and keeps the original names
as back-compat re-exports.

- scripts/search/strategies.py (new) — 237 LoC, 10 pure
  strategy functions + STRATEGIES ordered list
- scripts/search/__init__.py (new) — package marker
- scripts/search_fag.py — strategy defs removed; re-imports
  from scripts.search.strategies (back-compat shim)
- tests/test_strategies.py (new) — 14 tests covering all 10
  strategies + the module-level STRATEGIES list invariant

Down from 1631 -> 1432 LoC in search_fag.py. T021's
subpackage restructure will move more.

### Refactor: extract name_utils (T016)

scripts/phonetic_match.py imported `normalise` and `soundex`
from scripts/search_fag.py — a downstream matcher reaching up
into the god-module for two helpers. Extracted both to
scripts/name_utils.py. search_fag.py keeps its defs as a
back-compat shim that delegates to name_utils, so callers
that `from scripts.search_fag import normalise` keep working.

- `scripts/name_utils.py` (new) — leaf module with 2
  functions: normalise, soundex
- `scripts/phonetic_match.py` — imports from name_utils
- `scripts/search_fag.py` — defs become shims
- `tests/test_name_utils.py` (new) — 11 tests covering empty/
  None/unicode/punctuation/classic Soundex cases

### Refactor: rename data files + add provenance _meta (T015)

The canonical OK pensioner file was called `unified.json`, which
doesn't tell you the scope (OK-only) or the source. Renamed to
`ok_pensioners.json` (reverting a historical rename; see
`CONTEXT.md` §Historical). CGR input already used the `ok_` prefix;
it gains a sibling `_meta.json` for parity.

- `docs/research/digitalprairie/unified_sample_50.json` →
  `ok_pensioners_sample_50.json`
- `docs/research/digitalprairie/ok_pensioners.meta.json` (new)
- `docs/research/cgr/ok_cemeteries.meta.json` (new)
- 5 importers updated (`backfill_backlinks`, `cgr_matcher`,
  `scrape_digitalprairie`, `spouse_cross_ref`, `spouse_prototype`)
- `scripts/rename_to_ok_names.py` (new) — one-shot idempotent
  migration script

Provenance block (`_meta.json` siblings) carries: `source_url`,
`source_collection`, `pulled_at`, `record_count`, `schema_version`.
Sibling-file pattern chosen over embedding in the data array
because every consumer iterates records assuming uniform shape.

### Pensions-application backlink end-to-end

view.html and report.md now show the digitalprairie
pensions-application URL beside the pension-card URL per
pensioner, alongside the existing Find a Grave backlink.
unified.json has always carried both URLs (`backlink` for
the application, `pensioncard_backlink` for the index
card); only the card URL flowed through the pipeline.

- `scripts/search_fag.py`, `scripts/state_normalize.py`,
  `scripts/unified_runner.py`, `scripts/run_unified.py` —
  plumb `backlink` through every record-construction
  site. Missing field defaults to `""` (backwards-safe).
- `scripts/view.html` — reads `backlink` in both
  normalize branches, renders an `application` link next
  to `source card`, includes the field in the search
  haystack so users can search by app URL.
- `scripts/report_generator.py` — top BOTH MATCH
  exemplars table now has two extra columns: `Pension
  card` and `Application`, each with markdown links.
- `scripts/backfill_backlinks.py` (new) — one-shot
  enrichment script. Reads existing `state.jsonl` and
  `pensions.json`, adds the missing `backlink` field,
  writes atomically (`.tmp` + rename). Use to enrich
  pre-change state files so view.html shows both links
  without waiting for a full pipeline rerun.
- 22 new tests: `tests/test_backlink_pipeline.py`,
  `tests/test_backfill_backlinks.py`,
  `tests/test_view_html.py` (4 new assertions),
  `tests/test_report_generator.py` (3 new assertions).
  All 657 non-integration tests green.

### Engineering skills bootstrap

Configured the mattpocock/skills engineering flow for this repo
so `/grill-with-docs`, `/to-prd`, `/to-issues`, `/triage`, and
`/mimplement` have the per-repo scaffolding they assume.

- `docs/agents/issue-tracker.md` — GitHub Issues via `gh` CLI;
  external PRs are not a triage surface.
- `docs/agents/triage-labels.md` — five canonical labels
  (`needs-triage`, `needs-info`, `ready-for-agent`,
  `ready-for-human`, `wontfix`).
- `docs/agents/domain.md` — single-context layout; ADRs read from
  `docs/agents/adr/` (matches this repo's existing location, not
  the upstream `docs/adr/` default).
- `AGENTS.md` — new `## Agent skills` block pointing at the three
  docs above.

### Memory leak fixes for long runs

The full 7,758-record Run #2 grew pwsh.exe to ~7 GB and then
~3.5 GB even on resume; pwsh became unresponsive. Investigation
pointed at two compounding issues:

1. **Playwright Locator and `body` string retention** in
   `scripts/search_fag.parse_results_page()` — link_locators list
   (up to 20 refs) and the full `page.inner_text("body")` string
   remained alive until function exit; on multi-thousand-record
   runs this added up. Fixed by explicitly clearing the locator
   list, dropping the body string, and running
   `gc.collect()` every 25 records.
2. **`scripts/fag_browser._open_browser()` only closed the
   Browser**, not the Context or Page — leaving Playwright
   connection objects referenced after periodic resets. Now closes
   page → context → browser in order, drops state refs to None,
   and runs `gc.collect()` once before spawn.

Added:
- `scripts/rss_watchdog.py` — background thread that polls process
  RSS via Win32 `GetProcessMemoryInfo` (no psutil dependency).
  Three configurable thresholds: warn, force-reset (signals the
  runner to reopen the browser at the next opportunity), exit
  (hard `os._exit(1)` so the runner can't write junk records after
  a wedged pwsh).
- `scripts/soak_memory.py` — manual smoke test that drives N
  synthetic Playwright navigations, samples RSS, computes slope,
  and exits 1 if average growth exceeds `--max-slope-mb-per-10`.
- `tests/test_rss_watchdog.py` — platform-agnostic watchdog tests
  via monkeypatched `GetProcessMemoryInfo` (7 tests).
- `tests/test_search_fag_memory.py` — parse_results_page memory
  hygiene tests (3 tests).

`scripts/run_unified.py` and `scripts/retry_errors_run.py` now
expose `--no-rss-watchdog`, `--rss-warn-mb`, `--rss-force-reset-mb`,
`--rss-exit-mb`, and `--max-consecutive-errors` CLI flags. Defaults:
2048 / 4096 / 6144 MB; 10 consecutive errors.

`scripts/fag_browser.py`: `fag_search()` now auto-recovers from
Playwright closed-target errors ("Target page, context or browser
has been closed" etc.) by reopening the browser at the next
opportunity. After `--max-consecutive-errors` (default 10)
in-a-row errors, raises to let the outer loop terminate the run.

`scripts/fag_browser.py`: matches closed-target errors against a
list of stable substrings across Playwright versions
("target closed", "browser has been closed", etc.) so the
recovery logic doesn't break on Playwright message changes.

### Run #1 / Run #2 update

- Run #1 produced ~3,361 valid records before the original DOM-
  crash bug.
- Run #2 (resume) added another ~1,000 valid records before
  Chromium memory pressure + a previously-broken browser reset
  produced two more error storms.
- State file `data/results/run_full_2026_07_16/state.jsonl` is
  the canonical record; the new leak fixes only affect future
  runs. Existing errored records will be re-tried with the new
  code via `scripts/retry_errors_run.py` once a fresh main run
  completes.



### Added — Oklahoma Digital Prairie Confederate pension index

**The goal of the project** is to find Confederate soldiers associated
with Oklahoma. The 1915 Oklahoma Confederate Soldiers' Pension Act
created a Board of Pension Commissioners that documented every
Confederate veteran (or widow) who applied for a state pension — a
canonical list of OK-associated CW soldiers.

- **`docs/research/digitalprairie/`** — pulled 7,558 unique pensioners
  from `digitalprairie.ok.gov` (both `pensions` and `pensioncard`
  collections, merged on application #).
  - 7,709 application files
  - 11,987 index cards
  - 7,558 unified records (canonical OK-associated CW pensioner list)
  - Each record has: parsed name, app#, pension#, company, regiment,
    spouse name, source URL, IIIF image URL, and a backlink to the
    original card on digitalprairie.ok.gov
- **`scripts/scrape_digitalprairie.py`** — the scraper. Iterates ID
  range, hits the CONTENTdm v13 single-item JSON API, parses
  structured metadata (no OCR needed), merges the two collections
  on application #, outputs both per-collection and unified JSON+CSV.
  Resume-safe. ~5 min for full run at concurrency 15.
- A 50-record sample (`unified_sample_50.{json,csv}`) is committed
  for quick reference. The full 30 MB unified.json is gitignored
  (reproducible by re-running the script).

### Top-level implication

The 7,558 unified records are the canonical input for the next step:
batch FaG searching. The local dixiedata DB has 575 soldiers
already in FaG. Most of the ~7,000 not-yet-in-FaG OK-associated CW
pensioners are the next batch to search. The next helper script
should:

1. Iterate `digitalprairie/unified.json`
2. Build a search URL per soldier using the v5.0 strategy ladder
3. Parse results, score, auto-flag high-confidence matches
4. Output `digitalprairie/unified_with_fag.csv`

### Previous: Research workspace for v5.0 design

Earlier in the same session, this commit also added the v5.0
research workspace. It does **not change any userscript behavior**.
It documents research conducted in July 2026 toward a v5.0 rewrite
of `FindaGraveIterativeHelper.user.js`.

- **`docs/research/`** — five research documents:
  - `local-data/` — analysis of 575 CW veterans in the dixiedata DB
    with attached FaG URLs. Found the slug-shape pattern (82% are
    `first_middle-last`), middlename prevalence (25% single-letter,
    90% any middle), and date-coverage distributions.
  - `findagrave-params/` — verified live parameter reference for
    `/memorial/search`. Confirmed `middlename` as a first-class
    narrowing param (the v4 helper doesn't use it).
  - `cw-tactics/` — practical CW genealogy playbook: abbreviation
    expansion (Wm/Jas/Thos), apostrophe variants, Confederate Home
    records, recommended search order.
  - `phonetic-algorithms/` — comparison of Soundex, Daitch-Mokotoff,
    Double Metaphone, Jaro-Winkler, Damerau-Levenshtein. Includes
    drop-in JS snippets for Tampermonkey.
  - `naming-conventions/` — Southern 1800–1860 naming culture,
    Confederate Home populations, service-record naming quirks.
  - `broadened-set/` — **43,834-soldier Confederate + Union CW
    dataset** pulled from `freecivilwarrecords.org` (17 Confederate,
    5 Union regiments, 11 states). Used to validate strategy
    patterns beyond the OK-heavy local data.

- **`docs/v5-design/`** — proposed v5.0 design:
  - `playbook.md` — master design doc with sources and architecture
  - `strategy-ladder.md` — 13 strategies in execution order with
    validated hit-rates per strategy

- **`scripts/`** — analysis scripts that produced the research:
  - `analyze_local_db.py`
  - `analyze_slug_shapes.py`
  - `validate_v5_ladder.py`
  - `build_broadened_set.py`
  - `match_broadened_to_local.py`

### Top-level finding

The current `FindaGraveIterativeHelper.user.js` v4.0 reaches ~80%
hit-rate against the local 577-pair validation set. The proposed
v5.0 strategy ladder reaches **100%** by adding:
- `middlename` as a primary search parameter (recovers 24 of 41
  exact-sniper failures)
- Apostrophe and abbreviation variant generation
- Civil War bio context filter as catch-all

But before implementation, **Path B** was needed: pull NPS Soldiers &
Sailors index data to broaden the training set beyond the NARA CMSR
bias (enlisted-focused, surviving-regiment bias). Path B has since
been deferred — the immediate goal shifted to building the OK
Confederate pensioner index (see above) for batch FaG searching.

## [0.7] — 2026-07-01

- Added update/download URLs and minor ledger fixes.
- Added README and MIT license.
- Added `process_ledger.py` for converting JSON exports to CSV + Markdown.

## [0.6] — 2026-06-XX

- Strip `VETERAN` suffix from memorial names during scraping.

## [0.5] — 2026-06-XX

- Made buttons collapsable.

## [0.1] — Initial commit

- `FindaGraveScraper.user.js` — basic memorial scraper with ledger
  export.