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

## v2 — added veteran score (+0.5 if is_veteran)

```python
score = 0.35*last + 0.25*first + 0.20*middle + 0.20*veteran
```

- All 5 had the CW-vet candidate at rank 1
- Score ~0.84

**Lesson:** `VETERAN` flag in the result card is a huge signal.

## v3 — added OK_burial boost (THE killer feature)

```python
score = 0.25*last + 0.19*first + 0.13*middle + 0.20*ok_burial + 0.12*veteran + 0.11*death
```

- 4/5 OK-buried pensioners found at rank 1 with score 0.76
- 1/5 missed (Peter Rozell: spelling variant)
- 84% rank-1 hit rate on 50 records from local dixiedata

**Lesson:** OK burial is the **goal-defining** feature. We are
specifically searching for OK-buried CW veterans; OK-burial bonus
correctly surfaces them.

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

## Scoring formula (current)

```python
score = (
    0.25 * last_score +     # 1.0 exact, 0.7 partial-prefix, 0.5 phonetic, 0 otherwise
    0.19 * first_score +    # 1.0 exact, 0.6 initial, 0.4 phonetic, 0 otherwise
    0.13 * middle_score +   # 1.0 exact, 0.5 initial, 0.5 (no local middle), 0 otherwise
    0.20 * ok_burial_score + # 0.5 if candidate buried in OK
    0.12 * veteran_score +  # 0.4 if candidate has VETERAN/CSA/Civil War flag
    0.11 * death_score      # 0.4 exact, 0.3 ±2y, 0.15 ±5y
)
```

Max possible score: 1.00 (all features fire perfectly).

## Status thresholds

| Status | Trigger | Meaning |
|---|---|---|
| `auto_accept` | score ≥ 0.75 AND 1 candidate | Confident match, no review |
| `ambiguous` | score ≥ 0.75 AND 2-10 candidates | Need to verify but trust top |
| `ambiguous` | 2-10 candidates | Manual review |
| `ambiguous` | 1 candidate but score < 0.75 | Only one match but unsure |
| `too_many` | >10 candidates | Long list to skim |
| `no_results` | all strategies 0 | Probably not in FaG |
| `captcha` | Cloudflare blocked | Retry later |
| `error` | exception during search | Retry or skip |
| `skip` | no last name in local | Data quality issue |

## What we'd change for v6

If hit rate plateaus at 84%, options:

1. **Birth year + birth place** — would help if local data has it
   (digitalprairie doesn't currently; could derive from regiment era)
2. **Spouse cross-reference** — see `future-work.md`
3. **Phonetic expansion for surnames** — generate Double Metaphone
   variants and search each
4. **Cemetery name match** — if local has "buried_in", match that
   against the candidate's cemetery
5. **Visit each candidate's memorial page** to extract full details
   (rank, bio, parents) — expensive but could push to 95%+

The current 84% is good enough for human review. The HTML viewer
is the safety net.
