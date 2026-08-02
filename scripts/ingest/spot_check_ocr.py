#!/usr/bin/env python3
"""Random spot-check of OCR'd death dates against the card image.

The death-date extraction pipeline runs in three passes (red-window
Tesseract, full-image Tesseract fallback, EasyOCR). All three use a
common `find_death_date` parser with fuzzy keyword matching. We've
seen "DECEASED" misread as `peceased`, `Dededsed`, `DBCBASBD`,
`DSEEASED`, etc. — the fuzzy matcher catches most of these but not
all, and a regex miss can quietly assign a wrong death year to a
pensioner.

This script does NOT modify any data. It:

  1. Samples N pensioncard_ids stratified by source_pass bucket
     (red / full-fallback / easyocr / None) + a NO_KEYWORD_BUT_DATE
     bucket from the audit report.
  2. Runs EasyOCR on the front scan of each sampled card (the
     existing L3 run was a single pass; this re-runs to give us
     fresh text to compare against the cached parser output).
  3. Writes a side-by-side review pack to
     `data/spot_check/<timestamp>/`:
        - manifest.json — full record (name, claimed year/iso,
          source_pass, cached easy_text, fresh easyocr text,
          parser verdict on the fresh text)
        - cards/<pensioncard_id>.jpg — copy of the card image
        - summary.md — quick-eyeball table

Operator opens the images in any viewer (or the v2 review UI
wired into the same pensioncard_ids), checks the year against the
stamp, marks each row PASS / FAIL / UNCERTAIN. Manual corrections
are NOT auto-applied — they feed into a follow-up issue/PR.

Why this exists: the audit script flags "wrong year" categories,
but a wrong year that *looks plausible* (e.g. 1923 instead of 1933)
passes every audit filter. Only eyeballing catches those.

Usage:
    python scripts/ingest/spot_check_ocr.py
    python scripts/ingest/spot_check_ocr.py --n-enriched 50 --n-hard 30
    python scripts/ingest/spot_check_ocr.py --seed 42   # reproducible
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

# We need easyocr + torch; both come from requirements-dev.txt.
# The main pipeline runtime stays clean of this dep.
import easyocr  # noqa: E402

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Reuse the parser from the canonical pipeline so the "parser
# verdict on fresh easyocr text" column is apples-to-apples with
# what the pipeline actually decided.
from scripts.ingest.red_ink_ocr_pilot import find_death_date  # noqa: E402

# Paths
SIDECAR = _ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners.with_death_dates.json"
OCR_RESULTS = _ROOT / "data" / "cards" / "red_ocr_results.json"
AUDIT_REPORT = _ROOT / "data" / "audit_death_dates_report.json"
IMG_DIR = _ROOT / "data" / "cards" / "img"
AUDIT_MD = _ROOT / "data" / "audit_death_dates_report.md"
OUT_ROOT = _ROOT / "data" / "spot_check"

# Where the front-scan jpg lives on disk. Existing pipeline naming
# is `<back_id>__<front_id>.jpg` (two-sided scans). For single-sided
# scans the naming is `<front_id>__<front_id>.jpg`. We pick the file
# whose front_id == pensioncard_id.
FRONT_SCAN_RE = __import__("re").compile(r"^(\d+)__(\d+)\.jpg$")


def front_scan_path(pcid: int) -> Path | None:
    """Return the path of the front scan for a pensioncard_id, or
    None if no scan is on disk."""
    back_prefix = f"{pcid}__"
    for entry in IMG_DIR.iterdir():
        m = FRONT_SCAN_RE.match(entry.name)
        if m and int(m.group(2)) == pcid:
            return entry
    # Fallback: any filename starting with the pcid as the front half.
    candidates = list(IMG_DIR.glob(f"*__{pcid}.jpg"))
    return candidates[0] if candidates else None


def load_inputs():
    """Load sidecar + OCR results + audit findings into memory."""
    sidecar = json.loads(SIDECAR.read_text(encoding="utf-8"))
    rows_by_id = {r["id"]: r for r in sidecar}
    ocr = json.loads(OCR_RESULTS.read_text(encoding="utf-8", errors="replace"))
    # Per-pcid OCR records (may be 2 for two-sided scans; we keep all)
    ocr_by_pcid: dict[int, list[dict]] = defaultdict(list)
    for rec in ocr:
        pcid = rec.get("pensioncard_id")
        if pcid is not None:
            ocr_by_pcid[pcid].append(rec)
    # Audit findings keyed by pensioner_id (only the NO_KEYWORD_BUT_DATE
    # bucket we care about; full audit is large)
    no_keyword_pids: set[int] = set()
    if AUDIT_REPORT.exists():
        findings = json.loads(AUDIT_REPORT.read_text(encoding="utf-8"))
        for f in findings.get("findings", []):
            if f.get("tag") == "NO_KEYWORD_BUT_DATE":
                pid = f.get("pensioner_id")
                if pid is not None:
                    no_keyword_pids.add(pid)
    return rows_by_id, ocr_by_pcid, no_keyword_pids


def stratified_sample(rows_by_id: dict, ocr_by_pcid: dict, *,
                      n_enriched: int, n_hard: int,
                      rng: random.Random) -> list[tuple[int, str]]:
    """Return [(pensioner_id, bucket)] for the spot-check.

    Enriched bucket: stratified by source_pass (red / full-fallback /
    easyocr). Hard bucket: NO_KEYWORD_BUT_DATE audit findings.
    """
    # Bucket enriched pensioners by source_pass of their card.
    buckets: dict[str, list[int]] = defaultdict(list)
    for pid, row in rows_by_id.items():
        if not row.get("death_year"):
            continue
        pcid = row.get("pensioncard_id")
        if pcid is None or pcid not in ocr_by_pcid:
            continue
        recs = ocr_by_pcid[pcid]
        # If any image was tagged easyocr, that wins (best signal).
        passes = [r.get("source_pass") for r in recs if r.get("death_date")]
        if not passes:
            continue
        # Prefer easyocr > full-fallback > red as the bucket label.
        if "easyocr" in passes:
            buckets["easyocr"].append(pid)
        elif "full-fallback" in passes:
            buckets["full-fallback"].append(pid)
        elif "red" in passes:
            buckets["red"].append(pid)
    # Aim for ~equal split across the 3 source_pass buckets.
    per_bucket = max(1, n_enriched // 3)
    sample: list[tuple[int, str]] = []
    for bname in ("red", "full-fallback", "easyocr"):
        pool = buckets.get(bname, [])
        rng.shuffle(pool)
        for pid in pool[:per_bucket]:
            sample.append((pid, bname))
    # Hard bucket: pensioners with NO death_year whose card has
    # OCR text — i.e. the parser genuinely missed a date that
    # might be on the card. (Audit's NO_KEYWORD_BUT_DATE tag
    # is the OPPOSITE: date extracted but no death keyword.
    # Useful in its own right, but we want the missed-set here.)
    hard_pool = [
        pid for pid, row in rows_by_id.items()
        if not row.get("death_year")
        and row.get("pensioncard_id") in ocr_by_pcid
    ]
    rng.shuffle(hard_pool)
    for pid in hard_pool[:n_hard]:
        sample.append((pid, "no_date_with_ocr"))
    return sample


def run_easyocr(reader, img_path: Path) -> str:
    """EasyOCR pass; concatenate the text fields in reading order."""
    if not img_path.exists():
        return ""
    try:
        results = reader.readtext(str(img_path), detail=0, paragraph=False)
    except Exception as exc:  # bad image, OOM, etc.
        return f"[easyocr error: {exc}]"
    return "\n".join(results)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n-enriched", type=int, default=30,
                    help="size of the stratified enriched sample "
                         "(split ~evenly across red/full-fallback/easyocr)")
    ap.add_argument("--n-hard", type=int, default=20,
                    help="size of the NO_KEYWORD_BUT_DATE audit sample")
    ap.add_argument("--seed", type=int, default=0,
                    help="RNG seed for reproducible sampling")
    ap.add_argument("--no-easyocr", action="store_true",
                    help="skip the fresh easyocr pass; only copy images "
                         "and emit the manifest. Useful if easyocr isn't "
                         "installed and the operator just wants images.")
    ap.add_argument("--gpu", action="store_true", default=True,
                    help="use GPU for easyocr (default; auto-detected)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("spot_check")

    rng = random.Random(args.seed)
    rows_by_id, ocr_by_pcid, _ = load_inputs()
    sample = stratified_sample(rows_by_id, ocr_by_pcid,
                              n_enriched=args.n_enriched,
                              n_hard=args.n_hard,
                              rng=rng)
    if not sample:
        log.error("empty sample — check input files")
        return 1
    log.info("sampled %d pensioners (seed=%d)", len(sample), args.seed)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / ts
    cards_dir = out_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    log.info("output: %s", out_dir)

    if args.no_easyocr:
        reader = None
    else:
        log.info("loading easyocr reader (gpu=%s)...", args.gpu)
        reader = easyocr.Reader(["en"], gpu=args.gpu, verbose=False)
        log.info("easyocr ready")

    manifest_rows: list[dict] = []
    summary_rows: list[dict] = []
    started = time.time()
    for i, (pid, bucket) in enumerate(sample, 1):
        row = rows_by_id[pid]
        pcid = row.get("pensioncard_id")
        claimed_year = row.get("death_year") or ""
        claimed_iso = row.get("death_date_iso") or ""
        # Source pass of the cached extraction (best signal wins).
        cached_passes = [r.get("source_pass") for r in ocr_by_pcid.get(pcid, [])
                         if r.get("death_date")]
        cached_pass = ""
        if "easyocr" in cached_passes:
            cached_pass = "easyocr"
        elif "full-fallback" in cached_passes:
            cached_pass = "full-fallback"
        elif "red" in cached_passes:
            cached_pass = "red"
        cached_easy_text = ""
        for rec in ocr_by_pcid.get(pcid, []):
            if rec.get("easy_text"):
                cached_easy_text = rec["easy_text"]
                break
        img = front_scan_path(pcid) if pcid else None
        img_rel = ""
        if img and img.exists():
            dst = cards_dir / f"{pcid}_{pid}.jpg"
            shutil.copy2(img, dst)
            img_rel = f"cards/{dst.name}"
        fresh_easy_text = ""
        parser_verdict = ""
        if reader is not None and img and img.exists():
            fresh_easy_text = run_easyocr(reader, img)
            parsed, _window = find_death_date(fresh_easy_text, row.get("last_name") or "")
            if parsed:
                parser_verdict = parsed.get("iso") or parsed.get("year") or ""
        manifest_rows.append({
            "pensioner_id": pid,
            "pensioncard_id": pcid,
            "name_raw": row.get("name_raw"),
            "last_name": row.get("last_name"),
            "bucket": bucket,
            "claimed_death_year": claimed_year,
            "claimed_death_date_iso": claimed_iso,
            "cached_source_pass": cached_pass,
            "cached_easy_text_excerpt": cached_easy_text[:500],
            "fresh_easyocr_text_excerpt": fresh_easy_text[:500],
            "parser_verdict_on_fresh_text": parser_verdict,
            "image_path": img_rel,
        })
        summary_rows.append({
            "bucket": bucket,
            "pid": pid,
            "pcid": pcid,
            "name": row.get("name_raw"),
            "claimed": f"{claimed_year}/{claimed_iso}",
            "src_pass": cached_pass,
            "fresh_parser": parser_verdict or "—",
            "img": img_rel,
        })
        if i % 5 == 0:
            elapsed = time.time() - started
            rate = i / elapsed if elapsed else 0
            log.info("processed %d/%d (%.1f/s)", i, len(sample), rate)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # summary.md — quick eyeball table.
    md_lines = [
        f"# Spot-check pack — {ts}",
        "",
        f"- Total records: **{len(sample)}**",
        f"- Seed: `{args.seed}`",
        f"- EasyOCR fresh pass: {'yes' if reader else 'no'}",
        "",
        "| bucket | pid | pcid | name | claimed (year/iso) | src_pass | parser-on-fresh | image |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in summary_rows:
        md_lines.append(
            f"| {r['bucket']} | {r['pid']} | {r['pcid']} | "
            f"{r['name']} | {r['claimed']} | {r['src_pass']} | "
            f"{r['fresh_parser']} | {r['img']} |"
        )
    md_lines += [
        "",
        "## Manual review protocol",
        "",
        "1. Open the image (`cards/<pcid>_<pid>.jpg`).",
        "2. Read the top-right DECEASED stamp. Note year (and month/day if shown).",
        "3. Compare to `claimed (year/iso)`.",
        "4. Mark each row in `manifest.json` with `review_verdict`:",
        "   - `pass` — claimed year matches the stamp",
        "   - `fail_year` — different year (record the correct one in `corrected_year`)",
        "   - `fail_parser` — date is on the card but the regex missed it (record in `corrected_iso`)",
        "   - `no_date_on_card` — card genuinely has no death date (confirms skip is correct)",
        "   - `uncertain` — can't tell from this scan quality",
        "",
        "Aggregate verdicts feed a follow-up issue. Do NOT auto-merge — the parser's",
        "precision is load-bearing for FaG matching.",
        "",
    ]
    (out_dir / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    log.info("done. %d records → %s", len(sample), out_dir)
    log.info("open %s/summary.md to start review", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
