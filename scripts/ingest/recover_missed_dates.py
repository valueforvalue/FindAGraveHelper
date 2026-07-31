"""Recovery pass for L3 EasyOCR missed death dates.

Issue #143. After the L3 EasyOCR run completed (commit 9e85f53),
4163 records had `easy_text` set but no `death_date` extracted.
The strict `find_death_date` parser rejected these because
EasyOCR's per-character noise produced date patterns outside
the strict grammar (trailing digits, missing days, etc).

This module is a CANDIDATE GENERATOR. It scans each missed
record's easy_text for date patterns, applies the L3 anti-keyword
guards (GRANTED / FILED / REJECTED / address change) within a
±60-char window, and emits candidates with confidence scores.
A human review pass writes the accepted ones back as
`death_date` with source_pass='easyocr_recovered_v1'.

Design notes:
  - Independent of find_death_date. Doesn't touch the pinned
    17% that the strict version gets right. Tests in
    tests/test_recover_missed_dates.py are independent.
  - Confidence is in [0, 1]. 0.7+ = high, 0.4-0.7 = review,
    <0.4 = probably noise.
  - The L3 anti-keyword regexes are reused from
    red_ink_ocr_pilot.py so the false-positive profile matches
    the prior L3 work.

Usage::

    # Generate candidates (read-only).
    python scripts/ingest/recover_missed_dates.py \\
        --input data/cards/red_ocr_results.json \\
        --output data/easyocr_runs/recovery_candidates.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ingest import red_ink_ocr_pilot as pilot  

MIN_YEAR = pilot.MIN_YEAR
MAX_YEAR = pilot.MAX_YEAR

# Reuse the L3 anti-keyword regexes.
DEATH_KW = pilot.DEATH_KEYWORDS
GRANT_RE = pilot.GRANT_RE
FILED_RE = pilot.FILED_RE
REJECTED_RE = re.compile(r"(?i)\brejected\b")
ADDR_CHANGE_RE = re.compile(
    r"(?i)\b(gives\b|gives:|changed\b|changed\s+from|"
    r"o\s*/\s*c\b|o\.\s*c\.\b|"
    r"temp\.?\s+ad(?:dress)?\b|"
    r"post\s+card\b|"
    r"a/?c\s+|gc\s+|oy\s+|qc\s+|aw\s+)\s*[\d/.\-]+"
)
ADDR_CHANGE_TRAILING = re.compile(
    r"(?i)\b(changed\s+from|changed\s+to|gives|"
    r"o\s*/\s*c\b|o\.\s*c\.|temp\.?\s+add?ress?|"
    r"post\s+card)\b"
)
LETTER_DATE_RE = pilot.LETTER_DATE_RE
WAR_END_RE = pilot.WAR_END_RE
MARRIED_RE = pilot.MARRIED_RE
CAME_TO_RE = pilot.CAME_TO_RE

WINDOW_PAD = 60

# Pattern families. Each entry is (regex, confidence_with_kw,
# confidence_no_kw, reasoning_tag, kind).
#   kind in {"date", "year-only"}.
#   The patterns are intentionally narrow. The strict parser
#   already handles clean M-D-YYYY; these target the SHAPE
#   variants the strict parser rejected.

PATTERNS = [
    
    (re.compile(
        r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b"
     ), 0.85, 0.55, "strict_mdY", "date"),

    
    (re.compile(
        r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2})\b"
     ), 0.75, 0.5, "2digit_year", "date"),

    
    (re.compile(
        r"\b(\d{1,2})[-/](\d{1,2})\s+(\d{4})\b"
     ), 0.7, 0.45, "space_before_year", "date"),

    
    (re.compile(
        r"\b(\d{1,2})[-/](\d{3})[-/](\d{4})\b"
     ), 0.6, 0.4, "3digit_day_field", "date"),

    
    (re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\w*[\.,]?\s+(\d{1,2})[\.,]?\s+(\d{2,4})\b",
        re.IGNORECASE
     ), 0.8, 0.55, "mon_day_year", "date"),

    
    (re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\w*[\.,]?\s+(\d{1,2})\s*/\s*(\d{2})\b",
        re.IGNORECASE
     ), 0.65, 0.45, "mon_day_2digit_slash", "date"),

    
    (re.compile(r"\b(18[6-9]\d|19[0-5]\d)\b"),
     0.4, 0.2, "year_only", "year-only"),
]


def _two_digit_year(y: int) -> int:
    return 1900 + y


def _is_valid(month: int, day: int, year: int) -> bool:
    if not (1 <= month <= 12):
        return False
    if not (1 <= day <= 31):
        return False
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return False
    if month in (4, 6, 9, 11) and day > 30:
        return False
    if month == 2 and day > 29:
        return False
    return True


def _year_only_in_range(year: int) -> bool:
    return MIN_YEAR <= year <= MAX_YEAR


def _has_death_keyword(text: str) -> bool:
    return bool(DEATH_KW.search(text))


def _anti_keyword_hits(window: str) -> list[str]:
    """Anti-keyword categories in window. If a death keyword is
    also in the window, the L2 lesson is: anti-keywords must
    NOT suppress the candidate (death context wins)."""
    if _has_death_keyword(window):
        return []
    hits = []
    if GRANT_RE.search(window):
        hits.append("GRANTED")
    if REJECTED_RE.search(window):
        hits.append("REJECTED")
    if FILED_RE.search(window):
        hits.append("FILED")
    if ADDR_CHANGE_RE.search(window) or ADDR_CHANGE_TRAILING.search(window):
        hits.append("ADDR_CHANGE")
    if LETTER_DATE_RE.search(window):
        hits.append("LETTER_DATE")
    if MARRIED_RE.search(window):
        hits.append("MARRIED")
    if CAME_TO_RE.search(window):
        hits.append("CAME_TO")
    return hits


@dataclass
class Candidate:
    text: str
    match: str
    year: int
    month: int | None
    day: int | None
    iso: str
    confidence: float
    reasoning: list[str] = field(default_factory=list)
    span: tuple[int, int] = (0, 0)
    anti_keywords_in_window: list[str] = field(default_factory=list)
    has_death_keyword: bool = False
    kind: str = "date"

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "match": self.match,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "iso": self.iso,
            "kind": self.kind,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "span": list(self.span),
            "anti_keywords_in_window": self.anti_keywords_in_window,
            "has_death_keyword": self.has_death_keyword,
        }


def extract_candidates(text: str) -> list[Candidate]:
    """Generate date candidates from a chunk of text. Sorted
    by confidence desc."""
    if not text:
        return []
    has_kw = _has_death_keyword(text)
    cands: list[Candidate] = []

    for pat, conf_kw, conf_no_kw, tag, kind in PATTERNS:
        for m in pat.finditer(text):
            try:
                ms, me = m.span()
                window = text[max(0, ms - WINDOW_PAD): min(len(text), me + WINDOW_PAD)]
                anti_kw = _anti_keyword_hits(window)
                if anti_kw and not _has_death_keyword(window):
                    continue

                if kind == "year-only":
                    year = int(m.group(1))
                    if not _year_only_in_range(year):
                        continue
                    iso = f"{year:04d}"
                    month = None
                    day = None
                else:
                    groups = m.groups()
                    if groups[0].isalpha():
                        month = pilot._month_to_int(groups[0])
                        day = int(groups[1])
                        y = int(groups[2])
                    else:
                        month = int(groups[0])
                        day = int(groups[1])
                        y = int(groups[2])
                    year = _two_digit_year(y) if y < 100 else y
                    
                    if not (1 <= month <= 12):
                        continue
                    if not (MIN_YEAR <= year <= MAX_YEAR):
                        continue
                    
                    if day > 31 and tag == "3digit_day_field":
                        
                        pass
                    elif not (1 <= day <= 31):
                        continue
                    iso = f"{year:04d}-{month:02d}-{day:02d}"

                reasoning = [tag]
                if has_kw:
                    reasoning.append("death_keyword_in_window")
                if y < 100 if kind != "year-only" else False:
                    reasoning.append("2digit_year_assumed_19xx")

                cands.append(Candidate(
                    text=text, match=m.group(0),
                    year=year, month=month, day=day, iso=iso,
                    confidence=(conf_kw if has_kw else conf_no_kw),
                    reasoning=reasoning, span=(ms, me),
                    anti_keywords_in_window=anti_kw,
                    has_death_keyword=has_kw, kind=kind,
                ))
            except (ValueError, TypeError, AttributeError):
                continue

    seen: set[str] = set()
    unique: list[Candidate] = []
    for c in cands:
        if c.iso not in seen:
            seen.add(c.iso)
            unique.append(c)
    unique.sort(key=lambda c: (-c.confidence, -c.year))
    return unique[:5]


def process_record(rec: dict) -> list[Candidate]:
    """Generate candidates for one red_ocr_results record.
    Skips records that already have a death_date or are
    missing easy_text."""
    if rec.get("death_date"):
        return []
    easy_text = rec.get("easy_text")
    if not easy_text:
        return []
    text = easy_text
    if rec.get("red_text"):
        text = text + " " + rec["red_text"]
    return extract_candidates(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path,
                    default=Path("data/cards/red_ocr_results.json"))
    ap.add_argument("--output", type=Path,
                    default=Path("data/easyocr_runs/recovery_candidates.json"))
    ap.add_argument("--min-confidence", type=float, default=0.4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    rows = json.loads(args.input.read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[: args.limit]

    out: list[dict] = []
    counts = {"scanned": 0, "with_candidate": 0,
              "high_conf": 0, "review": 0, "low_conf": 0}
    for r in rows:
        counts["scanned"] += 1
        cands = process_record(r)
        cands = [c for c in cands if c.confidence >= args.min_confidence]
        if not cands:
            continue
        counts["with_candidate"] += 1
        for c in cands:
            if c.confidence >= 0.7:
                counts["high_conf"] += 1
            elif c.confidence >= 0.4:
                counts["review"] += 1
            else:
                counts["low_conf"] += 1
        out.append({
            "pensioncard_id": r.get("pensioncard_id"),
            "image": r.get("image"),
            "candidates": [c.to_dict() for c in cands],
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "min_confidence": args.min_confidence,
        "counts": counts,
        "records": out,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(counts, indent=2))
    print(f"wrote {len(out)} record-candidate-sets to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
