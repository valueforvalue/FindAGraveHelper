# Learning: EasyOCR slice protocol — how to validate settings before a multi-hour commit

> **Earned by:** the 2026-07-29 L3 EasyOCR work. After Tesseract
> L0/L1/L2 left ~5000 of 9436 pension cards without a death date,
> we tried EasyOCR on a 100-widow slice (got ~1% real lift, settings
> looked right) and were about to commit to the multi-hour full run
> when we almost lost the canonical OCR file to a slice-clobber bug.
> This doc freezes the protocol so the next slice run can't repeat
> either mistake.

## TL;DR

- **Always slice first, never run full immediately.** ~50 records
  is the sweet spot: small enough to inspect by hand, big enough
  to see if the lift holds.
- **Always pass `--output <sidecar.json>` for slice runs.** The
  script refuses to write to the canonical
  `data/cards/red_ocr_results.json` when the input has < 1000
  records, unless you pass `--in-place`. This guard exists because
  of the clobber incident on 2026-07-29 (see "Why we slice" below).
- **Settings that are locked in for L3:** EasyOCR `en` model,
  CPU (`gpu=False`), `paragraph=False`, `detail=1`, confidence
  floor `>= 0.3`, throttle 0.25s. No need to retune these.
- **Lift estimate from real slices:** ~1% real lift over L2. Plan
  ~7 hours CPU for full 4891 no-date record pass (2087 widows +
  2909 soldiers). Don't expect more.

## Why we slice

The full L3 pass is `~5s × 4891 records = ~7 hours` of CPU on this
machine (no CUDA). That's too long to find out a setting was wrong.
We slice to:

1. **Confirm the parser still finds dates** on a small sample.
2. **Inspect output by hand** — read the `easy_text` field, look
   for obvious misses (EasyOCR garbles handwriting, drop conf
   threshold and you'll pick up noise).
3. **Measure lift** — `new_dates / records_with_easy_text` is the
   raw rate; subtract obvious false positives (1915 grant stamps,
   1865 war-end) to get the real lift.

Slice of 100 widows: 17 new dates = 17% raw, ~1% real.
Slice of 50 random (widows+soldiers): in progress at time of
writing.

## Slice procedure (reproducible)

```bash
# 1. Pick the records. Seed the RNG so the slice is reproducible.
python -c "
import json, random
from pathlib import Path
data = json.loads(Path('data/cards/red_ocr_results.json').read_text())
candidates = [r for r in data
              if not r.get('death_date') and not r.get('easy_text')]
random.seed(42)
pick = random.sample(candidates, 50)
Path('data/cards/easyocr_slice_50_random_input.json').write_text(
    json.dumps(pick, indent=2))
# Mirror to the output file so the script can write back without
# touching the canonical file.
Path('data/cards/easyocr_slice_50_random_output.json').write_text(
    json.dumps(pick, indent=2))
"

# 2. Run the slice. ALWAYS pass both --input and --output.
python -u scripts/ingest/easyocr_pass.py \
    --include-soldiers \
    --input  data/cards/easyocr_slice_50_random_input.json \
    --output data/cards/easyocr_slice_50_random_output.json \
    > data/easyocr_slice_50_random.log 2>&1 &

# 3. Watch the output file (script flushes every 60s).
watch 'python -c "
import json
from pathlib import Path
d = json.loads(Path(\"data/cards/easyocr_slice_50_random_output.json\").read_text())
done = sum(1 for r in d if r.get(\"easy_text\"))
dates = sum(1 for r in d if r.get(\"death_date\"))
print(f\"{done}/50 with easy_text, {dates}/50 with death_date\")
"'
```

## The 2026-07-29 clobber incident

**What happened:** I ran the slice with `--input easyocr_slice_50.json`
but forgot `--output`. The script's `--output` defaults to overwriting
`--input`, and the *canonical* default for `--output` was hardcoded
to `data/cards/red_ocr_results.json`. Result: the script read 50
records, processed 11, then wrote the 50-record list back to the
**canonical 9436-record file**, replacing it.

**Why we recovered:** the canonical file is gitignored
(`data/cards/red_ocr_results.json` in `.gitignore`), so no git
corruption. Found an intact 9436-record copy in
`%TEMP%\extract_conflict\merged\merged_tmp\pension-viewer-bundle\data\cards\red_ocr_results.json`
left over from a prior test run.

**The fix** (commit pending): the script now refuses to overwrite
the canonical file when the input looks like a slice (< 1000
records) unless `--in-place` is passed. Slice runs are still easy
— you just always pass `--output` to a sidecar.

## Locked-in settings (don't retune without reason)

| Setting | Value | Why |
|---|---|---|
| `--include-soldiers` for full pass | yes | Default is widows-only. The full run needs both. |
| `--only-widows` | implicit default | Use this for widow-only investigation runs. |
| `--priority-only` | not used yet | Filters to records where `red_text` is empty (EasyOCR's main value-add). Try this if full-pass lift is below 0.5%. |
| `--refresh` | off | Re-OCR even if `easy_text` is set. Useful when retuning EasyOCR conf floor. |
| EasyOCR `gpu` | False | No CUDA on this box. Setting True crashes. |
| EasyOCR `paragraph` | False | Each detected span is its own line. Better for date regex matching. |
| EasyOCR `detail` | 1 | We need `conf` per span so the conf-floor filter works. |
| Conf floor | 0.3 | Lower = more noise. Higher = miss faded ink. |
| Throttle | 0.25s | Gentle CPU cool-down. Don't drop below 0.1 or torch thrashes. |

## When you're ready for the full run

```bash
# Verify slice results by hand first.
python -c "
import json
from pathlib import Path
d = json.loads(Path('data/cards/easyocr_slice_50_random_output.json').read_text())
new = [r for r in d if r.get('death_date') and not r.get('red_text')]
print(f'{len(new)} records gained a death_date from EasyOCR text')
for r in new[:5]:
    print(f'  pcid={r[\"pensioncard_id\"]}: {r[\"death_date\"]}')
"

# If lift looks right, kick off the full pass in the background.
# --in-place is required because the input IS the canonical file.
python -u scripts/ingest/easyocr_pass.py \
    --include-soldiers \
    --in-place \
    > data/easyocr_full_run.log 2>&1 &

# Save PID for later.
echo $! > data/easyocr_full_run.pid
```

**Expected runtime:** 7 hours CPU. Background it. Kill with
`kill $(cat data/easyocr_full_run.pid)` if you need to stop.

## Resume behavior

- The script writes the output file every 60s.
- Each record's `easy_text` is set in memory immediately, so killing
  mid-pass loses at most the in-flight record + up to 60s of work.
- Restart the same command (no `--refresh`): records with
  `easy_text` already set are skipped automatically.

## Files

- `scripts/ingest/easyocr_pass.py` — the EasyOCR pass itself.
- `scripts/ingest/red_ink_ocr_pilot.py` — the L0–L2 Tesseract
  pipeline; exports `find_death_date` which L3 reuses.
- `data/cards/red_ocr_results.json` — canonical 9436-record OCR
  state. **Never overwrite from a slice run.**
- `data/cards/red_ocr_summary.json` — small summary JSON.
  Refreshed at end of L0/L1/L2; not touched by L3.

## Slice results so far

### Slice A: 100 widows (Tesseract L2 leftovers only)
Source: `data/easyocr_slice_100.log`. Settings: `--only-widows`
(no `--include-soldiers`), conf floor 0.3.

- 100/100 processed in 1444s (~24 min).
- 17 raw new dates.
- After by-hand filter (drop 1865 / 1915 grant stamps /
  correspondence dates): **1 real death date**.
- **Real lift: ~1%** of records that Tesseract L2 missed.

### Slice B: 50 random, mixed widows+soldiers
Source: `data/cards/easyocr_slice_50_random_output.json`.
Settings: `--include-soldiers`, seed=42, conf floor 0.3.

- 50/50 processed in 965s (~16 min).
- 30 raw new dates.
- After by-hand inspection: **~5 real death dates** (pcid 803,
  10002, 4742, 3263, 3498 — all from explicit "Deceased M-D-YYYY"
  stamps that Tesseract missed because the red-mask hid them).
- **Real lift: ~10%** on this slice.

The mixed-widows+soldiers slice has a meaningfully higher real
lift than the widows-only slice, mostly because the soldier cards
have cleaner DECEASED stamps that EasyOCR reads well.

### Parser bugs surfaced by the slice

Several false positives share a pattern: when the OCR text has no
death keyword (no "Deceased"/"died"/"killed"/"dead"), the
`find_death_date` fallback picks the first plausible date. On
pension cards the text is full of dates that ARE NOT deaths:

- `"Filed 6/14/15"` → picks 6/14/15 as death (grant date).
- `"Letter 3/6/23 gives Temp Address"` → picks 3/6/23 as death
  (correspondence date).
- `"ac 12/31-52 gives Ry3, 5-25, 3810 W. Park, Ok. City"` →
  picks 1955-08-19 as death, but the real Deceased stamp says
  1935-08-19 (EasyOCR misread `35` as `55`).

**Fix needed before full run:** require a death keyword near any
candidate date, OR add anti-keywords ("Letter"/"gives"/"Filed"/
"Changed"/"post card"/"GRANTED") that suppress nearby dates. The
slice made this clearly visible; do NOT start the 7h full run
until this is patched and re-sliced.

## Pre-flight checklist before the full run

1. Run slice A or B as described above.
2. Inspect the new death dates by hand. Count real vs false.
3. If real lift < 0.5%, abort — L3 isn't helping.
4. If real lift >= 0.5% but parser bugs are visible (slice B
   above), fix the parser and re-slice.
5. Once a slice comes back clean, kick off the full run with
   `--in-place` (see command above).
