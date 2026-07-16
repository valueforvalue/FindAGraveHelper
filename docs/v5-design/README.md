# v5.0 Design Documents

The next-generation Find a Grave search helper.

## Documents

| Doc | What |
|---|---|
| [`playbook.md`](./playbook.md) | The master design document — full architecture, sources, decisions. Originally written before validation. |
| [`strategy-ladder.md`](./strategy-ladder.md) | The 13 strategies in execution order, with validated hit-rates and per-strategy logic. |

## Status

**Phase: design complete, awaiting Path B (NPS data) before implementation.**

The broadened CW training set surfaced biases in our initial patterns
(see [`../research/broadened-set/`](../research/broadened-set/)).
We want to pull NPS Soldiers & Sailors index data before locking the
strategy ladder. NPS data adds:

- Officers (CMSR is enlisted-heavy)
- Alternate names (explicit "Alternate Name" field on cards)
- Non-regimental Confederate records (militia, reserves, home guard)
- Wider geographic coverage (especially VA)

## What we have

- 43,834-soldier broadened training set (17 Confederate, 5 Union
  regiments)
- 50.9% match rate between local data and broadened set
- Validated strategy ladder reaches 100% cold-start hit-rate on
  local 577 pairs
- Slug parser that handles 1-, 2-, 3-part and hyphenated forms
- Per-feature scoring function (Double Metaphone + Jaro-Winkler
  + Damerau-Levenshtein + state + unit)

## What's next

1. Pull NPS CWSS index (~6.3M records) — different data source
2. Re-validate strategy ladder against combined dataset
3. Build minimal v5.0 (B1, B2, B4, B5, C1 only) — ship
4. Add B3, B6-B9 strategies as needed based on real-world misses
5. Build Mode 2 (SWEEP) after Mode 1 (SNIPE) is validated by use