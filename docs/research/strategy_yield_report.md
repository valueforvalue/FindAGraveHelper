# Strategy Yield Research Report

Generated: 2026-07-21 09:14:08

## Summary

Probed 6 soldiers x 10 strategies against real Find a Grave.

Throttle: 2.5s (L1 floor).

### Soldiers probed
- **Frank Troop** (rare_surname) - ground truth: [37997921](https://www.findagrave.com/memorial/37997921)
- **Silas Hudson** (rare_surname) - ground truth: [138585373](https://www.findagrave.com/memorial/138585373)
- **Jahue Everett** (rare_surname) - ground truth: [22397759](https://www.findagrave.com/memorial/22397759)
- **Dewitt Lee** (common_surname) - ground truth: [43909545](https://www.findagrave.com/memorial/43909545)
- **Zachary Jones** (common_surname) - ground truth: [19845867](https://www.findagrave.com/memorial/19845867)
- **George Campbell** (common_surname) - ground truth: [23728390](https://www.findagrave.com/memorial/23728390)

## Per-Strategy Hit Rates
| Strategy | Hits | Misses | Hit Rate | Unique Saves |
|----------|------|--------|----------|--------------|
| B1-exact | 6 | 0 | 100% | 0 |
| B2-middle-initial | 0 | 0 | 0% | 0 |
| B3-first-initial-fuzzy | 3 | 3 | 50% | 0 |
| B4-fuzzy-last | 5 | 1 | 83% | 0 |
| B5-apostrophe | 0 | 0 | 0% | 0 |
| C1-cw-context | 4 | 2 | 67% | 0 |
| F1a-birthyear-exact | 0 | 0 | 0% | 0 |
| F1b-deathyear | 6 | 0 | 100% | 0 |
| F1c-year-sniper | 0 | 0 | 0% | 0 |
| F1d-year-window | 6 | 0 | 100% | 0 |

## B1-Exact Baseline
- B1-exact found the correct memorial for **6/6** soldiers (100%)

## Strategies That Found What B1 Missed

B1-exact found every soldier. No strategies needed to save the day.

## Recommendations

Based on 6 soldiers probed:

### Strategies that never fire
- **B2-middle-initial**: skipped 6/6 times
- **B5-apostrophe**: skipped 6/6 times
- **F1a-birthyear-exact**: skipped 6/6 times
- **F1c-year-sniper**: skipped 6/6 times

### Throttle observation
- All searches ran at 2.5s throttle (L1 floor)
- No Cloudflare blocks observed during probe