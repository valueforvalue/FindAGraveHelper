# Strategy Yield Research Report — Issue #69

**Generated:** 2026-07-21
**Method:** Live FaG searches for 6 soldiers × 10 strategies = 60 requests at 2.5s throttle
**Ground truth:** FaG memorial backlinks from dixiedata.db

---

## Soldiers Probed

| # | Name | Surname Type | Ground Truth |
|---|------|-------------|-------------|
| 1 | Frank Troop | rare | [37997921](https://www.findagrave.com/memorial/37997921) |
| 2 | Silas Hudson | rare | [138585373](https://www.findagrave.com/memorial/138585373) |
| 3 | Jahue Everett | rare | [22397759](https://www.findagrave.com/memorial/22397759) |
| 4 | Dewitt Lee | common | [43909545](https://www.findagrave.com/memorial/43909545) |
| 5 | Zachary Jones | common | [19845867](https://www.findagrave.com/memorial/19845867) |
| 6 | George Campbell | common | [23728390](https://www.findagrave.com/memorial/23728390) |

---

## Per-Strategy Hit Rates

| Strategy | Hits | Misses | Hit Rate | Avg Candidates | Best Use |
|----------|------|--------|----------|----------------|----------|
| **B1-exact** | 6 | 0 | **100%** | 3.8 | Baseline. Always run first. |
| **F1d-year-window** | 6 | 0 | **100%** | 2.0 | Best precision. Always #1 rank. |
| **F1b-deathyear** | 6 | 0 | **100%** | 3.5 | Good. Adds death year filter. |
| B4-fuzzy-last | 5 | 1 | 83% | 9.0 | Useful for common surnames. |
| B3-first-initial-fuzzy | 3 | 3 | 50% | 17.2 | Noisy. Hits ceiling (20) often. |
| **C1-cw-context** | 0 | 6 | **0%** | 1.0 | Dead weight. Remove or demote. |
| B2-middle-initial | — | — | — | — | Never fires (no middle initial in params). |
| B5-apostrophe | — | — | — | — | Never fires (0 apostrophe surnames in OK data). |
| F1a-birthyear-exact | — | — | — | — | Never fires. OK pensioners rarely have birth years in the input. |
| F1c-year-sniper | — | — | — | — | Never fires. Requires both birth + death year. |

---

## Rank Quality: Where Does the Correct Memorial Appear?

| Soldier | B1-exact | F1d-year-window | F1b-deathyear | B4-fuzzy-last |
|---------|----------|-----------------|---------------|---------------|
| Troop (rare) | **#1** | #1 | #1 | #1 |
| Hudson (rare) | **#1** | #1 | #1 | miss |
| Everett (rare) | **#1** | #1 | #1 | #1 |
| Lee (common) | **#1** | #1 | #1 | #3 |
| Jones (common) | **#1** | #1 | #1 | #2 |
| Campbell (common) | #4 | **#1** ✓ | #8 | #4 |

**Key finding:** F1d-year-window is the only strategy that puts Campbell at rank #1. B1-exact puts him at #4 behind 3 wrong George Campbells. Adding F1d-year-window as a follow-up to B1 would auto-accept Campbell correctly.

---

## Analysis

### B1-exact: 100% hit rate, but rank degrades for common names
For 5/6 soldiers, B1 returned the correct memorial at rank #1. For George Campbell (common name), B1 returned 11 candidates with the correct one at #4 — a human reviewer would need to scroll.

### F1d-year-window: High precision, perfect ranking
Consistently returns 2 candidates with the correct one at #1. The death year narrows the search enough to eliminate wrong-name collisions. **This should be the second strategy after B1, not buried at position 10.**

### C1-cw-context: Zero value
"Confederate States America" bio search never returns the correct memorial. It returns exactly 1 result each time which is always wrong. The FaG veteran flag + CSA bio search is too narrow to be useful as a strategy. **Recommend: remove from ladder or disable by default.**

### B3/B4 fuzzy: Useful for hard cases, noisy for easy ones
B3 hits 50% with 17 avg candidates — when it works, it works, but it brings massive noise. B4 hits 83% with 9 avg candidates. Both should be low-priority fallbacks, not early-ladder.

### Strategies that never fire in OK data
- **B5-apostrophe**: 0 apostrophe surnames in 665 soldiers
- **B2-middle-initial**: Only fires when middle is a single letter — good for the 89% who have middle names, but the strategy requires B1-exact params shape which already includes middle
- **F1a/F1c**: Require birth years — OK pensioners rarely have them in input data

---

## Recommendations

### 1. Reorder the strategy ladder
```
1. B1-exact              (100% hit, good precision)  ← keep first
2. F1d-year-window       (100% hit, best precision)  ← MOVE UP from #10
3. F1b-deathyear         (100% hit, good)            ← keep
4. B4-fuzzy-last         (83% hit, useful fallback)  ← keep
5. B3-first-initial-fuzzy (50% hit, noisy)           ← demote
6. C1-cw-context         (0% hit, dead)              ← remove or disable
```

### 2. Remove or disable C1-cw-context
0% hit rate over 6 soldiers. Returns noise. The `isVeteran=true` + `bio="Confederate States America"` search is too narrow. If needed for research, keep but disable from default ladder.

### 3. B1-exact + OK filter is sufficient for ~83% of records (rare surnames)
For unique/uncommon surnames (the majority of the OK dataset: 384 unique surnames among 565 soldiers with FaG links), B1-exact alone finds the correct memorial at rank #1. Only common surnames (Jones, Lee, Campbell, etc.) benefit from additional strategies.

### 4. F1d-year-window is the best second strategy
When B1 returns many candidates for a common surname, F1d narrows to 2 results with the correct one at rank #1. This should trigger auto-accept.

### 5. Throttle observation
All 60 requests completed without Cloudflare blocks at 2.5s throttle. The L1 floor works. Lowering to 1.5s was not tested in this probe (preserves the floor).

### 6. Birth year data gap
F1a and F1c never fire because the OK pensioner input records rarely carry birth years. If dixiedata.db has birth years (many do: 662/665 have death years, birth dates may also be present), enriching the pipeline input with birth years would unlock F1a and F1c, potentially improving precision further.

---

## Data Appendix

### dixiedata.db statistics (665 soldiers, 565 with FaG backlinks)
- 418 unique surnames → high diversity, most are rare
- 595/665 (89%) have middle names
- 662/665 (99.5%) have death years
- 0 apostrophe surnames
- 1113 total `records` entries with FaG URLs

### Probe methodology
- 6 soldiers: 3 rare surname, 3 common surname
- 10 strategies each (6 that fire, 4 that skip)
- 60 FaG requests at 2.5s throttle
- Ground truth: memorial ID from dixiedata.db `records.details`
- OK state filter on all searches (`locationId=state_38`)
- No birth years passed (simulating real pipeline input)
