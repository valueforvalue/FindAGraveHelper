#!/usr/bin/env python3
"""Death-date extraction discrepancy audit.

Cross-references three data sources to surface suspicious death-date
extractions:

  * ok_pensioners.with_death_dates.json    — the merged sidecar
  * data/cards/enrichment_report.json      — enriched + their source_pass
  * data/cards/red_ocr_results.json        — raw OCR output per image

Produces:
  - audit_report.json     — full machine-readable findings
  - audit_report.md       — human-readable summary table

Findings categories (each tagged, deduped, ranked):

  1. OUT_OF_RANGE_YEAR       — death year < 1865 (Civil War end) or > 1955
                                (any pensioners surely dead by then given the
                                pension ran 1910s–1950s).
  2. YEAR_LATER_THAN_PENSION  — death year > 1955 or beyond reasonable
                                coverage (cards stop ~1950s).
  3. ISO_YEAR_MISMATCH        — death_year != int(death_date_iso[:4]).
  4. FULL_DATE_BUT_YEAR_ONLY  — death_date_iso is bare 4-digit year but
                                red_text contains a month/day pattern.
  5. NO_KEYWORD_BUT_DATE      — date extracted but near_death_keyword
                                is False AND mentions_soldier_name False
                                AND no widow → extraction came from a
                                non-death-context. Likely wrong field
                                (rejected dates, filing dates, etc.).
  6. WIDOW_BUT_NO_DATE        — is_widow_card True but no death date
                                (most widows had death dates extracted,
                                missing one is suspicious).
  7. CONFLICTING_DATES        — death_date_iso has month/day that
                                disagrees with another extracted date
                                in OCR results for the same image.
  8. PASS_RED_BUT_LOW_TEXT    — source_pass='red' but red_text is empty
                                or has no number-like tokens.
  9. DUPLICATE_PENSIONER_ID   — same pensioner_id appears multiple times
                                with different dates.
 10. SUSPECT_MONTH_DAY        — month out of [1,12] or day out of
                                [1,31]; or Feb 30 etc.

Usage:
    python scripts/audit/audit_death_dates.py
    python scripts/audit/audit_death_dates.py --strict  # fail on any finding
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any findings (for CI gating)")
    ap.add_argument("--enriched", type=Path, default=None,
                    help="path to ok_pensioners.with_death_dates.json "
                         "(default: docs/research/digitalprairie/)")
    ap.add_argument("--enrichment", type=Path, default=None,
                    help="path to data/cards/enrichment_report.json")
    ap.add_argument("--ocr", type=Path, default=None,
                    help="path to data/cards/red_ocr_results.json")
    ap.add_argument("--out-json", type=Path, default=None,
                    help="output JSON path (default: "
                         "data/audit_death_dates_report.json)")
    ap.add_argument("--out-md", type=Path, default=None,
                    help="output markdown path (default: "
                         "data/audit_death_dates_report.md)")
    args = ap.parse_args(argv)

    base = _ROOT / "data"
    docs = _ROOT / "docs" / "research" / "digitalprairie"

    enriched_path = args.enriched or (docs / "ok_pensioners.with_death_dates.json")
    enrichment_path = args.enrichment or (base / "cards" / "enrichment_report.json")
    ocr_path = args.ocr or (base / "cards" / "red_ocr_results.json")
    out_json = args.out_json or (_ROOT / "data" / "audit_death_dates_report.json")
    out_md = args.out_md or (_ROOT / "data" / "audit_death_dates_report.md")

    print(f"loading {enriched_path.name}...", file=sys.stderr)
    enriched = load_json(enriched_path)
    print(f"loading {enrichment_path.name}...", file=sys.stderr)
    enrichment = load_json(enrichment_path)
    print(f"loading {ocr_path.name}...", file=sys.stderr)
    ocr = load_json(ocr_path)

    enriched_by_id = {r["id"]: r for r in enriched if "id" in r}
    enrichment_records = list(enriched)
    enrichment_by_id = enriched_by_id
    ocr_by_pcid = defaultdict(list)
    for rec in ocr:
        pcid = rec.get("pensioncard_id")
        if pcid is not None:
            ocr_by_pcid[pcid].append(rec)

    findings: list[dict] = []

    # ---- Pass 1: per-pensioner audit (sidecar is authoritative) ----
    for enr in enrichment_records:
        pid = enr.get("id")
        pcid = enr.get("pensioncard_id")
        year_raw = enr.get("death_year", "") or ""
        iso_raw = enr.get("death_date_iso", "") or ""
        # widow = has non-empty spouse name (matches build_pensioncard_viewer)
        is_widow = bool((enr.get("spouse_name_raw") or "").strip())
        name = enr.get("name_raw", "")
        # Cross-reference OCR for the death-keyword / source_pass flags
        ocr_recs = ocr_by_pcid.get(pcid, []) if pcid is not None else []
        # union: any image with a keyword. Issue #139 follow-up
        # (2026-07-31): the re-enrich driver now writes the
        # near_death_keyword flag INSIDE death_date (matching
        # process_image's schema), not at the top level of the
        # OCR record. Read from both locations for backward
        # compatibility with older records that pre-date the
        # schema change.
        has_kw = any(
            r.get("near_death_keyword")
            or (r.get("death_date") or {}).get("near_death_keyword")
            for r in ocr_recs
        )
        # source_pass = the pass that produced the final date for this pcid
        passes = [r.get("source_pass") for r in ocr_recs if r.get("source_pass")]
        source_pass = passes[0] if passes else None
        if any(p == "red" for p in passes):
            source_pass = "red"
        elif any(p == "full-fallback" for p in passes):
            source_pass = "full-fallback"

        try:
            year = int(year_raw) if year_raw else None
        except ValueError:
            year = None
            findings.append({
                "tag": "NON_NUMERIC_YEAR",
                "pensioner_id": pid,
                "pensioncard_id": pcid,
                "name": name,
                "death_year": year_raw,
                "death_date_iso": iso_raw,
                "is_widow": is_widow,
                "source_pass": source_pass,
                "note": "death_year is not an integer",
            })

        # 1: out-of-range
        if year is not None:
            if year < 1861:
                findings.append({
                    "tag": "OUT_OF_RANGE_YEAR",
                    "pensioner_id": pid,
                    "pensioncard_id": pcid,
                    "name": name,
                    "death_year": year,
                    "death_date_iso": iso_raw,
                    "is_widow": is_widow,
                    "source_pass": source_pass,
                    "note": f"year {year} predates Civil War start (1861)",
                })
            if year > 1955:
                findings.append({
                    "tag": "OUT_OF_RANGE_YEAR",
                    "pensioner_id": pid,
                    "pensioncard_id": pcid,
                    "name": name,
                    "death_year": year,
                    "death_date_iso": iso_raw,
                    "is_widow": is_widow,
                    "source_pass": source_pass,
                    "note": f"year {year} is implausibly late "
                            "(pension coverage ended ~1950s)",
                })

        # 3: iso/year mismatch
        if year is not None and iso_raw and re.match(r"^\d{4}", iso_raw):
            try:
                iso_year = int(iso_raw[:4])
            except ValueError:
                iso_year = None
            if iso_year and iso_year != year:
                findings.append({
                    "tag": "ISO_YEAR_MISMATCH",
                    "pensioner_id": pid,
                    "pensioncard_id": pcid,
                    "name": name,
                    "death_year": year,
                    "death_date_iso": iso_raw,
                    "is_widow": is_widow,
                    "source_pass": source_pass,
                    "note": f"death_year={year} but iso starts with {iso_year}",
                })

        # 5: date without keyword + not widow + no soldier mention
        if (year is not None and not has_kw
                and not enr.get("mentions_soldier_name", False)
                and not is_widow):
            findings.append({
                "tag": "NO_KEYWORD_BUT_DATE",
                "pensioner_id": pid,
                "pensioncard_id": pcid,
                "name": name,
                "death_year": year,
                "death_date_iso": iso_raw,
                "is_widow": is_widow,
                "source_pass": source_pass,
                "note": "date extracted but no death-keyword, "
                        "no widow card, no soldier-name mention — "
                        "possibly mis-extracted (rejected/filing date?)",
            })

        # 6: widow with no date
        if is_widow and not year:
            findings.append({
                "tag": "WIDOW_BUT_NO_DATE",
                "pensioner_id": pid,
                "pensioncard_id": pcid,
                "name": name,
                "death_year": "",
                "death_date_iso": "",
                "is_widow": True,
                "source_pass": source_pass,
                "note": "widow card but no death date extracted",
            })

        # 10: month/day sanity on ISO
        m = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$", iso_raw or "")
        if m and (m.group(2) or m.group(3)):
            try:
                mo = int(m.group(2)) if m.group(2) else None
                dy = int(m.group(3)) if m.group(3) else None
            except ValueError:
                mo = dy = None
            bad = False
            note = ""
            if mo is not None and not 1 <= mo <= 12:
                bad = True
                note = f"month {mo} out of range"
            elif dy is not None:
                if not 1 <= dy <= 31:
                    bad = True
                    note = f"day {dy} out of range"
                elif mo in (4, 6, 9, 11) and dy > 30:
                    bad = True
                    note = f"day {dy} invalid for month {mo}"
                elif mo == 2 and dy > 29:
                    bad = True
                    note = f"day {dy} invalid for Feb"
            if bad:
                findings.append({
                    "tag": "SUSPECT_MONTH_DAY",
                    "pensioner_id": pid,
                    "pensioncard_id": pcid,
                    "name": name,
                    "death_year": year,
                    "death_date_iso": iso_raw,
                    "is_widow": is_widow,
                    "source_pass": source_pass,
                    "note": note,
                })

        # 8: red source pass but no red text
        if source_pass == "red" and pcid is not None:
            ocr_recs = ocr_by_pcid.get(pcid, [])
            if not ocr_recs:
                findings.append({
                    "tag": "PASS_RED_BUT_NO_OCR",
                    "pensioner_id": pid,
                    "pensioncard_id": pcid,
                    "name": name,
                    "death_year": year,
                    "death_date_iso": iso_raw,
                    "is_widow": is_widow,
                    "source_pass": source_pass,
                    "note": "marked source_pass=red but no OCR result found",
                })
            else:
                red_texts = [r.get("red_text", "") for r in ocr_recs]
                if not any(red_texts):
                    findings.append({
                        "tag": "PASS_RED_BUT_EMPTY_TEXT",
                        "pensioner_id": pid,
                        "pensioncard_id": pcid,
                        "name": name,
                        "death_year": year,
                        "death_date_iso": iso_raw,
                        "is_widow": is_widow,
                        "source_pass": source_pass,
                        "note": "marked red but every image had empty red_text",
                    })

        # 4: full text has month/day pattern but iso only has year
        if pcid is not None and year is not None and iso_raw:
            iso_full = re.match(r"^\d{4}-\d{2}-\d{2}$", iso_raw)
            if not iso_full:
                # iso is bare year — check if OCR text had a clearer pattern
                for rec in ocr_by_pcid.get(pcid, []):
                    ft = rec.get("full_text", "") or ""
                    if re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}\b",
                                 ft, re.IGNORECASE):
                        findings.append({
                            "tag": "FULL_DATE_BUT_YEAR_ONLY",
                            "pensioner_id": pid,
                            "pensioncard_id": pcid,
                            "name": name,
                            "death_year": year,
                            "death_date_iso": iso_raw,
                            "is_widow": is_widow,
                            "source_pass": source_pass,
                            "note": "OCR text has month/day/year pattern "
                                    "but date_iso is bare year",
                        })
                        break

    # ---- Pass 2: enriched sidecar — look for orphans / disagreements ----
    for r in enriched:
        pid = r.get("id")
        if pid in enrichment_by_id:
            enr = enrichment_by_id[pid]
            if r.get("death_year") and enr.get("death_year"):
                if str(r["death_year"]) != str(enr["death_year"]):
                    findings.append({
                        "tag": "DUPLICATE_PENSIONER_DATE_CONFLICT",
                        "pensioner_id": pid,
                        "pensioncard_id": r.get("pensioncard_id"),
                        "name": r.get("name_raw", ""),
                        "death_year": enr["death_year"],
                        "death_date_iso": enr.get("death_date_iso", ""),
                        "is_widow": enr.get("is_widow_card", False),
                        "source_pass": enr.get("source_pass"),
                        "note": f"sidecar says {r.get('death_year')}, "
                                f"enrichment_report says {enr['death_year']}",
                    })

    # ---- Pass 3: duplicate pensioner_ids in enrichment_report ----
    pids_in_enrichment = [r.get("id") for r in enrichment_records]
    dupes = [pid for pid, n in Counter(pids_in_enrichment).items() if n > 1]
    for pid in dupes:
        recs = [r for r in enrichment_records if r.get("id") == pid]
        dates = [(r.get("death_year"), r.get("death_date_iso")) for r in recs]
        findings.append({
            "tag": "DUPLICATE_PENSIONER_ID",
            "pensioner_id": pid,
            "pensioncard_id": None,
            "name": "",
            "death_year": "",
            "death_date_iso": "",
            "is_widow": False,
            "source_pass": None,
            "note": f"appears {len(recs)}x with dates {dates}",
        })

    # ---- Pass 4: pensioncard_id shared by multiple pensioners ----
    pcid_to_pids = defaultdict(set)
    for r in enrichment_records:
        pcid = r.get("pensioncard_id")
        if pcid is not None:
            pcid_to_pids[pcid].add(r.get("id"))
    for pcid, ids in pcid_to_pids.items():
        if len(ids) > 1:
            findings.append({
                "tag": "DUPLICATE_PENSIONCARD_ID",
                "pensioner_id": sorted(ids)[0],
                "pensioncard_id": pcid,
                "name": "",
                "death_year": "",
                "death_date_iso": "",
                "is_widow": False,
                "source_pass": None,
                "note": f"pensioncard_id={pcid} shared by pensioner_ids {sorted(ids)}",
            })

    # ---- Summarize ----
    by_tag = Counter(f["tag"] for f in findings)
    by_year = Counter()
    for f in findings:
        if f.get("death_year") not in (None, ""):
            try:
                by_year[int(f["death_year"])] += 1
            except (ValueError, TypeError):
                pass

    summary = {
        "total_enrichment_records": len(enrichment_records),
        "total_enriched_pensioners": len(enriched_by_id),
        "total_findings": len(findings),
        "by_tag": dict(by_tag.most_common()),
        "by_year_top": dict(by_year.most_common(20)),
        "earliest_year_seen": min((int(f["death_year"]) for f in findings
                                   if str(f.get("death_year", "")).isdigit()),
                                  default=None),
        "latest_year_seen": max((int(f["death_year"]) for f in findings
                                 if str(f.get("death_year", "")).isdigit()),
                                default=None),
    }
    print(json.dumps(summary, indent=2))

    out_json.write_text(json.dumps({"summary": summary, "findings": findings},
                                   indent=2),
                        encoding="utf-8")

    # Markdown
    md = ["# Death-Date Extraction Audit\n"]
    md.append(f"- enrichment records: {summary['total_enrichment_records']}")
    md.append(f"- pensioners (enriched sidecar): {summary['total_enriched_pensioners']}")
    md.append(f"- total findings: {summary['total_findings']}\n")
    md.append("## Findings by tag\n")
    for tag, n in by_tag.most_common():
        md.append(f"- **{tag}**: {n}")
    md.append(f"\n## Year range seen in findings: "
              f"{summary['earliest_year_seen']} \u2192 {summary['latest_year_seen']}\n")
    md.append("## First 50 findings\n")
    md.append("| Tag | Pensioner ID | Name | Year | ISO | Wid | Pass | Note |")
    md.append("|---|---|---|---|---|---|---|---|")
    for f in findings[:50]:
        md.append("| {tag} | {pid} | {name} | {yr} | {iso} | {w} | {sp} | {note} |".format(
            tag=f["tag"],
            pid=f.get("pensioner_id", ""),
            name=(f.get("name") or "")[:30],
            yr=f.get("death_year", ""),
            iso=(f.get("death_date_iso") or "")[:10],
            w="Y" if f.get("is_widow") else "",
            sp=f.get("source_pass") or "",
            note=(f.get("note") or "")[:60],
        ))
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {out_json}", file=sys.stderr)
    print(f"wrote {out_md}", file=sys.stderr)

    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())