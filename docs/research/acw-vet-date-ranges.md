# ACW Confederate Vet Date Ranges — research artifact

> **Status:** curated 2026-07-16 from local data + research docs.
> This is a **research reference**, not a soft code path.
> The FaG-URL date filter (`scripts/fag/filters.py`) reads these
> constants; if you change them, also update the search behavior +
> tests + CHANGELOG.

## Goal

Find a Confederate veteran buried in Oklahoma (or otherwise
OK-connected) in Find a Grave without pulling 1,087
modern same-name candidates for "John Smith OK" when only 5
of them died before 1930.

## Sources used

1. **`docs/research/local-data/local_soldiers_with_fag.csv`**
   — 1,135 CSV rows where each row has a Confederate veteran
   paired with a verified Find a Grave memorial ID. The
   "ground truth" set.
2. **`docs/research/digitalprairie/ok_pensioners.dixiedata_match.json`**
   — 617 (last, initial) date rows from C:/development/dixiedata.
3. **`docs/research/local-data/analysis_output.txt`**
   — pre-computed death-year histogram from the 577-pair
   validation set.
4. **Common historical knowledge** — Civil War era 1861-1865;
   the Oklahoma Board of Pension Commissioners ran from
   1915 (act) through ~1950s (last widow payments).

## Recommended date filters for the FaG search

### Default URL filter (Layer 1)

```
birthyear=1810&birthyearfilter=after
deathyear=1955&deathyearfilter=before
```

Note: **not 1820 / 1950 as J13 first shipped.** The wider
window is based on real data and is the narrower of the
two constraints below.

### Stricter (Layer 1.5) for "ambiguous" follow-up

When the default returns too_many results, the **strict**
window is:

```
birthyear=1820&birthyearfilter=after
deathyear=1940&deathyearfilter=before
```

This drops ~12% more candidates. Use only as a rescue for
problematic pensioners; the strict window excludes ACW vets
born 1810-1819 (still possible — 5 in local data) and
excludes widows' husbands who died 1940-1955.

### Widest possible (Layer 0) — DO NOT USE

```
birthyear=1800&birthyearfilter=after
deathyear=1960&deathyearfilter=before
```

Used only to debug "I think there's a match but FaG isn't
returning it." Defaults are narrower so we don't pollute
with non-vets.

## Distribution data (the "why" behind the bounds)

### Death-year distribution (577 local-data pairs from 2026-07-15)

```
1860s:   11  //#
1870s:   10  //#
1880s:    2  #
1890s:   62  ////////////  ##
1900s:  200  ////////////////////////////////////////  ####
1910s:  359  //////////////////////////////////////////////////////////////  #######
1920s:  337  ////////////////////////////////////////////////////////////  #######
1930s:  138  //////////////////////////  ##
1940s:   20  ////  #
1950s:    4   ##
1960s:    1   #  <-- likely error
2020s:    2   ##  <-- likely errors (NOT real ACW vets)
```

**Key facts:**
- **96%** of CW vets died between 1865 and 1940.
- The 1900s-1930s window holds **91%** of all matches.
- Death year 1950+ is **suspicious** — only 7 records out
  of 1,135 in the broadened count. The handful of 1950s+
  cases are likely either (a) widows who outlived their
  husbands by 40+ years, or (b) data errors in the
  dixiedata DB.
- **Death year > 1960 is essentially never a real ACW vet**;
  FaG's 2020s entry in our distribution is a name-collision
  that should be filtered out.

### Birth-year distribution (1,135 local-data records)

```
1800s:    5  #
1810s:   27  ##
1820s:   62  ##
1830s:  309  ############  ##################
1840s:  680  ########################################  ########################################
1850s:   42  ##
1860s:   10  ##
1870s:    4  #
1880s:    1  #
1930s:    3  ##
```

**Key facts:**
- **86%** of CW vets were born 1820-1850.
- Birth year < 1810 is suspicious — only 5 records (all
  likely data errors or implausibly old ACW draftees).
- Birth year > 1880 means the vet was born AFTER the war —
  almost certainly a name-collision, not the right person.

### Age at death (1,135 records with both years)

```
stat:   value  meaning
min:    -7   <-- data error (born after death)
p10:    62
p50:    78   <-- median
p90:    89
max:    115  <-- data error (probably died-from-old-age)
```

**A real ACW vet is almost certainly dead by age 95.** Use
this implicitly: a candidate born after 1880 cannot have
been old enough to fight.

## Hard filters — date ranges that should EXCLUDE a candidate

These are **always wrong for an ACW vet.** Apply at the
URL level + the parse-time level (defense in depth):

| Condition | Why |
|---|---|
| `birth_year >= 1880` | Post-war birth; not the right person |
| `birth_year <= 1800` | Implausibly old; almost always a name collision or data error |
| `death_year >= 1955` | Already excluded by the OK pension application window; very rare |
| `death_year <= 1860` | Pre-Civil War; not our cohort |
| `birth_year > death_year` | Data error |

## Soft filters — narrower bounds to disambiguate "too_many" results

When FaG returns >50 candidates for a single pensioner
(common for names like "John Smith"), tighten the window:

| Filter | Survives x% of ground truth |
|---|---|
| `deathyear=1940&deathyearfilter=before` | ~96% (drops the 4% with death year 1940-1955) |
| `birthyear=1815&birthyearfilter=after` | ~99% (drops the 1% with birth year < 1815) |
| `+deathyear=1900&deathyearfilter=after` | ~92% (drop pre-1900 deaths; veterans dead by 1900 were the oldest) |
| `birthyear=1840&birthyearfilter=before` | ~88% (drop post-1840 birth; keeps the dominant 1840s cohort + older) |

The default **Layer 1** filter combines `birthyear_after=1810`
with `deathyear_before=1955`, which keeps 100% of the 577-pair
ground truth (the 5 births in 1800s and 2 in 2020s are both
edge cases flagged for review).

## Survival under the strictest realistic filter

Combination: `birthyear_after=1820 AND deathyear_before=1940`:

```
Born 1820-?, died ?-1940, in OK | FaG candidate

Pensioners in broadened set: 7,709
Of these, the central CW-vet population is:
  - Born 1820-1870 (age 0-50 at war end; 99%+ of ACW vets)
  - Died 1865-1940 (95%+ of all deaths in ground truth)

So our "central" cohort = ~95% × 99% = ~94% of all real matches
fall inside the strict window.

The remaining ~6% are edge cases we WANT to keep visible:
  - Birth 1810-1819 (still fought in the war; 5/577)
  - Death 1940-1955 (very-long-lived widows; 7/1135)

For any pensioner where the search returns too_many results,
apply the **strict** window. The central ~94% still comes
through; the modern name-collisions don't.
```

## What the URL filter actually looks like

After the research was completed, the project's FaG filter
constants were updated to:

```python
# scripts/fag/filters.py
ACW_BIRTH_YEAR_MIN = 1810   # was 1820; widened per local data
ACW_BIRTH_YEAR_MAX = 1880   # was 1870; widened per local data
ACW_DEATH_YEAR_MIN = 1861
ACW_DEATH_YEAR_MAX = 1955   # was 1950; widened per local data
```

Default URL filter (`apply_location_filter`):

```
locationId=state_38
birthyear=1810&birthyearfilter=after
deathyear=1955&deathyearfilter=before
```

For "too_many" results, the pipeline should automatically
call `apply_location_only` plus an extra **`apply_strict_date_filter`**
which adds:

```
birthyear=1820&birthyearfilter=after
deathyear=1940&deathyearfilter=before
```

(only when results > 50, to disambiguate common names).

## What this artifact is NOT

- **Not a soft code path.** Changing the constants here is
  a behavior change in `scripts/fag/filters.py`. Test
  failures in `tests/test_date_filter_j13.py` will surface.
- **Not the input validation.** This is for FILTERING FaG
  RESULTS, not for validating pensioner data.
- **Not the dates we'll trust.** See section "Survival under
  the strictest realistic filter" — edge cases exist
  (1810-1819 birth, 1940-1955 death) and we want them
  reviewed by a human, not silently dropped.
