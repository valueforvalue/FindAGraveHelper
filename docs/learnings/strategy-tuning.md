# Strategy Tuning Log

A chronological record of every scoring change and what effect it
had. Use this to understand the **why** behind the current weights.

## v1 — minimal scoring (only name match)

```python
score = 0.4*last + 0.3*first + 0.3*middle
```

- Tested on 5 records from local dixiedata
- All 5 had a top candidate, but only ~60% at rank 1
- Other candidates with same name flooded the list

**Lesson:** name match alone is not enough; CW-era has many
same-name people.

## v2 — added veteran score (+0.4 if is_veteran)

```python
score = 0.35*last + 0.25*first + 0.20*middle + 0.20*veteran
```

- All 5 had the CW-vet candidate at rank 1
- Score ~0.84

**Lesson:** `VETERAN` flag in the result card is a huge signal.

## v3 — added OK_burial boost (initial goal-defining feature)

```python
score = 0.25*last + 0.19*first + 0.13*middle + 0.20*ok_burial + 0.12*veteran + 0.11*death
```

- 4/5 OK-buried pensioners found at rank 1 with score 0.76
- 1/5 missed (Peter Rozell: spelling variant)
- 84% rank-1 hit rate on 50 records from local dixiedata

**Lesson (early):** OK burial looks like the killer signal — the
top candidate for OK pensioners was the OK-buried CW vet.

## v4 — added death-year matching

```python
death_score = 0.4 if exact, 0.3 if ±2y, 0.15 if ±5y
```

- When local `death_year` is known (which it is for 100% of OK
  pensioners via the digitalprairie records), exact match is a
  strong signal
- Especially useful for ruling out same-name people with
  different death years

**Lesson:** year-level features are reliable when the local data
is well-curated.

## v5 — burial-agnostic: "OK-connected, not require OK burial"

**Critical correction from Jeremy (user feedback, July 2026):**

> "We also might consider the search a little more broad and
> include all of those who were pensioners in oklahoma even if
> they were not finally buried in OK. Because they will have
> spent a decent chunk of their lives in OK which is what we're
> after."

**The data confirms this.** From the digitalprairie metadata
description:

> "To qualify for pensions, applicants had to provide proof of
> honorable discharge and of at least one year's residency in
> Oklahoma prior to making application."

So **every** pensioner in this index lived in OK for at least 1
year. But burial state could be anywhere — many veterans were
buried where they died, which may or may not be OK. The project
goal is **OK-connection** (residency, family ties, life history),
not specifically OK burial.

**Implication:** OK burial is a tiebreaker, not a requirement.
A non-OK-buried candidate with matching name+veteran+death is
just as valid as an OK-buried one.

### Changes

| Feature | Before | After | Why |
|---|---|---|---|
| `ok_burial` max | 0.5 | 0.3 | Smaller bonus, not required |
| `death` max | 0.4 | 0.5 | Stronger signal than burial state |
| `veteran` max | 0.4 | 0.8 | CW-era vet flag is the strongest era signal |
| `state` max | 0.2 | 0.1 | Rare to have matching state |
| Name weights | 0.57 total | 0.50 total | Make room for stronger features |
| AUTO_ACCEPT_THRESHOLD | 0.75 (single value) | 0.70 with death, 0.60 without | Match max achievable score |
| AUTO_ACCEPT_GAP | (didn't exist) | 0.10 | Top must beat #2 by this for auto-accept |

**A perfect name+veteran+death match now scores 1.00 (was 0.80).**

A name+veteran-only match (no death year) = 0.64.
A name+death-only match (no veteran flag) = 0.61.
A name-only match = 0.50.

### Results on 50 ground-truth records (after v5)

- **rank-1: 44/50 = 88%** (up from 86% before)
- **auto_accept: 29** (up from 0!)
- **auto_accept precision: 100%** (29/29 correct)
- too_many: 21 (down from 50)

### Results on 5 OK-buried test records (after v5)

- **4/5 auto-accept** (Robert Goad, Andrew Ables, James Myers,
  John Welter) — OK-buried candidates still rank high
- 1/5 missed (Peter Rozell — data quality, spelling variant)

### What this means

The harness now produces **auto-accepts** for high-confidence
matches even when there are many candidates (gap rule). Human
review via `view.html` focuses on the remaining
`too_many` (close matches with no clear winner) and `ambiguous`
records.

The 6 still-missed records are all **data quality** issues —
the expected person isn't in the top 20 candidates at all
because of spelling variants, missing middle names, or wrong
death year.

## Scoring formula (current)

```python
score = (
    0.22 * last_score +      # 1.0 exact, 0.7 partial-prefix, 0.5 phonetic, 0 otherwise
    0.17 * first_score +     # 1.0 exact, 0.6 initial, 0.4 phonetic, 0 otherwise
    0.11 * middle_score +    # 1.0 exact, 0.5 initial, 0.5 (no local middle), 0 otherwise
    0.10 * ok_burial_score + # 0.3 if candidate buried in OK (tiebreaker)
    0.18 * veteran_score +   # 0.8 if candidate has VETERAN/CSA/Civil War flag
    0.22 * death_score       # 0.5 exact, 0.4 ±2y, 0.2 ±5y
)
```

Max possible score: 1.00 (all features firing perfectly).

## Status thresholds

| Status | Trigger | Meaning |
|---|---|---|
| `auto_accept` | score ≥ 0.70 (with death year) / 0.60 (without) AND gap to #2 ≥ 0.10 | Confident match, no review |
| `auto_accept` | 1 candidate with score ≥ threshold | Same as above |
| `ambiguous` | score ≥ threshold but gap < 0.10 | Top is close to #2, human should look |
| `ambiguous` | 1-10 candidates, score below threshold | Only one match but unsure |
| `too_many` | >10 candidates, no dominant top | Long list to skim |
| `no_results` | all strategies 0 | Probably not in FaG |
| `captcha` | Cloudflare blocked | Retry later |
| `error` | exception during search | Retry or skip |
| `skip` | no last name in local | Data quality issue |

## What we'd change for v6

If hit rate plateaus at 88%, options:

1. **Spouse cross-reference** — see `future-work.md`. The
   prototype on 30 records found 18 cross-refs to widow records.
   For widow pensioners specifically, this would push us past 95%.
2. **Phonetic expansion for surnames** — generate Double Metaphone
   variants and search each (could catch "Rozell" → "Rozzell")
3. **Visit each candidate's memorial page** to extract full details
   (rank, bio, parents) — expensive but could push to 95%+
4. **Birth year derivation** from regiment era (most CW soldiers
   were 16-25 when they enlisted; enlistment year is often known)
5. **Cemetery name match** — if local has "buried_in" (the local
   CSV does; unified.json doesn't), match against candidate's
   cemetery. Currently unused because unified has no cemetery data.

The current 88% is good enough for human review on the small
remaining pile. The HTML viewer is the safety net.

## What NOT to change

- **Don't compare regiment state to burial state.** These are
  unrelated — most CW soldiers served in TX/AR/AL but are buried
  in OK. Earlier versions of the harness made this mistake.
- **Don't require OK burial for high confidence.** The user
  feedback was explicit: "they will have spent a decent chunk of
  their lives in OK which is what we're after."
- **Don't add Boolean operators to bio search.** FaG's bio search
  is full-text only; `"Civil War" OR "CSA"` returns 0 results.
  Use the most specific narrowing term.