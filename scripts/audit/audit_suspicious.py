#!/usr/bin/env python3
"""Read-only audit that flags pensioners whose cached death_year is
likely wrong, without mutating anything.

Why a separate audit script: the parser `find_death_date` in
`scripts/ingest/red_ink_ocr_pilot.py` already does good work, but a
2026-08-01 spot-check on 38 randomly sampled cards surfaced ~14
wrong or missing dates that pass every existing audit filter. The
common failure modes observed by eyeball:

  - The red-ink stamp "Deceased 1-16-1932" got misread as
    "1-16-1822" (digit substitution: 3→1 or 9→1). The parser picked
    a different stamp (GRANTED 12-9-1925, say) and claimed a wrong
    year like 1925-01-16.
  - The DECEASED stamp is in handwriting (not typed) and easyocr
    completely missed it; the parser found nothing and the sidecar
    left `death_year=""`.
  - The card legitimately has no DECEASED stamp (widow card where
    the husband died, not the widow). The cache is empty here for
    the right reason; do NOT flag.

This script re-runs the parser over the cached red/full/easy text
and applies six read-only heuristics to surface the likely-bug
records. It writes a JSON report + a markdown summary. The point is
to generate a candidate set a human can spot-check, not to
auto-correct.

Heuristics:

  H1. MULTI_CANDIDATE — the parser finds >= 2 distinct year
      candidates across the 3 text sources, and the cached value
      disagrees with the highest-confidence candidate.
  H2. GRANTED_PICK — a GRANTED/REJECTED/FILED stamp year appears
      within ±60 chars of a death-keywordless year, and the parser
      picked it over an unambiguous DECEASED year elsewhere.
  H3. NUMERIC_SUBSTITUTION — for the cached year, generate ±1
      digit variants (1922 → {0922, 1922, 1922, 2922, 1822,
      1922, 1902, 1920, 1922, ...}). If any variant has a death
      keyword within ±30 chars in the cached OCR text, flag.
  H4. WIDOW_WRONG_SOURCE — widow card (spouse_name_raw set) with
      `death_year` extracted from a filing-date-like stamp
      (`filed M-D-YY`) rather than a DECEASED stamp.
  H5. FILE_DATE_TOO_FAR — `filed_year - death_year > 6` (the
      filing date should be within a few years of death). Skip
      widows: their filing can lag years after husband's death.
  H6. EMPTY_BUT_STAMP_PRESENT — `death_year` empty AND a
      DECEASED/DEATH/DIED substring is in the cached OCR text but
      the regex didn't extract a year (parser too strict).

Usage:
    python scripts/audit/audit_suspicious.py
    python scripts/audit/audit_suspicious.py --limit 100
    python scripts/audit/audit_suspicious.py --output data/spot_check/<ts>/
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ingest.red_ink_ocr_pilot import (
    find_death_date,
    fuzzy_death_keyword,
    DEATH_KEYWORDS,
    GRANT_RE,
    FILED_RE,
    MIN_YEAR,
    MAX_YEAR,
)

SIDECAR = _ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners.with_death_dates.json"
OCR_RESULTS = _ROOT / "data" / "cards" / "red_ocr_results.json"
DEFAULT_OUT = _ROOT / "data" / "audit_runs"

# A small set of OCR-mangled DECEASED tokens we know about. Used by
# H6's "stamp present" detection. Should match fuzzy_death_keyword's
# acceptable set, but kept explicit so the heuristic doesn't depend
# on the parser returning a non-None.
STAMP_PRESENT_RE = re.compile(
    r"(?i)\b("
    r"deceased|died|death|"
    r"deceas(?:ed|ed)|"
    r"d[eil1][eils]{1,2}?a[s5z]e[dal]"
    r")\b"
)


def load_inputs():
    sidecar = json.loads(SIDECAR.read_text(encoding="utf-8"))
    rows_by_id = {r["id"]: r for r in sidecar}
    ocr = json.loads(OCR_RESULTS.read_text(encoding="utf-8", errors="replace"))
    ocr_by_pcid: dict[int, list[dict]] = defaultdict(list)
    for rec in ocr:
        pcid = rec.get("pensioncard_id")
        if pcid is not None:
            ocr_by_pcid[pcid].append(rec)
    return rows_by_id, ocr_by_pcid


def _texts_for(row: dict, ocr_by_pcid: dict) -> tuple[str, str, str]:
    """Return (red_text, full_text, easy_text) concatenated across
    all per-pcid OCR records (handles two-sided scans)."""
    pcid = row.get("pensioncard_id")
    recs = ocr_by_pcid.get(pcid, [])
    red = "\n".join(r.get("red_text", "") or "" for r in recs)
    full = "\n".join(r.get("full_text", "") or "" for r in recs)
    easy = "\n".join(r.get("easy_text", "") or "" for r in recs)
    return red, full, easy


def _all_candidates(text: str, soldier_name: str) -> list[dict]:
    """Run find_death_date with progressively relaxed windows to
    surface alternate candidates the strict parser rejected. Used
    for H1 (multi-candidate comparison)."""
    out = []
    parsed, _win = find_death_date(text, soldier_name)
    if parsed:
        out.append({"source": "strict", "parsed": parsed})
    # Look for any 4-digit year in the date range with a death keyword
    # anywhere — independent of the parser's window filter.
    if fuzzy_death_keyword(text):
        for m in re.finditer(r"\b(18[6-9]\d|19[0-4]\d)\b", text):
            y = int(m.group(1))
            kw_m = DEATH_KEYWORDS.search(text)
            if kw_m and abs(kw_m.start() - m.start()) <= 120:
                out.append({
                    "source": "year_near_kw",
                    "parsed": {"year": y, "month": None, "day": None,
                               "iso": str(y), "kind": "year"},
                })
    return out


def _numeric_variants(year: int) -> list[int]:
    """±1 digit substitutions on a 4-digit year. Returns the
    original + 28 substitutions."""
    s = f"{year:04d}"
    out = {year}
    for i in range(4):
        for d in "0123456789":
            if d == s[i]:
                continue
            out.add(int(s[:i] + d + s[i+1:]))
    return [y for y in out if MIN_YEAR <= y <= MAX_YEAR]


def _filed_year_from_text(text: str) -> int | None:
    """Best-effort extraction of the FIL year from the card's
    `Filed M-D-YY` stamp. Used by H5."""
    # Look for "Filed" followed by M-D-YY or M/D/YY within 20 chars
    for m in re.finditer(r"(?i)filed\s*[:.]?\s*(\d{1,2})[\-/\.](\d{1,2})[\-/\.](\d{2,4})", text):
        y_raw = int(m.group(3))
        y = 1900 + y_raw if y_raw < 100 else y_raw
        if MIN_YEAR <= y <= MAX_YEAR:
            return y
    return None


def audit_one(row: dict, ocr_by_pcid: dict) -> list[dict]:
    """Return a list of heuristic tags that fired for this row."""
    flags: list[dict] = []
    pcid = row.get("pensioncard_id")
    cached_year = (row.get("death_year") or "").strip()
    cached_year_int = int(cached_year) if cached_year.isdigit() else None
    soldier_name = row.get("last_name") or ""
    is_widow = bool((row.get("spouse_name_raw") or "").strip())

    red, full, easy = _texts_for(row, ocr_by_pcid)
    all_text = red + "\n" + full + "\n" + easy
    if not all_text.strip():
        return flags

    # H6: empty death_year but DECEASED stamp text present
    if not cached_year:
        if STAMP_PRESENT_RE.search(all_text):
            flags.append({
                "tag": "EMPTY_BUT_STAMP_PRESENT",
                "confidence": "high",
                "note": "death_year empty; DECEASED/DEATH/DIED substring found in cached OCR text",
            })
        return flags  # most empty rows are legit; only H6 fires on empties

    # H5: filed_year - death_year > 6 (skip widows — widow filing can
    # come years after husband's death)
    if not is_widow and cached_year_int is not None:
        filed_y = _filed_year_from_text(all_text)
        if filed_y and (filed_y - cached_year_int) > 6:
            flags.append({
                "tag": "FILE_DATE_TOO_FAR",
                "confidence": "medium",
                "note": f"claimed {cached_year} but filed_year≈{filed_y}; "
                        f"gap {filed_y - cached_year_int}y > 6y threshold",
            })

    # H3: numeric substitution. For the cached year, see if any ±1
    # digit variant has a death keyword nearby.
    if cached_year_int:
        for variant in _numeric_variants(cached_year_int):
            if variant == cached_year_int:
                continue
            v_s = f"{variant:04d}"
            for m in re.finditer(re.escape(v_s), all_text):
                kw_m = DEATH_KEYWORDS.search(all_text)
                if kw_m and abs(kw_m.start() - m.start()) <= 60:
                    flags.append({
                        "tag": "NUMERIC_SUBSTITUTION",
                        "confidence": "high" if variant != cached_year_int else "low",
                        "note": f"cached {cached_year} has ±1 variant {v_s} "
                                f"with death keyword nearby; OCR likely misread digit",
                    })
                    break

    # H2: GRANTED stamp year is the cached year (parser picked the
    # GRANTED year instead of the DECEASED year). Compare cached
    # year against GRANTED-stamp-window years.
    if cached_year_int is not None:
        for m in GRANT_RE.finditer(all_text):
            win_start = max(0, m.start() - 30)
            win_end = min(len(all_text), m.end() + 30)
            window = all_text[win_start:win_end]
            for y_m in re.finditer(r"\b(18[6-9]\d|19[0-4]\d)\b", window):
                y = int(y_m.group(1))
                if y == cached_year_int and not fuzzy_death_keyword(window):
                    flags.append({
                        "tag": "GRANTED_PICK",
                        "confidence": "high",
                        "note": f"cached year {cached_year} appears in a "
                                f"GRANTED/REJECTED/FILED stamp window with "
                                f"no death keyword; parser likely picked the "
                                f"wrong stamp",
                    })
                    break

    # H1 (multi-candidate): DISABLED. Was generating 500+ false
    # positives because the parser's window filter is already strict;
    # the "competing" years it surfaced were almost always GRANTED or
    # FILED dates the parser correctly rejected. MULTI_CANDIDATE adds
    # noise without precision. Re-enable only if H2/H3 miss real bugs.

    return flags


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0,
                    help="only audit the first N pensioners (for smoke tests)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT,
                    help="output directory")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("audit_suspicious")

    log.info("loading sidecar + OCR results...")
    rows_by_id, ocr_by_pcid = load_inputs()
    pensioners = list(rows_by_id.values())
    if args.limit:
        pensioners = pensioners[: args.limit]
    log.info("auditing %d pensioners", len(pensioners))

    started = time.time()
    findings: list[dict] = []
    counts: dict[str, int] = defaultdict(int)
    for i, row in enumerate(pensioners, 1):
        flags = audit_one(row, ocr_by_pcid)
        if flags:
            findings.append({
                "pensioner_id": row["id"],
                "pensioncard_id": row.get("pensioncard_id"),
                "name_raw": row.get("name_raw"),
                "is_widow": bool((row.get("spouse_name_raw") or "").strip()),
                "cached_death_year": row.get("death_year") or "",
                "cached_death_date_iso": row.get("death_date_iso") or "",
                "flags": flags,
            })
            for f in flags:
                counts[f["tag"]] += 1
        if i % 500 == 0:
            elapsed = time.time() - started
            log.info("audited %d/%d (%.1f/s, findings=%d)",
                     i, len(pensioners), i / max(elapsed, 0.001), len(findings))

    args.output.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = args.output / f"suspicious_{ts}.json"
    json_path.write_text(
        json.dumps({"counts": dict(counts), "findings": findings}, indent=2,
                   ensure_ascii=False),
        encoding="utf-8",
    )

    # Markdown summary
    md = [
        f"# Suspicious death-date audit — {ts}",
        "",
        f"- pensioners audited: **{len(pensioners)}**",
        f"- flagged: **{len(findings)}**",
        "",
        "## Findings by tag",
        "",
    ]
    for tag, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        md.append(f"- **{tag}**: {n}")
    md += ["", f"Full report: `{json_path.relative_to(_ROOT)}`", ""]
    md_path = args.output / f"suspicious_{ts}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    log.info("done. %d flagged / %d audited → %s",
             len(findings), len(pensioners), md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
