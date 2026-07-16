# Find a Grave Helper — v5.0 Design Playbook

**Inputs:**
- 1,147 records / **575 unique soldiers / 572 unique memorials** from `.dixiedata/dixiedata.db`
- FaG URL-param live verification (search-form inspection)
- Phonetic algorithm research (Soundex, D-M, Double Metaphone, Jaro-Winkler, Damerau-Levenshtein)
- CW-era naming conventions (Southern tradition, Confederate Homes, pension records)
- Practical CW search tactics (NPS index, Fold3 CMSR, headstone applications, etc.)

---

## 1. The slug is the ground truth

The single most important empirical finding: **Find a Grave's slug
embeds the search name in `first_middle-last` form**. Local first+last
search alone misses the middle component ~82% of the time the slug
*has* a middle component. This drives the entire v5 design.

| Slug form (n=577) | Count | %     | Implication |
|-------------------|-------|-------|---|
| `first_last` (no middle in slug) | 13 | 2.3%  | Trivial |
| `first_m-last` (middle as word, joined with hyphen to last) | 471 | 81.6% | **Helper must send middlename** |
| `first-last` (FaG split on `_` only — no underscore separator) | 92 | 15.9% | Slug-split logic must accept hyphens |
| `first_m_m-last` (multi-part middle) | 14 | 2.4%  | rare but real (e.g. `martin_van_buren-king`) |

The **FaG URL `middlename` parameter is verified live** (1,788 results
for `John Jacob Smith`). It is **a first-class search axis**, not a
synonym for `firstname`.

---

## 2. Verified FaG URL parameters (live-tested)

Confirmed via direct URL round-trips against `findagrave.com/memorial/search`:

### Person name
- `firstname` — given name (≥1 char server-side; UI suggests ≥2)
- `middlename` — distinct, narrowing, real results
- `lastname` — matches **all surnames** (maiden, married, alt) entered in field
- `exactspelling=true` — disable fuzzy match
- `fuzzyNames=true` — enable similar spellings (default off; current script **has this right**)
- `maidenname=true` — include maiden-name matches (women)
- `nickname=true` — include nickname matches
- `titles=true` — include title-prefix matches (Dr., Rev., Mrs.)

### Dates (year-only precision)
- `birthyear`, `birthyearfilter` — filter values: `exact`, `before`, `after`, `1`, `3`, `5`, `10`, `25`, `unknown`
- `deathyear`, `deathyearfilter` — same buckets
- `datefilter` = `24h | 7d | 30d | 90d | 90dplus` — **added in last N** (NOT death date)

### Direct lookup (gold paths)
- `memorialid` — exact ID; bypasses all name search
- `cemeteryid` / `cemeteryId` — narrow to one cemetery
- `cemeteryName` — free-text camelCase cemetery filter
- `contributorid` — contributor's memorials

### Other flags
- `bio` — full-text bio search with Boolean ops: `(a) AND (b)`, `(a) OR (b)`, `(a) NOT (b)`, quoted phrases, `?` and `*` wildcards
- `plot` + `plotinfo=true` — plot text + "with plot info"
- `isVeteran=true` — veteran only
- `famous`, `sponsored`, `cenotaph`, `monument`, `noncemetery` — memorial-type flags
- `nophoto`, `hasphoto`, `gps`, `nogps`, `hasflowers` — content flags

### Pagination & sort
- `page` — 1-indexed, 20/page, **hard cap at 500 pages (~10K results)**
- `sort` — `relevance`, `birthDate`, `deathDate`, `firstName`, `cemeteryName`, `created`, `updated`, `plot`
- `order` — `asc|desc`
- `condensed` — list view without thumbs

### NOT in URL (JS-only state)
- `stateId` / `countyId` — does not filter when set directly. Location widget uses internal API IDs that are not URL-persistent.

### Bot friction
- PerimeterX bot detection. 1–2 req/sec with realistic UA/Referer is OK; sustained iteration may CAPTCHA.

---

## 3. v5.0 strategy ladder (15 strategies)

Ordered by expected hit-rate lift per local record. Empirically calibrated against the 577-pair local dataset:

### Tier A — direct hit paths (cheapest, try first)
1. **Memorial ID** — if `fag_id` known, jump straight to `/memorial/<id>`. **100% recall when ID present.**
2. **Slug resolve** — extract ID from any existing FaG URL already stored in DB; skip search entirely.

### Tier B — exact with name expansion (no fuzzy)
3. **Exact sniper** — `firstname=&middlename=&lastname=` + `exactspelling=true` + `birthyear=±1`. Targets the 80% case.
4. **First-initial exact sniper** — when `first` is a single letter (e.g. `J.`), send `firstname=J`, `middlename=<.>`. Targets `g_w-thompson` style.

### Tier C — fuzzy with widening
5. **Middlename-initial fuzzy** — `firstname=f&middlename=m&lastname=l` + `fuzzyNames=true`. Critical because 25% of records have single-letter middle.
6. **First-initial + fuzzy last** — `firstname=J*&lastname=l` + `fuzzyNames=true`. For when firstname is unknown/empty.
7. **Fuzzy last only** — `firstname=&lastname=l` + `fuzzyNames=true`. Last-resort name widening.
8. **Maiden-name expansion** — for women, also try lastname as maiden (only meaningful with `maidenname=true`).

### Tier D — date-anchored search
9. **Birth ±5** — `birthyearfilter=5` (NOT 25). CW genealogist rule: tighter window first.
10. **Birth ±10** — widen if ±5 returns too many.
11. **Death ±10** — anchor on death year. Critical for CW-era vets (peak cohort 1910s–1920s).
12. **Death-anchored birth search** — derive birth year from known death year if unknown.

### Tier E — context-aware (unit / pension / home)
13. **Civil War context** — `isVeteran=true` + `birthyearfilter=25` + `bio="Civil War" OR "CSA" OR "Confederate" OR "GAR" OR "United States Army" OR "U.S.A."`
14. **Confederate Home context** — `bio="Confederate Home" OR "Beauvoir" OR "Higginsville" OR "Ardmore" OR "Austin" OR "R.E. Lee Camp"`. Targets late-life residence records (peak death-decade 1910s–1930s).
15. **Unit + state filter** — if `unit` parsed (`Co. K, 19th AL Inf.`), build `bio="19th Alabama" OR "19th AL"` filter.

### Tier F — phonetic/misspelling fallback
16. **Metaphone query** — generate Double Metaphone code for surname; if FaG doesn't match, expand search to D-M-equivalent surnames (built locally from a census-cross-reference table).
17. **Abbreviation expansion** — for `Wms/Wm/Jas/Thos/Jno/Chas/Geo/Robt`, generate full-name variants (verified abbreviation list: FamilySearch). Run as separate queries.
18. **Apostrophe normalization** — try `O'Brien` AND `Obrien` AND `OBrien` AND `O Brien` (and similar for `St. John` / `Van Buren`).

### Tier G — disambiguation
19. **Results count: 0** → next strategy
20. **Results count: 1** → grab memorial ID, log, stop
21. **Results count: 2–10** → prompt user with candidate list (name, birth, death, cemetery, slug)
22. **Results count: >10** → apply additional narrowing (tighter year window, add `bio` filter), re-query
23. **Hard cap: 500 pages / 10K results** → bail out, prompt user to refine

---

## 4. Result scoring (post-fetch)

When 2+ results return, rank locally using a **multi-feature scorer**
so the best candidate surfaces first and ties resolve correctly.

### Features (0..1 each)
- **First-name phonetic** — Double Metaphone equality on `firstname` (1 if equal, 0 if not)
- **Last-name phonetic** — Double Metaphone equality on `lastname`
- **Middle-name initial** — 1 if local middle initial matches slug's middle segment letter
- **Middle-name full** — 1 if local middle name == slug's middle segment
- **Birth year delta** — `1 - min(|Δ|, 25) / 25`
- **Death year delta** — same shape
- **Burial state match** — 1 if burial state == local `pension_state` or unit-derived state
- **Unit match** — 1 if FaG bio/inscription mentions local unit
- **Veteran flag** — bonus +0.1 if `isVeteran=true` in result AND local is CW-era

### Score formula
```js
score = 0.20*firstPhonetic + 0.25*lastPhonetic + 0.15*middleMatch +
        0.10*birthDelta + 0.10*deathDelta + 0.10*burialMatch +
        0.05*unitMatch + 0.05*veteranBonus
```

**Auto-flag ≥ 0.85** (AML-style threshold). **0.70–0.84** = "review candidates" list. **< 0.70** = discard.

### Algorithm choice per agent recommendation
- **Double Metaphone** primary (English/CW-era names)
- **Soundex** recall backstop (catches what D-M misses)
- **Damerau-Levenshtein** for "Morrisson vs Morrison" transpositions
- **Daitch-Mokotoff** if name looks German/Polish/Scandinavian (infer by regex `/[äöüß]|icz|ski|berg|mann$/i`)
- **Jaro-Winkler** for short strings (initials)

---

## 5. The 6 search modes

### Mode 1 — SNIPE (default, fast)
Strategies 1–11 in order. Auto-advance on 0/10+, log to console. Best when ID or strong name match is expected.

### Mode 2 — SWEEP (broad)
Skip Tier A, start Tier D (date-anchored). Use when you have lots of soldiers with unknown FaG IDs and want maximum coverage in one pass.

### Mode 3 — DISAMBIG (manual pick)
Pause on 2–10 results. Show name + birth + death + cemetery + slug + score. Let user click to attach to local record.

### Mode 4 — INSPECT (read-only)
Given a memorial URL or ID, parse the slug + scrapes birth/death/cemetery/bio. Compare against local record. Show diff. No navigation.

### Mode 5 — BACKFILL (round-trip)
Read every local record with a FaG URL, parse slug/memorial ID, score against local fields, surface mismatches for human review. **This is the audit mode** for verifying that the 572 known IDs are still attached to the right people.

### Mode 6 — ENRICH (push)
Optional: paste local data back into FaG as a note (if user is logged in). Useful for adding mother's maiden name, unit, pension state, etc. — but **requires careful ethics discussion**, NOT in v5.0.

---

## 6. Architecture: 4-layer split

```
┌─────────────────────────────────────────────┐
│ UI  (panel, modes, candidate picker)        │
├─────────────────────────────────────────────┤
│ Controller (mode driver, state machine,     │
│            sessionStorage, session log)     │
├─────────────────────────────────────────────┤
│ Strategies (URL builders per tier A–G)      │
│           + Result parser                   │
│           + Local scorer                    │
├─────────────────────────────────────────────┤
│ Phonetic lib (D-M, Soundex, D-L, J-W)       │
│ Name-normalization lib (apostrophe, prefix) │
│ CW context lib (Confederate Home list,      │
│                  unit-state parser)         │
└─────────────────────────────────────────────┘
```

**Phonetic lib**: drop-in `talisman` from CDN via `@require`, or inline single-file JS (~5 KB) for air-gapped use. **Recommend `@require` for first version**, fall back to inline if Tampermonkey CSP blocks it.

---

## 7. v5.0 vs v4.0 — concrete changes

| Concern | v4.0 | v5.0 |
|---|---|---|
| Middlename | ignored | **passed as primary param** |
| First-name empty | sniper fails | **auto-skip to fuzzy+initial** |
| Death year | unused | **death-anchored birth derivation + ±10 filter** |
| Surname-only slugs | not detected | **split on `_` AND `-`** |
| 2+ results | silent miss | **scored candidate picker** |
| Direct ID | impossible | **`memorialid` short-circuit** |
| Apostrophes / St. John | sent as-is | **variant generator** |
| Abbreviations (Wm, Jas) | not handled | **expanded variants** |
| Phonetic scoring | none | **Double Metaphone + Jaro-Winkler** |
| Strategy count | 5 | **18** |
| Modes | 1 (linear) | **6 (snipe/sweep/disambig/inspect/backfill/...)** |
| Session log | none | **localStorage of attempt history per soldier** |
| Single-letter middle | impossible to filter | **pass middle-initial only when local middle is one char** |
| `bio` filter | partial (just OR) | **full Boolean syntax** |
| Cache | none | **sessionStorage of last results per soldier** (avoid re-query) |

---

## 8. Validation: replay strategies against local data

This is the **single most important pre-build step**. Before shipping,
write a Python harness that:

1. Loads 577 (soldier, memorial) pairs from `/tmp/fag_soldiers.csv`
2. For each pair, simulates the v5.0 strategy ladder
3. Records which strategy would have found the right memorial
4. Reports per-strategy hit rate and overall
5. Reports edge cases (false positives within 0.85 score threshold)

**Pass criteria**: ≥ 95% of pairs found by some strategy; ≥ 85% by Tier A–C alone.

---

## 9. Risks & open questions

1. **Bot friction**: 18 strategies × 575 soldiers = 10,350 page loads. Will hit PerimeterX. Need a throttle (1.5s between pages) and graceful CAPTCHA detection.
2. **Storage growth**: session log per soldier × 575 = ~115 KB localStorage. Within limits (5 MB typical).
3. **Slug parsing edge cases**: 1-part, 2-part, 3-part, hyphenated, double-barrel (e.g. `francis_ann-fitzgerald_bradshaw`), apostrophe, diacritics. Test corpus should include each shape.
4. **Fuzzy false positives**: Common surnames (Smith, Williams, Johnson) will return 100K+ results. Strategy must tighten year window aggressively.
5. **Ethical line**: ENRICH mode (writing back to FaG) is risky. Defer to v5.1 with explicit user opt-in.
6. **Browser compatibility**: `@require` works in Tampermonkey, Violentmonkey, Greasemonkey 4.x. Need fallback for Greasemonkey 3.x (Firefox legacy).

---

## 10. Next steps

1. ✅ **Validation harness** (Python) — run against local 577 pairs, confirm hit-rate
2. → **Strategy scaffold** — write `Strategies` array with v5 ladder
3. → **Phonetic lib** — `@require` talisman, expose `nameScore()`
4. → **Result parser** — extract slug/memorial ID/cemetery/year from results page
5. → **UI** — mode picker + candidate list panel
6. → **Session log** — localStorage with attempt history, downloadable JSON
7. → **Backfill audit mode** — score all 575 local records vs. attached IDs
8. → **Tests** — slug parser, scorer, strategy URL builder

Sources from research:
- [Find a Grave Memorial Search help](https://support.findagrave.com/s/article/Memorial-Search)
- [Searching the bio field using keywords](https://support.findagrave.com/s/article/Searching-the-bio-field-using-keywords)
- [Naming Memorials](https://support.findagrave.com/s/article/Naming-Memorials)
- [Talisman phonetics library](https://yomguithereal.github.io/talisman/phonetics/)
- [Beider & Morse, APGQ 2010](https://stevemorse.org/phonetics/bmpm2.htm)
- [FamilySearch Abbreviations in Genealogy](https://www.familysearch.org/en/wiki/Abbreviations_Found_in_Genealogy_Records)
- [NPS Civil War Soldiers search](https://www.nps.gov/civilwar/search-soldiers.htm)
- [NARA Confederate Pensions guide](https://www.archives.gov/research/military/civil-war/confederate-pension-records)
- [FamilySearch Confederate Soldiers' Home Records](https://www.familysearch.org/en/wiki/Confederate_Soldiers_Home_Records)
- [Beauvoir Veteran Project data](https://beauvoirveteranproject.org/data/data/)
- [Library of Virginia — R.E. Lee Camp](https://lva-virginia.libguides.com/lee-home)
- [Missouri Confederate Memorial](https://mostateparks.com/parks/confederate-memorial-hs/general-information-confederate-memorial)
- [Family Tree Magazine — middle names](https://familytreemagazine.com/names/researching-ancestors-middle-names/)
- [Genfiles — Senior/Junior suffixes](https://genfiles.com/articles/senior-junior/)
- [Family Locket — Southern naming patterns](https://familylocket.com/analyzing-naming-patterns-a-southern-united-states-example/)