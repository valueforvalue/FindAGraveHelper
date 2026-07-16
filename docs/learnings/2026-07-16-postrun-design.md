# Post-Run Phases — Design (2026-07-16)

After Run #2 completes (resumed from pid 4978, ~2,732 records
remaining) and `retry_errors_run.py` repairs the 796 transient
errors, we have a fully-populated `state.jsonl` covering all
~7,758 OK Confederate pensioners. The next phases are post-run
analyses that turn that data into findings we trust.

This document captures the design of those phases. Phase 2
(CGR-side dedup) is implemented and tested; Phase 3
(leftover-investigation) and Phase 4 (view.html surfacing) are
designed and awaiting build. **Nothing in this document replaces
the per-pensioner FaG search** — that policy is locked in
`scripts/unified_pipeline.py` module docstring.

## Phase 2: CGR-side dedup — IMPLEMENTED

**Goal**: collapse duplicate Confederate Graves Registry records
into canonical persons, with full provenance preserved.

**Input**:
- `docs/research/cgr/ok_vets_enriched.jsonl` (2,593 enriched CGR vets).
- `data/results/run_full_2026_07_16/state.jsonl` (post-run FaG output,
  ~7,709 lines).
- `docs/research/digitalprairie/ok_pensioners.json` (input pensioner
  list, 7,758 records).

**Output**: `data/results/run_full_2026_07_16/cgr_dedup.json`

**Output schema** (an excerpt):

```json
{
  "version": 1,
  "created_at": "<iso8601 UTC>",
  "thresholds": {
    "jaro_winkler_first": 0.90,
    "year_delta": 5
  },
  "persons": {
    "person_108936": {
      "member_cgr_ids": [108936],
      "linked_pensioner_ids": [3, 5, 11, 930, 1841, 3732, 3735, 3736],
      "merged_metadata": {
        "first_name": "Hugh",
        "last_name": "Adams",
        "birth_year": "",
        "death_year": "",
        "cemetery_ids": [14378],
        "spouse": "",
        "regiment": "CSA",
        "company": "",
        "rank": "Pvt",
        "source_count": 1
      }
    },
    "person_110879": {
      "member_cgr_ids": [110879, 139653],
      "linked_pensioner_ids": [928],
      "merged_metadata": {
        "first_name": "Virgil",
        "middle_name": "Balentine",
        "last_name": "Adair",
        "birth_year": "1842",
        "death_year": "1910",
        "cemetery_ids": [14845, 17918],
        "spouse": "Talitha Jane (Bates)",
        "regiment": "39 GA",
        "company": "A",
        "rank": "Pvt",
        "source_count": 2
      }
    }
  },
  "cgr_id_to_person_id": { ... },
  "pensioner_id_to_person_id": { ... },
  "stats": {
    "input_cgr_records": 2593,
    "input_pensioners": 7709,
    "output_persons": 5300,
    "merged_pairs": 186
  }
}
```

**Dedup predicate** (strict, locked 2026-07-16):

Two CGR records `a` and `b` are considered the same person iff:

1. **Last-name match**: `norm(a.last_name) == norm(b.last_name)`
   (lowercase, accents stripped, punctuation stripped).
2. **First-name similarity**: `jaro_winkler(norm(a.first_name),
   norm(b.first_name)) >= 0.90`.
3. **Tiebreaker** (at least one must hold): birth year within 5y,
   death year within 5y, same cemetery id, same unit (normalized),
   or same rank.

If any of (1), (2), (3) fails, the records do NOT merge.
False-negatives are tolerated; false-positives are not (we do
not accidentally merge two distinct veterans).

**Provenance**: every merged cluster records BOTH:

- `member_cgr_ids`: source CGR records that rolled into this person.
- `linked_pensioner_ids`: pensioners whose CGR blocking index
  returned any of the member records.

This means: a question like "is pensioner #5 the same as pensioner
#11?" reduces to "do they map to the same `person_id` in the
dedup file?". The dual-source map makes cross-source traceability
trivial.

**Singletons**:

- A pensioner that linked to no CGR record gets its own
  person_id (`pensioner_<id>`).
- A CGR record that no pensioner linked to still gets a real
  person_id derived from its member-cgr-id range.
- These are intentionally separate — they reflect the data we have,
  not synthetic clustering.

**Why Jaro-Winkler, not Levenshtein**:

Jaro-Winkler gives a bonus for common prefixes. For names with
typos ("Jones"/"Jomes") or phonetic proximity ("Smith"/"Smyth")
this gives more useful scores than raw edit distance. The
stand-alone implementation in `scripts/cgr_dedup.py` avoids a
hard dependency on `jellyfish` or `rapidfuzz`.

**Phase 2 implementation**: `scripts/cgr_dedup.py`
(`build_dedup()` + CLI). 26 unit tests in
`tests/test_cgr_dedup.py` covering normalization,
Jaro-Winkler math, the same-person predicate edge cases
(different last-name, missing first-name, no tiebreaker),
union-find transitive clustering, dual-source map, and the
output schema.

## Phase 3: Leftover-investigation — DESIGN ONLY

**Goal**: turn every "low-confidence" record into either a
"conclusive find" or a "conclusive non-find". Strong certainty
one way or the other.

**Trigger set** (from the policy discussion 2026-07-16):

Records matching ALL of:

- `fag_status in {auto_accept, ambiguous, too_many, no_results}`, OR
- `best_score < 0.85` (no confident match on the first pass)

In practice: the second condition subsumes most of the first;
we examine rows where the first pass wasn't conclusive.

**Secondary strategy ladder** (4 strategies; apply until one of
{conclusive find, exhausted} holds):

1. **Spouse cross-search**: if local record has `spouse_name`
   AND the pensioner is a widow applicant, search FaG for the
   widow explicitly, and look for memorial pages with spouse
   links back to the soldier. Approximately 49% of pensioners
   have `spouse_name` (per `docs/learnings/future-work.md` § 1).

2. **Birth-state narrowing**: if local record has `birth_state`,
   narrow the FaG search by state=birth_state. Most pensioners
   lived/died in OK but some were born elsewhere and buried far
   from OK after the war.

3. **Nickname + initial-swap**: try phonetic equivalents of the
   first name. Examples:
   - `Wm` ↔ `William`
   - `Thos` ↔ `Thomas`
   - `Jno` ↔ `John`
   - `Benj` ↔ `Benjamin`
   Implementation: a small dictionary + Jaro-Winkler fallback
   on the first-name field.

4. **Regiment-bio + death-year**: combine the regiment-bio
   strategy with a death-year filter, narrowing Confederate
   searches to the right decade.

**Hard-target termination**:

For each leftover record, run strategies one at a time. Stop
when:

- (a) a top candidate scores `> 0.85` with strong name match
  AND the candidate's burial data is consistent (state, dates).
  Mark: `found_conclusive=True`. Skip remaining strategies.
- (b) all 4 strategies exhausted. Mark:
  `no_fag_memorial=True`.

**Output**: `data/results/run_full_2026_07_16/leftover_investigation.jsonl`,
one row per examined pensioner with the final disposition and
any newly-discovered candidate info. In-place updates to
`state.jsonl` flag `found_conclusive`/`no_fag_memorial` for
review surface.

**NOT a search gate**: per the policy, follow-up searches are
explicitly endorsed for low-confidence rows. See the
always-run-FaG policy clause added to
`scripts/unified_pipeline.py` on 2026-07-16.

**Why these 4 strategies (and not more)**: this is the
minimum set that exercises the additional metadata (spouse,
birth state, nicknames, death year) we have access to but the
first pass didn't fully use. Adding more strategies (e.g.
phonetic surname expansion, NPS cross-reference) is left for
later phases.

## Phase 4: view.html surfacing — DESIGN ONLY

**Goal**: surface the dedup + investigation results in the
human-review interface (`scripts/view.html`).

**Badges to add**:

| Badge | Meaning | Color |
|---|---|---|
| `CGR-strong` | At least one CGR record linked (post-dedup, this is the union of person_id's members). | blue |
| `CGR-merged` | Multiple CGR records collapsed into this person (via dedup). | purple |
| `Conclusive found` | Phase 3 found a > 0.85 match. | green |
| `No FaG memorial` | Phase 3 exhausted all strategies without finding one. | gray |
| `BOTH MATCH (direct)` | Existing — FaG had a direct backlink to CGR. | green |
| `BOTH MATCH (corroborated)` | Existing — CGR row matches a FaG candidate by data. | teal |

**Filter pills** on top of view.html:

- All
- Found (any positive badge)
- Not found (no_fag_memorial badge)
- CGR-strong (CGR-strong or CGR-merged)

**Implementation**: extend the existing `view.html` data
extractor (`scripts/view_unified.py`, etc.) to load
`cgr_dedup.json` and `leftover_investigation.jsonl` alongside
`state.jsonl`.

## Cross-cutting: policy alignment

The always-run-FaG policy (locked 2026-07-16 in
`scripts/unified_pipeline.py` module docstring) prohibits:

- Skipping the FaG search based on CGR strength.
- Treating CGR data as a pre-search gate.

The policy explicitly endorses:

- Additional FaG strategies on low-confidence rows (Phase 3).
- CGR-side dedup as post-run analysis (Phase 2).
- view.html surfacing of cross-source maps (Phase 4).

The policy is enforced by four test guards in
`tests/test_unified_runner.py::TestAlwaysRunFaGPolicy`. Any
future commit that re-introduces a skip-fast-path or removes
the docstring fails the suite.

## Files

| Path | Phase | Status |
|---|---|---|
| `scripts/cgr_dedup.py` | 2 | implemented |
| `tests/test_cgr_dedup.py` | 2 | 26 tests |
| `scripts/cgr_dedup_run.py` (TODO) | 2 | CLI helper |
| `docs/learnings/2026-07-16-postrun-design.md` | all | this document |
| `scripts/leftover_investigation.py` (TODO) | 3 | designed |
| `tests/test_leftover_investigation.py` (TODO) | 3 | designed |
| `view.html` | 4 | badges + filters designed |
| `scripts/view_postrun.py` (TODO) | 4 | badge data loader |
