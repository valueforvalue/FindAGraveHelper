## Finding

After commit `d50cef0` (issue #144 fix layer), the suspicious-death-date
audit dropped from **1,151 → 445 flagged**. The 445 remaining are:

- **333 EMPTY_BUT_STAMP_PRESENT** — `death_year` empty in sidecar, but a
  DECEASED/DEATH/DIED substring exists in cached OCR text. Common cause:
  OCR-garbled stamp like `DECEASED LecerlvoO` or handwritten `Deceased 12-10-27`
  that EasyOCR couldn't read. Parser cannot recover; needs human eyeball.
- **84 NUMERIC_SUBSTITUTION** — cached year has a ±1-digit variant
  nearby that has a death keyword. Likely real OCR digit errors
  (1923 → 1928, etc.). Parser can't decide which is correct.
- **31 FILE_DATE_TOO_FAR** — `filed_year − death_year > 6`. Real
  outliers worth a glance; mostly widows that slipped the widow-skip.

These 445 need human review against the actual card images. There is
**no operator-facing tool** for this today. The pieces exist
(`data/audit_runs/suspicious_<ts>.json` carries `pensioncard_id` +
per-finding `flags[]`; `data/cards/img/<pcid>__<pid>.jpg` carries the
front scan; the spot-check tool already does a small sample of this
manually), but nothing ties them into a review workflow.

## Goal

Build a standalone HTML review page that an operator can open in a
browser, walk through all 445 flagged records, mark each with a
3-way verdict, and export a verified sidecar. No server, no build
step — same pattern as the spot-check pack.

## Acceptance criteria

- [ ] **Standalone HTML file** at e.g. `scripts/view/death_review.html`
      (or under `data/audit_runs/review_<ts>/`). Mirrors the
      `data/spot_check/<ts>/` layout: open the HTML, it loads the
      JSON + images from sibling files.
- [ ] Loads `data/audit_runs/suspicious_<ts>.json` (latest run) +
      `docs/research/digitalprairie/ok_pensioners.with_death_dates.json`
      + `data/cards/img/<pcid>__<pid>.jpg` images. Filter UI: by
      tag (`EMPTY_BUT_STAMP_PRESENT` / `NUMERIC_SUBSTITUTION` /
      `FILE_DATE_TOO_FAR` / all).
- [ ] Per-record panel:
      - Card image (front scan) at top
      - Pensioner name + widow flag + cached `death_year` + `death_date_iso`
      - Flag chips (one per `flag` in finding) with the heuristic `note`
      - The OCR text excerpts that produced the flag (when available —
        red_text / full_text / easy_text excerpts; mirror what
        `spot_check_ocr.py` already does in `manifest.json`)
      - **Three verdict buttons**: CONFIRM (cached year is correct) /
        CORRECT (operator types new `death_year` + optional ISO) /
        UNCERTAIN (skip; revisit later)
      - Keyboard shortcuts: `Y` = CONFIRM, `C` = CORRECT (focus year
        input), `U` = UNCERTAIN, `J` / `K` = next/prev record
      - Progress bar: `47 / 445 reviewed (10.6%)` with counts per verdict
- [ ] **Persists reviewer state to localStorage** keyed by audit-run
      timestamp. Reloading the page restores progress.
- [ ] **Export button**: dumps a sidecar
      `ok_pensioners.reviewed.json` containing only the corrected
      records (CONFIRM verdicts are skipped; they're already correct).
      Schema: same shape as `with_death_dates.json` but only includes
      pensioners that were CORRECTED, with new `death_year` +
      `death_date_iso`. Promotion to `ok_pensioners.json` remains a
      manual `cp` step (CHANGELOG convention; source untouched).
- [ ] **Scripts/CLI to package a review pack**:
      `python scripts/audit/build_review_pack.py --audit suspicious_<ts>.json`
      copies the JSON + images into `data/audit_runs/review_<ts>/`
      alongside the HTML. Operator opens the HTML, reviews, exports
      `ok_pensioners.reviewed.json`, then runs the existing
      `enrich_pensioners_with_death_dates.py` workflow to merge.
- [ ] Tests in `tests/test_build_review_pack.py` for pack assembly
      (image copy, JSON subset, relative paths). 1,688-test suite
      stays green.

## Out of scope (still)

- Auto-correcting the sidecar from operator verdicts. The export is
  explicit and the operator reviews the export before promoting.
- Multi-user review (state is local per-browser). Out of scope until
  multi-user is actually needed.
- Streaming the audit findings into the existing
  `scripts/ingest/build_pensioncard_viewer.py` output. That viewer is
  the always-on per-letter page; the review pack is its own thing.
- Fixing the underlying 333 EMPTY records beyond what `d50cef0`
  already does. They're genuine OCR-quality limits.

## Linked artifacts

- `scripts/audit/audit_suspicious.py` — read-only audit (sister script)
- `data/audit_runs/suspicious_20260802_233222.json` — current run,
  445 findings
- `data/cards/img/<pcid>__<pid>.jpg` — front-scan jpgs (already
  downloaded by `download_pensioncard_images.py`)
- `data/spot_check/20260802_233301/` — sibling pattern (manifest.json
  + cards/*.jpg + summary.md) that the review pack should mirror
- `scripts/ingest/build_pensioncard_viewer.py` — reference for the
  card-image path resolution (`front_scan_path`)