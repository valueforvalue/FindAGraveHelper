# Re-OCR runbook — issue #144

## Context

After three parser fixes (source-order tie-break, "Entered Home"
anti-keyword, MIN_YEAR 1865→1860 + Month YYYY pattern), 4 of 11
eyeballed bugs are fixed. The remaining 7 are OCR-quality issues
(digit misreads, handwritten stamps the OCR completely missed). A
fresh EasyOCR pass on the 3,393 candidate cards may recover
~600-800 additional death dates.

## Prerequisites

```bash
pip install -r requirements-dev.txt   # torch + easyocr
python -m easyocr --download en       # first run downloads model
```

GPU required (RTX 3050 6 GB confirmed working). CPU fallback works
but is 10-30× slower.

## Step 1 — Regenerate the slice (if sidecar/audit changed)

```bash
python -c "
import json, sys; sys.path.insert(0, '.')
from scripts.ingest.spot_check_ocr import front_scan_path
sidecar = json.loads(open('docs/research/digitalprairie/ok_pensioners.with_death_dates.json', encoding='utf-8').read())
audit = json.loads(sorted(__import__('pathlib').Path('data/audit_runs').glob('suspicious_*.json'))[-1].read_text(encoding='utf-8'))
ocr = json.loads(open('data/cards/red_ocr_results.json', encoding='utf-8', errors='replace').read())
flagged = {f.get('pensioncard_id') for f in audit.get('findings', []) if f.get('pensioncard_id')}
no_date = {r['pensioncard_id'] for r in sidecar if not r.get('death_year') and r.get('pensioncard_id') and front_scan_path(r['pensioncard_id']) and front_scan_path(r['pensioncard_id']).exists()}
all_pcids = flagged | no_date
slice_records = [r for r in ocr if r.get('pensioncard_id') in all_pcids and front_scan_path(r['pensioncard_id']) and front_scan_path(r['pensioncard_id']).exists()]
json.dump(slice_records, open('data/cards/ocr_reocr_slice.json', 'w'), ensure_ascii=False)
print(f'slice: {len(slice_records)} records')
"
```

## Step 2 — Run EasyOCR on the slice

```bash
python scripts/ingest/easyocr_pass.py \
    --input data/cards/ocr_reocr_slice.json \
    --output data/cards/ocr_reocr_slice_out.json \
    --refresh \
    --include-soldiers \
    --workers 4 \
    --throttle 0.05
```

Expected time: ~19 min at 3 cards/sec with 4 workers on GPU.
The slice file is gitignored (regenerable). Output writes to a
separate file — the canonical `red_ocr_results.json` is NOT
touched in this step.

## Step 3 — Merge fresh easy_text back into canonical

```bash
python -c "
import json
canonical = json.loads(open('data/cards/red_ocr_results.json', encoding='utf-8', errors='replace').read())
fresh = json.loads(open('data/cards/ocr_reocr_slice_out.json', encoding='utf-8', errors='replace').read())
by_image = {r['image']: r for r in fresh}
updated = 0
for rec in canonical:
    if rec['image'] in by_image:
        fresh_rec = by_image[rec['image']]
        if fresh_rec.get('easy_text', '') != rec.get('easy_text', ''):
            rec['easy_text'] = fresh_rec.get('easy_text', '')
            rec['easy_text_len'] = fresh_rec.get('easy_text_len', 0)
            updated += 1
print(f'merged {updated} updated easy_text fields')
json.dump(canonical, open('data/cards/red_ocr_results.json', 'w'), ensure_ascii=False)
"
```

## Step 4 — Re-run enrich pipeline

```bash
python scripts/ingest/re_enrich_from_ocr.py
python scripts/ingest/enrich_pensioners_with_death_dates.py
```

## Step 5 — Re-audit + spot-check

```bash
python scripts/audit/audit_suspicious.py
python scripts/ingest/spot_check_ocr.py --seed 42
```

Compare the new audit flag count to the pre-re-OCR baseline
(1,151 flagged / 7,709 audited as of 2026-08-01 22:47).

## Expected lift

| Category | Cards | Expected recovery |
|---|---|---|
| EMPTY_BUT_STAMP_PRESENT | 577 | ~230 (40% — fresh OCR may read stamps the cached pass garbled) |
| GRANTED_PICK | 928 | ~50 (parser logic issue, not OCR quality) |
| NUMERIC_SUBSTITUTION | 171 | ~50-100 (fresh OCR may fix digit misreads) |
| No-date with images | 2,983 | ~300-450 (10-15% — handwritten stamps) |
| **Total** | **3,393** | **~600-800** |

Conservative target: enriched 3,607 → ~4,200-4,400 (54% → ~55-57%).
