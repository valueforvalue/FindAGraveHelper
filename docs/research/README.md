# Research Workspace — Find a Grave Helper v5.0

This directory contains the **research artifacts** that drove the
design of the next-generation Civil War Find a Grave search helper.

The work was done in July 2026 by Jeremy Morris (valueforvalue) using
local-data mining, web research, and broadened dataset construction.

## What's here

| Directory | What |
|---|---|
| [`local-data/`](./local-data/) | Analysis of the 1,147 records in `.dixiedata/dixiedata.db` (575 unique soldiers, 572 unique FaG memorials). Shows the slug shapes, name patterns, and date distributions that informed the v5 strategy ladder. |
| [`findagrave-params/`](./findagrave-params/) | Live-verified reference of every `/memorial/search` URL parameter, plus notes on bot friction and pagination limits. |
| [`cw-tactics/`](./cw-tactics/) | Practical Civil War genealogy playbook — name traps, record sources, recommended search order. |
| [`phonetic-algorithms/`](./phonetic-algorithms/) | Comparison of Soundex, Daitch-Mokotoff, Double Metaphone, Jaro-Winkler, Damerau-Levenshtein for matching historical name variants. |
| [`naming-conventions/`](./naming-conventions/) | Southern naming traditions 1800–1860, Confederate Home population data, service-record naming quirks. |
| [`broadened-set/`](./broadened-set/) | The 43,834-soldier Confederate + Union CW dataset pulled from `freecivilwarrecords.org`, with scripts to rebuild it. This is the expanded training set that supersedes the OK-CW-only local data. |

## Top-level research findings (TL;DR)

1. **The FaG slug is the ground truth.** 82% of slugs are
   `first_middle-last`, not `first_last`. Sending only first + last misses
   the middle component entirely. The current helper does not send
   `middlename`. This is the single biggest fix.

2. **49% of all Confederate soldiers have a middle initial**, higher
   than the 25% our local OK-CW training set suggested. The middlename
   strategy is more important than originally thought.

3. **Apostrophe surnames are common in Confederate records** (185
   found across our broadened set, 19 different `O'X` variants).
   Helper should generate `O'Brien`/`OBrien`/`Obrien` variants.

4. **State-from-unit pre-narrows dramatically.** 50.9% of our local
   records match the broadened set on (last + first-initial + state).
   State pre-narrowing reduces result count before fuzzy widening.

5. **Cold-start hit-rate with the proposed v5 strategy ladder is
   ~99.5%** against the local 577-pair validation set, vs ~80% for
   the existing 5-strategy helper.

## How the research was done

### Phase 1: Local data extraction
The user's dixiedata DB contains 575 soldiers with attached Find a Grave
URLs. We extracted these as `(soldier, memorial_id, slug)` triples and
analyzed:

- Slug shape distribution (1-part, 2-part, hyphenated, 3-part)
- First/last/middle name match rates between local records and slug
- Date coverage and birth-year distribution
- Database quality issues (e.g., `last_name='VETERAN'` sentinel)

→ Output: `local-data/local_soldiers_with_fag.csv` + analysis scripts

### Phase 2: Web research (parallel agents)
Four parallel research agents collected:

1. **FaG URL parameter reference** — verified live against findagrave.com
2. **Civil War genealogy tactics** — name traps, records, recommended
   search order, confederate homes
3. **Phonetic algorithms** — Soundex, D-M, Double Metaphone, etc.
4. **Naming conventions** — Southern 1800-1860 culture, CW service
   record quirks, headstone applications

→ Outputs: see `findagrave-params/`, `cw-tactics/`, `phonetic-algorithms/`, `naming-conventions/`

### Phase 3: Validation against local data
The agent-suggested strategy ladder was replayed against the 577
local (soldier, memorial) pairs. Per-strategy first-hit rate was
measured. Result: 100% of pairs reachable by some strategy, 92.9%
by the exact-sniper alone.

→ Output: `local-data/validation_results.md`

### Phase 4: Broadened training set
The local 577 pairs were considered too biased (mostly OK CW vets,
mostly 1920s deaths, mostly men). We pulled 21 CW regiment rosters
from `freecivilwarrecords.org` (17 Confederate, 5 Union) covering
~43,000 soldiers across 11+ states. This broadened set is the new
training set for the helper.

→ Output: `broadened-set/broadened_cw_training.csv` + the 21 source rosters

### Phase 5: Match broadened set against local
Matched broadened soldiers against local records on
`(last_name, first_initial, state_from_unit)`. 50.9% match rate
reveals state distribution biases in our broadened set (TX, MO, SC
cavalry underrepresented). Documents what the broadened set covers
and what it doesn't.

→ Output: `broadened-set/match_results.md`

## Next: Batch FaG search

With the canonical 7,558-OK-pensioner list, the next step is to
build a batch FaG search harness:

1. Iterate `digitalprairie/unified.json`
2. For each pensioner, build a search URL using the v5.0 strategy
   ladder
3. Submit, parse results, score candidates
4. Auto-flag high-confidence matches (≥0.85)
5. Output `digitalprairie/unified_with_fag.csv` showing which
   pensioners are already in FaG vs. which need to be found

The local dixiedata DB has 575 soldiers already in FaG. The
unified set has 7,558. Most of the ~7,000 not-yet-in-FaG soldiers
are the next batch to search.

Path B (NPS Soldiers & Sailors index) is still useful for
broadening the strategy-ladder validation set, but is no longer a
prerequisite for the immediate goal of finding OK-associated CW
soldiers.

## Reproducing the analysis

```bash
# Phase 1 — analyze local DB
python scripts/analyze_local_db.py

# Phase 4 — rebuild broadened set (requires rosters in broadened-set/rosters/)
python scripts/build_broadened_set.py

# Phase 5 — match broadened to local
python scripts/match_broadened_to_local.py

# Phase 6 — pull OK Confederate pension records from Digital Prairie
python scripts/scrape_digitalprairie.py \
    --out-dir docs/research/digitalprairie \
    --min-id 1 --max-id 13000 --no-probe \
    --concurrency 15 --save-every 500
```

## Sources

- [Find a Grave Memorial Search help](https://support.findagrave.com/s/article/Memorial-Search)
- [Searching the bio field using keywords](https://support.findagrave.com/s/article/Searching-the-bio-field-using-keywords)
- [Naming Memorials](https://support.findagrave.com/s/article/Naming-Memorials)
- [freecivilwarrecords.org](https://freecivilwarrecords.org/) — free NARA CMSR + NPS CWSS data
- [Talisman phonetics library](https://yomguithereal.github.io/talisman/phonetics/)
- [Beider & Morse, APGQ 2010](https://stevemorse.org/phonetics/bmpm2.htm)
- [FamilySearch Abbreviations in Genealogy](https://www.familysearch.org/en/wiki/Abbreviations_Found_in_Genealogy_Records)
- [NPS Civil War Soldiers & Sailors System](https://www.nps.gov/civilwar/search-soldiers.htm)
- [NARA Confederate Pensions guide](https://www.archives.gov/research/military/civil-war/confederate-pension-records)
- [FamilySearch Confederate Soldiers' Home Records](https://www.familysearch.org/en/wiki/Confederate_Soldiers_Home_Records)
- [Family Tree Magazine — middle names](https://familytreemagazine.com/names/researching-ancestors-middle-names/)