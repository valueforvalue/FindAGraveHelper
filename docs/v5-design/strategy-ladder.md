# v5.0 Strategy Ladder

The proposed design for the next-generation helper script. This
document defines the strategy ladder in detail.

## Goal

Given a soldier record (first, middle, last, birth, death, unit, state,
pension_state), produce a Find a Grave URL with maximum hit-rate on
**first try** while minimizing FaG requests (each request risks
CAPTCHA / bot friction).

## Constraints

- Must work in browser (Tampermonkey / Greasemonkey / Violentmonkey)
- 1.5s throttle between FaG page loads (avoid PerimeterX)
- Cold start: no prior FaG URL known for this soldier
- Target: >95% hit-rate on typical CW soldier data

## Strategy ladder (revised, v5.0)

### Tier B (no prior FaG URL — cold start)

Run in order, stop on first hit (1+ result found that scores >0.7).

| # | Name | FaG params | When triggered | Local hit-rate from validation |
|---|---|---|---|---|
| **B1** | Exact sniper | `firstname`, `middlename`, `lastname`, `exactspelling=true`, `birthyearfilter=1` | Always first | 92.9% |
| **B2** | Middlename-initial sniper | `firstname`, `middlename=<initial>`, `lastname`, `exactspelling=true`, `birthyearfilter=1` | When local middle is single letter `H.` etc. | recovers +4.2% |
| **B3** | First-initial exact | `firstname=<initial>`, `middlename`, `lastname`, `exactspelling=true`, `birthyearfilter=1` | When local first is single letter `J.` etc. | recovers +0.3% |
| **B4** | First-initial + fuzzy | `firstname=<initial>*`, `lastname`, `fuzzyNames=true`, `birthyearfilter=5` | Always (after B1-B3) | recovers +1.7% |
| **B5** | Fuzzy last only | `firstname=`, `lastname`, `fuzzyNames=true`, `birthyearfilter=5` | After B4 | recovers +0.7% |
| **B6** | Maiden-name flag | add `maidenname=true` | For women (gender='F' or local has `maiden_name`) | rare |
| **B7** | Nickname flag | add `nickname=true` | When name has known-nickname (Wm, Jas, etc.) | rare in validation |
| **B8** | Apostrophe variants | drop `'`, replace with ` ` | When local last has `'` or `-` | rare in validation |
| **B9** | Abbreviation expansion | expand `Wm`→`William` etc. | When local first in known-abbrev set | rare in validation |

### Tier C (context filters as catch-alls)

| # | Name | FaG params | When |
|---|---|---|---|
| **C1** | Civil War bio context | `isVeteran=true`, `bio="Civil War" OR "CSA" OR "Confederate" OR "GAR" OR "United States Army"` | After all Tier B fail |
| **C2** | Confederate Home context | `bio="Confederate Home" OR "Beauvoir" OR "Higginsville" OR "Ardmore" OR "R.E. Lee Camp" OR "Pettigrew"` | After C1 fails |
| **C3** | Unit-derived state filter | `bio="<unit name>"` (e.g. `bio="19th Alabama"`) | When unit parsed |
| **C4** | Death-year-anchored search | `deathyear=<known>`, `deathyearfilter=10` | When death known |
| **C5** | Widening year filter | `birthyearfilter=25` | Last resort |

## Hit-rate ladder (validated against 577 local pairs, cold start)

| After strategy | Cumulative hit-rate |
|---|---|
| B1 alone | 92.9% |
| + B2 | 97.1% |
| + B3 | 93.2% (note: B3 below B2 in ladder order — included for completeness) |
| + B4 | 98.8% |
| + B5 | 99.5% |
| + C1 | 100.0% |

**Practical shipping plan:** B1, B2, B4, B5, C1 reach 100%. Skip B3, B6-B9 for v5.0 unless validation against the broadened set shows they're needed.

## Strategy execution order

The helper should run them in this exact order, stopping when one
returns results that include a candidate scoring >0.7 against the
local record:

```
1. B1 — exact sniper
   ├── if results include a >0.7 candidate → STOP, prompt user
   └── else → next

2. B2 — middlename-initial sniper (when local middle is single letter)
   ├── if results include a >0.7 candidate → STOP, prompt user
   └── else → next

3. B4 — first-initial + fuzzy (always)
   ├── if results include a >0.7 candidate → STOP, prompt user
   └── else → next

4. B5 — fuzzy last only (always)
   ├── if results include a >0.7 candidate → STOP, prompt user
   └── else → next

5. C1 — Civil War bio context
   ├── if results include a >0.7 candidate → STOP, prompt user
   └── else → declare "not found", log to ledger
```

## Candidate scoring (multi-feature, 0..1)

For each FaG result, compute:

```js
function scoreCandidate(local, candidate) {
  const lastPhonetic = soundexEqual(local.last, candidate.last) ? 1 : 0;
  const firstPhonetic = soundexEqual(local.first, candidate.first) ? 1 : 0;
  const middleMatch = middleMatches(local.middle, candidate.middle); // 0..1
  const birthDelta = birthYearDistance(local.birthYear, candidate.birthYear); // 0..1
  const deathDelta = deathYearDistance(local.deathYear, candidate.deathYear); // 0..1
  const unitMatch = unitInBio(local.unit, candidate.bio) ? 1 : 0;
  const stateMatch = burialStateMatch(local.state, candidate.burial_state) ? 1 : 0;
  const veteranBonus = candidate.isVeteran ? 0.1 : 0;

  return Math.min(1,
    0.20 * firstPhonetic +
    0.25 * lastPhonetic +
    0.15 * middleMatch +
    0.10 * birthDelta +
    0.10 * deathDelta +
    0.10 * stateMatch +
    0.05 * unitMatch +
    0.05 + veteranBonus  // baseline + veteran bonus
  );
}
```

**Thresholds:**

- ≥ 0.85 — auto-select (no user prompt)
- 0.70 – 0.84 — prompt user with candidate list
- < 0.70 — discard; try next strategy

## Pre-narrowing from local data

Before running any strategy, the helper should:

1. **Detect "VETERAN" sentinel** in local last_name → swap with middle_name
2. **Strip title prefixes** (`Capt`, `Chief`, `Mrs.`, `Dr.`, `Rev.`) from
   first_name and remember them
3. **Parse unit** to extract `(Company, Number, State, Type)`
4. **Parse death date** to year
5. **Detect single-letter first/middle** for the appropriate strategy

## Result-count handling

After each strategy query:

| Result count | Action |
|---|---|
| 0 | Try next strategy |
| 1 | Auto-select if score ≥ 0.85; else prompt |
| 2 – 10 | Score all, prompt with ranked list |
| 11 – 100 | Add tightening filter (`birthyearfilter=1`, `isVeteran=true`) and retry; if still >10, prompt with top-10 |
| > 100 | Tighten aggressively, prompt with top-10 with warning |
| 500-page cap (~10K) | Bail; declare "too ambiguous, refine" |

## Modes

The helper ships with **two modes**:

### Mode 1: SNIPE (single soldier)

```
Input:  name fields + birth + death + unit + state
Output: FaG URL (or "not found")
Time:   5-15 seconds
```

### Mode 2: SWEEP (batch)

```
Input:  list of N soldier IDs (from local DB query)
Output: CSV download (soldier_id, fag_url, status)
Time:   ~2 sec/soldier (throttled)
```

**No Mode 5 BACKFILL / AUDIT / ID-caching.** Those are different
tools. The helper's job is find → return URL.

## What this v5 design explicitly is NOT

- ❌ Not an audit tool. (Use a separate script for that.)
- ❌ Not a URL-verifier. (Different tool.)
- ❌ Not an enricher that writes to FaG. (Different tool, ethics.)
- ❌ Not a URL-cache. Each call is cold-start.
- ❌ Not a NARA scraper. (Different project — `FindaGraveScraper.user.js`
  is the existing scraper for already-found memorials.)

## Open questions for v5.0

1. **Bot friction**: 1.5s throttle × 575 soldiers = 14+ min per SWEEP
   run. Is this acceptable?
2. **State pre-narrowing**: should the helper accept a list of
   preferred states from the user, or auto-detect from unit?
3. **Result scoring weights**: should the helper weight unit-match
   higher than date-match (CW genealogists say unit > date)?
4. **Captcha handling**: when PerimeterX triggers, fail gracefully
   or surface the error to the user?
5. **Multi-page results**: how aggressive should "result count >
   100" tighten be?

See `playbook.md` for the full design context and validation.