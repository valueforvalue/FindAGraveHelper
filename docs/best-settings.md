# Best pipeline settings

Derived from DD benchmark (n=40, no death_year) and real pensioner testing.

## Recommended config

```json
{
  "engine": {
    "throttle": 1.5,
    "state_filter": "OK",
    "relax_throttle_floor": true
  },
  "pipeline": {
    "mode": {
      "mode": "none",
      "max_refinements": 0
    }
  }
}
```

## Why

| Setting | Value | Reason |
|---|---|---|
| `mode` | `none` | Refinement strategies (B3-fuzzy, F3-nickname, etc.) add 0% incremental recall on DD benchmark. Save 12+ FaG requests per 10 pensioners. |
| `throttle` | 1.5s | Safe for slice runs. Full 7,758 run still needs 2.5s L1 floor. |
| `relax_throttle_floor` | `true` | Required for throttle < 2.5s. |
| `state_filter` | `OK` | Narrows to OK-buried candidates. Broadens to US when OK returns empty. |
| `threshold` | `hardcoded` / 0.85 | Calibrated classifier available but hardcoded is simpler. |

## Post-scoring features (always active)

These run automatically in `run_unified.py` after scheduler drain, before projection:

| Feature | Trigger | Boost | Cost |
|---|---|---|---|
| Spouse verification | Widow + spouse-linked candidate + score >= 0.65 | +0.15 | 1 memorial page nav per verified candidate |
| Memorial CSA signals | Regiment + non-widow + score 0.50-0.80 | +0.08 | 1 memorial page nav per borderline pensioner |
| Regiment-era bonus | Regiment + no death_year + candidate in ACW window | +0.05 | Free (scoring only) |
| OK burial bump | Candidate buried in OK | Weight 0.10→0.15 | Free |
| Cemetery type | Confederate/National/Veterans cemetery | +0.03 | Free |
| Uniqueness factor | >2 same-name candidates | Penalty on unverified only | Free |

## CLI

```bash
PYTHONPATH=. python scripts/pipeline/run_unified.py \
    --config output/<run>/config.json \
    --throttle 1.5 --relax-throttle-floor --mode none \
    --limit <N>
```

## DD benchmark results (n=40)

| Metric | Value |
|---|---|
| Recall | 92% |
| Top-1 | 68% |
| Top-3 | 85% |
| Auto-accept | 53% |
| Strategies per pensioner | 2 (OK + US scope, B1-exact) |

## Real pensioner results (n=10, 5 widows)

| Metric | Value |
|---|---|
| Auto-accept | 6/10 |
| Spouse verified | 3/5 widows |
| Memorial CSA signals | 6/10 |
| State extraction | 20/20 all candidates |
