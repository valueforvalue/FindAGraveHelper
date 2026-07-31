# 2026-07-31 — Issue #139: Diagnosis of the NO_KEYWORD_BUT_DATE bucket

Spun out of the L0–L3 follow-up work on issue #139 (red-ink OCR
death-date extraction quality). The L0–L2 parser changes landed
on master (commit `ad1cee4`) and dropped the bucket from 1818
→ 1648. The L3 EasyOCR pass (commit `9e85f53`) brought it back
up to **2116** in the latest audit (2026-07-31, 3272 total
findings).

## The bucket

`scripts/audit/audit_death_dates.py` flags
`NO_KEYWORD_BUT_DATE` for every pensioner whose `death_date_iso`
is set but whose `near_death_keyword=False`,
`mentions_soldier_name=False`, AND `is_widow_card=False` (a
soldier card with a year-only pick from a non-death context).

The 2116 records break down by year:

| Year | Count | Likely source |
|------|-------|---------------|
| 1915 | 136 | GRANTED stamp (`OCT 7, 1915`) — Tesseract+EasyOCR both see `1915` |
| 1920 | 140 | Likely from year-only widow pickups or pension-stamp variants |
| 1929 | 136 | |
| 1928 | 130 | |
| 1921 | 131 | Real death years OR stamp variants — needs manual review |
| 1922 | 127 | |
| 1926–1935 | ~700 | Spread, mostly real widow-card picks the parser didn't downgrade |
| 1916, 1917 | ~170 | Mix of war-end + real widow picks |
| 1865 | 42 | War-end parole stamp; L2 already rejects when other candidates exist |
| 1866–1914 | ~80 | Mostly REAL death years (Civil War vets who died before pension started) |

The 1920–1929 cluster is the ambiguous center. Some are real
widow death years where the OCR happened to not see the
"Deceased" keyword. Some are stamps.

## Why L0–L2 didn't fix it

L0–L2 added filters and tightened precision, but **the EasyOCR
pass was never re-enriched**. Specifically:

1. `scripts/ingest/easyocr_pass.py:_merge_result` populates
   `rec["easy_text"]` and a fresh `rec["death_date"]` (with
   `source_pass="easyocr"`) when Tesseract found nothing.
2. The death-date parsing it runs is the L0 parser (before L1
   line-strip and L2 filters).
3. `scripts/ingest/re_enrich_from_ocr.py` (the re-driver) only
   re-parses `red_text` and `full_text`. **It never touches
   `easy_text`.**
4. So all 2008 `source_pass=easyocr` records hold STALE L0-era
   death_date values.

## The 1915 stamp pattern

Spot-checked 20 records with `death_year=1915`. Every one has
the GRANTED stamp variant in OCR text:

```
GRANTED OCT 7 = 1915     (pcid=9079, red_text)
GRANTED 00T7 - 1915      (pcid=8641, easy_text)
GRANTED ON7=1915         (pcid=1084, easy_text)
GRANTED 0CT7 - 1915      (pcid=11438, easy_text)
```

The L1 line-stripper in `red_ink_ocr_pilot.py:strip_form_lines`
drops the `REJECTED` and `GRANTED` keywords but **leaves the
orphaned date**. When `find_death_date` scans the cleaned text,
`1915` is the only candidate year, the L2 filter
(`if year==1915 and other_years: skip`) doesn't fire (no other
years), and the year-only pick survives.

## The fix path (no re-OCR needed)

### Fix A: Re-enrich easy_text with the current parser

Add an `easy_text` pass to `re_enrich_from_ocr.py`:

```python
for rec in results:
    red_parsed, red_window = find_death_date(red_text, soldier_name)
    full_parsed, full_window = find_death_date(full_text, soldier_name)
    easy_parsed, easy_window = find_death_date(easy_text, soldier_name)
    # Score: prefer the candidate that came from the text source
    # matching the original source_pass, then by near_death_keyword,
    # then by full-date > year-only.
    chosen = ... # 3-way pick
```

This will recompute ~2008 dates using the L1+L2 parser. The
GRANTED 1915 stamp case will be correctly rejected because the
L1 line-strip drops `REJECTED | GRANTED ... OCT 7 ...` even
when the year appears on an orphan line — wait, let me verify.

Actually, the L1 stripper drops lines matching
`LINE_STRIP_PATTERNS`. The patterns include:
```python
re.compile(r"(?i)\b(granted|grant)\b"),
re.compile(r"(?i)\b(rejected|rejection)\b"),
```

But `ON7=1915` is its OWN chunk after splitting (no GRANTED
keyword on it). So the orphan year survives. **Fix A alone
doesn't solve the 1915 problem.**

### Fix B: Strengthen the line-strip to drop orphan stamp dates

Add a post-strip pass: after the initial chunk-level drop,
look at the SURROUNDING chunks. If a line containing only
digits/separators (a stamp fragment) appears within N chunks of
a stripped keyword chunk, drop the orphan too.

Or simpler: tighten the strip patterns to match the orphan
patterns:
```python
re.compile(r"(?i)\b(?:OCT|0CT|00T|OC|T)\s*[\d\s=\-]+\d{4}\b"),
re.compile(r"(?i)\b(?:NOV|N0V|NUV)\s*[\d\s=\-]+\d{4}\b"),
re.compile(r"(?i)\bON\s*\d\s*=?\s*\d{4}\b"),
```

The `OCT 7 = 1915` / `OCT7 - 1915` / `ON7=1915` variants share
a pattern: `(<MONTH>|<OCT>?[A-Z0-9]?[A-Z]?<T|N>[\s=\-]*\d{1,2}[\s=\-]*\d{4})`.

Or, even simpler: when the only year candidate in cleaned text
is exactly 1915 AND the source_pass was easyocr/full-fallback,
require an additional death-keyword in the window. This catches
the stamp case without depending on the broken line splitter.

### Fix C: Drop `source_pass="easyocr"` records that don't carry a death keyword

The EasyOCR pass wrote `rec["death_date"] = parsed` only when
`rec.get("death_date") is None` AND parsed was non-None. Many
of those parsed values are year-only picks where the L0 parser
got the GRANTED stamp year. After re-enriching with the L1+L2
parser, those will become `None` (correctly). The audit will
reclassify them as `WIDOW_BUT_NO_DATE` if `is_widow_card` or
`NO_DATE` if not.

## Expected impact

Running the re-enrich with all three fixes (A + B + C):

- `NO_KEYWORD_BUT_DATE`: 2116 → ~600 (estimated, mostly the
  1866-1910 tail + genuine-no-context cases that need manual
  review)
- `WIDOW_BUT_NO_DATE`: 1052 → ~1200 (the reclassified cases)
- `FULL_DATE_BUT_YEAR_ONLY`: 80 → ~0 (mechanical promotion via
  re-running the date regex over `easy_text` / `full_text`)
- Total findings: 3272 → ~2500 (~25% reduction)

The remaining ~600 NO_KEYWORD_BUT_DATE are the hard cases that
need image preprocessing (L4: top-right ROI crop + EasyOCR
re-pass). That's a separate slice.

## Acceptance criteria

- [ ] `re_enrich_from_ocr.py` processes `easy_text` (Fix A)
- [ ] `find_death_date` or `strip_form_lines` drops orphan
      GRANTED 1915 stamp patterns (Fix B)
- [ ] Re-run re-enrich; audit regenerated
- [ ] Findings count drops measurably (>20% on NO_KEYWORD_BUT_DATE)
- [ ] Tests added for the new easy_text pass + stamp patterns
- [ ] No regression: pensioners that should have a death date
      keep one
- [ ] Suite: still 1642+ passing

## Files to touch

- `scripts/ingest/re_enrich_from_ocr.py` — add easy_text pass
- `scripts/ingest/red_ink_ocr_pilot.py` — strengthen line-strip
  (add ORPHAN_STAMP_RE pattern, or post-pass)
- `tests/test_red_ink_ocr_pilot.py` — tests for new patterns
- `data/audit_death_dates_report.json` — regenerated
- `CHANGELOG.md [Unreleased]` — entry for L4

## Related

- Issue #138: parent ticket for the red-ink OCR pipeline
- Issue #139: this issue
- Commit `ad1cee4`: L2 precision refinements on master
- Commit `9e85f53`: L3 EasyOCR pass complete