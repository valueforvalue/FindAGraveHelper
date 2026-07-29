"""OCR pension card images and extract death dates from red ink.

For each image downloaded by :mod:`scripts.ingest.download_pensioncard_images`,
this script:
1. Builds a red-ink mask: keep pixels where R > G + B AND R > 100.
   Output: a grayscale image where red ink is black and everything
   else is white.
2. OCR pass A: Tesseract on the red-masked image.
3. If pass A yielded no candidate death date, OCR pass B:
   Tesseract on the full card image as fallback.
4. Parse OCR text for death/death-adjacent phrases and bare dates.
5. Write one row per image to ``data/pilot/red_ocr_results.json``
   and a flat summary to ``data/pilot/red_ocr_summary.json``.

This is phase 2 of the red-ink OCR pilot (the developer asked to
download all images first, then OCR them in a separate pass).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import pytesseract
import numpy as np
from PIL import Image, ImageOps

# Tesseract binary lives at the UB-Mannheim default install path.
# Configure the wrapper once at import so callers don't have to.
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_IN_DIR = Path("data/cards/img")
DEFAULT_INPUT_JSON = Path(
    "docs/research/digitalprairie/ok_pensioners.json"
)
DEFAULT_OUT = Path("data/cards/red_ocr_results.json")
DEFAULT_SUMMARY = Path("data/cards/red_ocr_summary.json")

# Year bounds for plausibility. OK Confederate pensioners were alive
# during/after the war; their death dates fall roughly 1865-1955 with
# most 1900-1950s. 2026-07-29 raised MAX_YEAR 1940 → 1955 after
# issue #139 audit revealed widow cards legitimately have death
# dates in the 1941-1955 range (e.g. Bond, Julia E. died 1942).
# Anything above 1955 is still almost certainly OCR noise (page
# numbers, regiment years, "By letter dated 19XX" stamps).
MIN_YEAR = 1865
MAX_YEAR = 1955

# Precision filters (see docs/learnings/2026-07-28-red-ink-ocr-pilot.md).
# These reject candidates that look like other-dates misread as death
# dates. Each filter is a regex matched (case-insensitive) against
# the context window around the chosen date.
#
# 2026-07-29 expansion: added MARRIED_RE (marriage dates picked as
# death) and LETTER_RE (filing-stamp dates picked as death) after
# issue #139 audit. Both bypassed the previous filter set.
WAR_END_RE = re.compile(r"(?i)\b(paroled|surrendered|citronelle|appomattox)\b")
GRANT_RE = re.compile(r"(?i)\b(granted|rejected)\b")
FILED_RE = re.compile(
    r"(?i)\b(filed|by letter|letter dated|"
    r"q/?\s*c\.?\s+of|qc of|on roll|"
    r"cancelled|canceled|"
    r"q/c|q\.\s*c\.?|filling|approval|approved)\b"
)
CAME_TO_RE = re.compile(r"(?i)\b(came to|arrived in|moved to)\b")
MARRIED_RE = re.compile(
    r"(?i)\b(married|wedded|wed\b|marriage|"
    r"date of birth|d/o/b)\b"
)

# 2026-07-29 added line-stripping helpers for Step L1 (issue
# #139 follow-up). Real pension cards have many short form-field
# lines (REJECTED / GRANTED / Filed / By letter / Q/C of / Widow
# on roll / etc) that often contain a date stamp — filing date,
# approval date, roll-call date — that the original parser would
# pick as a death. Stripping these lines BEFORE find_death_date
# runs reduces NO_KEYWORD_BUT_DATE findings significantly.
#
# Each pattern is matched per-line; lines matching ANY of these
# are dropped from the cleaned text. We also keep the death
# stamp pattern (e.g. "Deceased 4-13-1933") on a protected list
# so we never accidentally strip the actual death line.
LINE_STRIP_PATTERNS = [
    re.compile(r"(?i)\b(rejected|rejection)\b"),
    re.compile(r"(?i)\b(granted|grant)\b"),
    re.compile(r"(?i)\bfiled\b\s*[\d/.\-]+\b"),
    re.compile(r"(?i)\b(by letter|letter dated|letter of)\b"),
    re.compile(r"(?i)\b(q/?\s*c\.?\s+of|q/c|on roll|widow on roll|"
               r"on the roll)\b"),
    re.compile(r"(?i)\b(cancel\w*|approved|approval|filling)\b"),
]
# Lines containing one of these tokens are protected (NEVER
# stripped) because they are likely the actual death stamp.
PROTECTED_LINE_TOKENS = re.compile(
    r"(?i)\b(deceased|died|death|d\.o\.d\.|"
    r"date of death)\b"
)

# Death-context regexes. The word "Deceased" appears as the most
# reliable anchor (saw it on the Andrews card); "died"/"death" are
# common but sometimes get confused with "died in service" etc.
DEATH_KEYWORDS = re.compile(
    r"(?i)\b(deceased|died|death|dead|obit|"
    r"date of death|d\.o\.d\.|d\/d)\b"
)

# Date regexes. We try several common formats the OCR will produce.
# Each pattern yields (regex, parser_fn). parser_fn takes the matched
# string and returns (year, month, day, iso) or None on failure.
def _iso(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


DATE_PATTERNS = [
    # 6-29-1935 / 6/29/1935 / 06-29-1935
    (re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b"),
     lambda m: _try_date(int(m.group(3)), int(m.group(1)), int(m.group(2)))),
    # 1935-6-29
    (re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b"),
     lambda m: _try_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    # Jun 29 1935 / June 29, 1935
    # 2026-07-29 loosened: "[\s,]?" instead of "\s+" before the
    # year so "June 5,1902" (OCR dropped the space after the
    # comma) still parses. Also added "[\.,]" between month-name
    # suffix and day for "Jun. 29".
    (re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\.,]?\s+"
        r"(\d{1,2}),?[\s,]?(\d{4})\b", re.I),
     lambda m: _try_date(
         int(m.group(3)), _month_to_int(m.group(1)), int(m.group(2)))),
    # 29 Jun 1935 / 29 June, 1935
    (re.compile(
        r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*\.?,?\s+(\d{4})\b", re.I),
     lambda m: _try_date(
         int(m.group(3)), _month_to_int(m.group(2)), int(m.group(1)))),
    # 2-digit year on stamps: "Deceased 1-26-25" or "5-2-24".
    # 2026-07-29 added per issue #139: many widow cards have
    # only a 2-digit-year death stamp. Maps 2-digit years to
    # 19xx (all pensioners died after 1900 in practice).
    (re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2})\b"),
     lambda m: _try_2digit_date(int(m.group(3)), int(m.group(1)), int(m.group(2)))),
    # bare 4-digit year (last-resort; only valid near a death keyword)
    (re.compile(r"\b(\d{4})\b"),
     lambda m: _try_year_only(int(m.group(1)))),
]

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month_to_int(s: str) -> int:
    return _MONTHS[s[:3].lower()]


def _try_date(year: int, month: int, day: int) -> tuple | None:
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return None
    if not (1 <= month <= 12):
        return None
    if not (1 <= day <= 31):
        return None
    return ("date", year, month, day, _iso(year, month, day))


def _try_year_only(year: int) -> tuple | None:
    if MIN_YEAR <= year <= MAX_YEAR:
        return ("year-only", year, None, None, f"{year:04d}")
    return None


def _try_2digit_date(year_2d: int, month: int, day: int) -> tuple | None:
    """Map 2-digit year to 19xx and call _try_date.

    All Confederate pensioners in this corpus died in 1900-1955
    (the pension ran 1910s-1950s), so a 2-digit year on a death
    stamp is unambiguously 19xx. 00-30 → 1900-1930; 31-99 →
    1931-1999. We pick a midpoint split at 30 because anything
    below 1931 (year 30) would predate the pension system.
    """
    if not (1 <= month <= 12):
        return None
    if not (1 <= day <= 31):
        return None
    full_year = 1900 + year_2d
    if not (MIN_YEAR <= full_year <= MAX_YEAR):
        return None
    return ("date", full_year, month, day, _iso(full_year, month, day))


def strip_form_lines(text: str) -> tuple[str, list[str]]:
    """Drop stamp / form-field lines that often contain non-death
    dates, before running find_death_date.

    Pension-card OCR output is a single string with no real
    line breaks (Tesseract concatenates). We still try to split
    on common break points: '\\n' (rare but possible), '. ' (end
    of stamp), ' | ' (some Tesseract pages), and every 60 chars
    (a fallback to break the long blob into line-sized chunks).

    For each chunk:
      - If it contains a protected token (deceased/died/death),
        keep it.
      - Else if it matches any LINE_STRIP_PATTERNS, drop it.
      - Else keep it.

    Returns (cleaned_text, dropped_chunks). The dropped list
    is exposed so the re-enrich audit can verify what got
    removed (and surface false positives if a death line was
    accidentally stripped).

    Issue #139 follow-up Step L1 (2026-07-29).
    """
    if not text:
        return "", []

    # Split on real newlines first; then on Tesseract's
    # pipe-delimited form-row pattern; then on sentence ends
    # and on 2+ spaces (Tesseract often joins form rows with
    # extra spaces). The 2+ space split is the important one
    # for stamping areas like
    # 'REJECTED 8/31-20  GRANTED OCT 7 1915  Deceased 4-13-1933'
    # where each stamp is its own logical line.
    chunks: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for piece in re.split(r"\s*[|;]\s*", line):
            piece = piece.strip()
            if not piece:
                continue
            # Split on 2+ spaces and sentence-end if the piece
            # is long. 2+ spaces is the Tesseract "form row
            # separator" signature.
            sub = re.split(r"(?<=[\.\?!])\s+|\s{2,}", piece)
            for s in sub:
                s = s.strip()
                if not s:
                    continue
                if len(s) > 100:
                    sentences = re.split(r"(?<=[\.\?!])\s+", s)
                    chunks.extend(stmt.strip() for stmt in sentences if stmt.strip())
                else:
                    chunks.append(s)

    if not chunks:
        return "", []

    kept: list[str] = []
    dropped: list[str] = []
    for chunk in chunks:
        # Protected tokens always survive.
        if PROTECTED_LINE_TOKENS.search(chunk):
            kept.append(chunk)
            continue
        # Match any strip pattern -> drop.
        if any(pat.search(chunk) for pat in LINE_STRIP_PATTERNS):
            dropped.append(chunk)
            continue
        kept.append(chunk)

    cleaned = " ".join(kept)
    return cleaned, dropped


def build_red_mask(img_rgb: Image.Image) -> Image.Image:
    """Return grayscale image: red ink -> black, rest -> white.

    Per the developer-approved rule: keep pixel iff R > G + B AND R > 100.
    Implemented with numpy for speed (~50x faster than pixel loop on
    a 2932x1748 card). Output uses dark-text-on-light-background
    convention expected by Tesseract.
    """
    arr = np.asarray(img_rgb.convert("RGB"))
    r = arr[:, :, 0].astype(np.int32)
    g = arr[:, :, 1].astype(np.int32)
    b = arr[:, :, 2].astype(np.int32)
    mask = (r > g + b) & (r > 100)
    out = np.full(arr.shape[:2], 255, dtype=np.uint8)
    out[mask] = 0
    return Image.fromarray(out, mode="L")


def ocr_image(img: Image.Image, psm: int = 6) -> str:
    """Run Tesseract. psm=6 = assume a uniform block of text."""
    return pytesseract.image_to_string(img, config=f"--psm {psm}")


def find_death_date(text: str, soldier_name: str = "") -> tuple[dict | None, str]:
    """Return (parsed_date_dict, source_text_window).

    Strategy:
    1. If any death keyword is present, search the surrounding
       text window for a date; prefer the closest match.
    2. If no keyword, fall back to the first plausible date in
       the whole text (less reliable).
    3. Widow-aware (issue #145): when ``soldier_name`` is given,
       candidates in windows that mention the soldier's name are
       preferred. This handles the case where a widow's pension
       card has BOTH the widow's own death date AND the soldier
       husband's death date — we want the latter for FaG search.
    """
    if not text:
        return None, ""

    # Step L1 (issue #139 follow-up, 2026-07-29): strip
    # form-field lines (REJECTED / GRANTED / Filed / By letter /
    # Q/C of / etc) from the text BEFORE scanning for date
    # candidates, so filing/approval/roll-call dates don't get
    # picked as the death. Lines containing 'deceased' or
    # 'died' are protected from stripping. All subsequent
    # candidate scanning + window display operate on the
    # cleaned text; the original is discarded.
    text, _dropped = strip_form_lines(text)

    candidates: list[tuple[str, dict]] = []
    for pattern, parser in DATE_PATTERNS:
        for m in pattern.finditer(text):
            parsed = parser(m)
            if parsed is None:
                continue
            kind, year, month, day, iso = parsed
            candidates.append((
                m.group(0),
                {
                    "kind": kind,
                    "year": year,
                    "month": month,
                    "day": day,
                    "iso": iso,
                    "match": m.group(0),
                    "span": [m.start(), m.end()],
                },
            ))

    if not candidates:
        return None, ""

    # Prefer dates that appear within ~40 chars of a death keyword.
    keyword_spans = [(m.start(), m.end())
                     for m in DEATH_KEYWORDS.finditer(text)]
    soldier_lower = soldier_name.strip().lower() if soldier_name else ""

    def score(c: tuple[str, dict]) -> tuple[int, int, int, int]:
        match_text, info = c
        ms, me = info["span"]
        if not keyword_spans:
            # No keyword at all: deprioritize.
            return (1, 0, 0, info["span"][0])
        min_dist = min(min(abs(ms - ke), abs(me - ks))
                       for ks, ke in keyword_spans)
        # Widow-aware bonus: if the soldier's name appears
        # ANYWHERE on the same side (full text window of ~120
        # chars), the candidate is much more likely to be the
        # soldier's death date. The narrow ±40 window misses
        # cases where the death is in prose but the name is
        # elsewhere on the card (e.g. "Baldwin, James
        # Thompson" at top, "He died" in middle prose).
        # Sort key is ascending tuple — we NEGATE the soldier
        # bonus so candidates mentioning the soldier sort FIRST.
        ws = max(0, ms - 120)
        we = min(len(text), me + 120)
        soldier_in_window = soldier_lower in text[ws:we].lower() \
            if soldier_lower else False
        return (0, 0 if soldier_in_window else 1, 0, min_dist)

    # Precision filters (post-sort, pre-pick). We try the best
    # candidate first; if it triggers a filter, fall through to
    # the next candidate. The filters are strong signals but not
    # absolute, so we keep the highest-scoring candidate that
    # doesn't trip any of them.
    candidates.sort(key=score)
    chosen_info = None
    chosen_window = ""
    # 2026-07-29 widened filter window from ±30 to ±60 chars
    # (issue #139). Phrases like "came to Oklahoma Territory 1912"
    # span ~40 chars; ±30 truncated "came to" off the window so
    # the CAME_TO_RE filter missed the bad date. ±60 covers all
    # known filter phrases.
    WINDOW_PAD = 60
    for _match_text, info in candidates:
        s = max(0, info["span"][0] - WINDOW_PAD)
        e = min(len(text), info["span"][1] + WINDOW_PAD)
        window = text[s:e].replace("\n", " ").strip()
        # If a death keyword is anywhere in the text, a death
        # date SHOULD exist somewhere. Apply filters softly:
        # reject only when the filter phrase is in the immediate
        # window AND no death keyword is in that same window.
        has_kw_in_window = bool(DEATH_KEYWORDS.search(window))
        if GRANT_RE.search(window) and not has_kw_in_window:
            continue
        if FILED_RE.search(window) and not has_kw_in_window:
            continue
        if CAME_TO_RE.search(window) and not has_kw_in_window:
            continue
        if MARRIED_RE.search(window) and not has_kw_in_window:
            continue
        if info["year"] < 1870 and WAR_END_RE.search(window) \
                and not has_kw_in_window:
            continue
        chosen_info = info
        chosen_window = window
        break

    return chosen_info, chosen_window


def process_image(path: Path, soldier_name: str = "") -> dict:
    """Run red-OCR + fallback OCR + date parsing on one image.

    Args:
        path: path to the card image.
        soldier_name: the deceased soldier's last name (or full
            name). Used to disambiguate widow cards where the
            widow's own death date may also appear.
    """
    img = Image.open(path)
    img.load()  # force full decode; protects against partial files
    img = img.convert("RGB")
    red_img = build_red_mask(img)

    red_text = ocr_image(red_img)
    red_parsed, red_window = find_death_date(red_text, soldier_name)

    full_text = ""
    full_parsed = None
    full_window = ""
    source_pass = "red"
    if red_parsed is None:
        full_text = ocr_image(img)
        full_parsed, full_window = find_death_date(full_text, soldier_name)
        if full_parsed is not None:
            source_pass = "full-fallback"

    chosen = red_parsed or full_parsed
    chosen_window = red_window or full_window

    # Stamp the death-keyword presence for downstream review.
    if chosen is not None:
        chosen = dict(chosen)
        combined_text = (red_text or "") + " " + (full_text or "")
        chosen["near_death_keyword"] = bool(
            DEATH_KEYWORDS.search(combined_text)
        )
        # Widow-aware tag: does the chosen window mention the
        # soldier's name? If yes, it's likely the soldier's death
        # date (the one we want for FaG search). If no on a widow
        # card, it's likely the widow's own death date.
        ws = max(0, chosen["span"][0] - 30)
        we = min(len(combined_text), chosen["span"][1] + 30)
        chosen_window_text = combined_text[ws:we]
        chosen["mentions_soldier_name"] = bool(
            soldier_name and soldier_name.lower() in chosen_window_text.lower()
        )

    return {
        "image": path.name,
        "size": list(img.size),
        "red_text_len": len(red_text),
        "red_text": red_text.strip(),
        "red_window": red_window,
        "full_text_len": len(full_text),
        "full_text": full_text.strip(),
        "full_window": full_window,
        "death_date": chosen,
        "source_pass": source_pass if chosen else None,
        "context_window": chosen_window,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", type=Path, default=DEFAULT_IN_DIR)
    ap.add_argument("--input-json", type=Path, default=DEFAULT_INPUT_JSON)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    ap.add_argument("--limit", type=int, default=0,
                    help="process only first N images (debug)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    # Build pensioncard_id -> pensioner record lookup for context.
    rows = json.loads(args.input_json.read_text(encoding="utf-8"))
    pcid_to_pensioner = {}
    pcid_to_soldier_name = {}
    pcid_is_widow = {}
    for i, row in enumerate(rows):
        pcid = row.get("pensioncard_id")
        if pcid is None:
            continue
        pcid = int(pcid)
        spouse_raw = (row.get("spouse_name_raw") or "").strip()
        is_widow = bool(spouse_raw)
        pcid_to_pensioner[pcid] = {
            "pensioner_id": row.get("id"),
            "pensioner_index": i,
            "name_raw": row.get("name_raw"),
            "first_name": row.get("first_name"),
            "last_name": row.get("last_name"),
            "spouse_name_raw": row.get("spouse_name_raw", ""),
            "is_widow_card": is_widow,
        }
        pcid_is_widow[pcid] = is_widow
        # Issue #145: on widow cards the SOLDIER's last name is
        # in the spouse field. We need it for widow-aware date
        # disambiguation so the FaG searcher picks the soldier's
        # death date, not the widow's.
        if is_widow:
            # spouse_raw formats seen: "Last, First M.", "First Last"
            if "," in spouse_raw:
                soldier_last = spouse_raw.split(",")[0].strip()
            else:
                parts = spouse_raw.split()
                soldier_last = parts[-1] if parts else ""
            pcid_to_soldier_name[pcid] = soldier_last
        else:
            # Non-widow card: the pensioner IS the soldier.
            pcid_to_soldier_name[pcid] = (row.get("last_name") or "").strip()

    images = sorted(args.in_dir.glob("*.jpg"))
    if args.limit:
        images = images[: args.limit]
    logging.info("found %d images in %s", len(images), args.in_dir)

    # Resume support: load any existing results JSON and skip
    # images that were already processed. Append new results.
    existing_results: list[dict] = []
    existing_names: set[str] = set()
    if args.out.exists():
        try:
            existing_results = json.loads(
                args.out.read_text(encoding="utf-8")
            )
            existing_names = {r.get("image") for r in existing_results
                              if r.get("image")}
            logging.info("resuming: %d existing results loaded",
                         len(existing_results))
        except Exception as e:
            logging.warning("could not load existing results: %s", e)

    new_images = [p for p in images if p.name not in existing_names]
    skipped = len(images) - len(new_images)
    logging.info("processing %d new images (%d already done)",
                 len(new_images), skipped)

    results = list(existing_results)
    for i, path in enumerate(new_images, 1):
        # filename: <pcid>__<page_id>.jpg
        try:
            pcid = int(path.stem.split("__")[0])
        except Exception:
            pcid = None
        pensioner = pcid_to_pensioner.get(pcid) if pcid is not None else None
        soldier_name = pcid_to_soldier_name.get(pcid, "") if pcid is not None else ""
        logging.info("[%d/%d] %s", i, len(new_images), path.name)
        try:
            r = process_image(path, soldier_name=soldier_name)
        except Exception as e:
            logging.warning("OCR failed %s: %s", path.name, e)
            r = {"image": path.name, "error": str(e)}
        r["pensioncard_id"] = pcid
        r["pensioner"] = pensioner
        r["soldier_name_used"] = soldier_name
        r["is_widow_card"] = pcid_is_widow.get(pcid, False) \
            if pcid is not None else False
        results.append(r)
        # Per-record flush so a crash mid-run doesn't lose work
        # (CONTEXT.md §L3 spirit).
        if (i % 20 == 0) or i == len(new_images):
            args.out.write_text(
                json.dumps(results, indent=2), encoding="utf-8"
            )
        # Heartbeat every 100 images — the OCR script has died
        # silently in this session at least twice; the heartbeat
        # lets external watchers confirm it's still alive.
        if i % 100 == 0:
            import os
            import psutil  # type: ignore
            rss_mb = psutil.Process(os.getpid()).memory_info().rss / 1e6
            logging.info("heartbeat: %d/%d done, RSS=%.0fMB",
                         i, len(new_images), rss_mb)

    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Aggregate summary.
    n = len(results)
    with_red = sum(1 for r in results if r.get("red_text_len", 0) > 0)
    with_full = sum(1 for r in results if r.get("full_text_len", 0) > 0)
    with_date = sum(1 for r in results if r.get("death_date"))
    red_only = sum(1 for r in results
                   if r.get("death_date") and r.get("source_pass") == "red")
    full_only = sum(1 for r in results
                    if r.get("death_date")
                    and r.get("source_pass") == "full-fallback")
    keyword_dates = sum(
        1 for r in results
        if r.get("death_date")
        and (
            any(kw in (r.get("red_text", "") or "")
                for kw in ("deceased", "died", "death", "dead"))
            or any(kw in (r.get("full_text", "") or "")
                   for kw in ("deceased", "died", "death", "dead"))
        )
    )
    plausible = sum(
        1 for r in results
        if r.get("death_date")
        and MIN_YEAR <= r["death_date"]["year"] <= MAX_YEAR
    )
    summary = {
        "total_images": n,
        "with_red_text": with_red,
        "with_full_text": with_full,
        "with_death_date": with_date,
        "from_red_pass": red_only,
        "from_full_fallback": full_only,
        "near_death_keyword": keyword_dates,
        "year_in_range": plausible,
        "candidate_rate": round(with_date / n, 3) if n else 0,
        "plausible_rate": round(plausible / n, 3) if n else 0,
        "red_vs_full_ratio": (
            round(red_only / with_date, 3) if with_date else 0
        ),
    }
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logging.info("summary: %s", json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())