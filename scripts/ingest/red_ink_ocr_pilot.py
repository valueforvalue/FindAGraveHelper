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
MIN_YEAR = 1860
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
# Issue #144 (2026-08-01): "Entered Home" anti-keyword. The
# Confederate Home admission date is NOT a death date. OCR reads
# "Entered Home 11-1-29" next to "Deceased 3-17-31" on the
# same card; the parser previously picked the home-entry date
# because it was closer to "Deceased" by char distance.
ENTERED_HOME_RE = re.compile(
    r"(?i)\b(entered\s+(?:the\s+)?home|ent(?:d|ered)\s+home)\b"
)
# Issue #144 (2026-08-01): enlistment anti-keyword.
ENLISTED_RE = re.compile(r"(?i)\benlist\w*\b")
# L3 follow-up (2026-07-29): address-change anti-keywords. A
# date within ±60 chars of any of these phrases is an
# address-change date, not a death. The inline filters in
# find_death_date apply these on the cleaned-text window AFTER
# strip_form_lines has dropped whole chunks; this catches cases
# where the phrase and date are on adjacent chunks.
ADDR_CHANGE_RE = re.compile(
    r"(?i)\b(gives\b|gives:|changed\b|"
    r"o\s*/\s*c\b|o\.\s*c\.\b|"
    r"temp\.?\s+ad(?:dress)?\b|"
    r"post\s+card\b|"
    r"a/?c\s+|gc\s+|oy\s+|qc\s+|aw\s+)\s*[\d/.\-]+"
)
# L3 follow-up: "by letter" inline (when the chunk didn't get
# stripped because the date appears AFTER the phrase on the
# same line).
LETTER_DATE_RE = re.compile(
    r"(?i)\b(?:by\s+letter|letter\s+dated|letter\s+of)\b"
    r"\s*[\d/.\-]+"
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
    # L3 follow-up (2026-07-29): address-change entries. These are
    # admin records where a date is paired with a phrase like
    # 'gives Temp Address', 'Changed from X to Y', 'o/c X/X/XX
    # gives ...'. Tesseract emits them on the same OCR block as
    # the Deceased stamp; the date is the address-change date,
    # NOT a death. The phrase 'gives' or 'Changed' on the same
    # chunk is the discriminator. Drops the whole chunk if the
    # phrase appears, even when a death keyword is also in the
    # chunk (because the chunks get split on sentence-end so the
    # address-change line is its own chunk).
    re.compile(r"(?i)\b(gives\b|gives:|changed\b|"
               r"o\s*/\s*c\b|o\.\s*c\.\b|"
               r"temp\.?\s+ad(?:dress)?\b|"
               r"post\s+card\b)"),
    # L3 follow-up: short-form correspondence tokens. These show
    # up at the start of admin chunks: 'a/c', 'ac', 'oy', 'gc'.
    # 'a/c' (acknowledgment of correspondence) and 'gc' (general
    # correspondence) are NOT death markers.
    re.compile(r"(?i)\b(?:^|\s)(?:a/?c|gc|oy|qc|aw)\s+[\d/.\-]+"),
    re.compile(r"(?i)\b(?:paroled|surrendered|citronelle|appomattox)\b"),
    # Issue #144 (2026-08-01): enlistment dates. 'Enlisted May 5th
    # 1862' is the enlistment date, NOT a death date. Common on
    # widow cards that record the soldier's service history.
    re.compile(r"(?i)\benlist\w*\b"),
]


ORPHAN_STAMP_RE = re.compile(
    r"(?i)"
    
    r"\b(?:[OC]?[OC]?T|N[OC]V|NUV|0N|00T|NOV)\s*[\d\s=.\-]{1,6}\d{4}\b"
    r"|"
    
    r"\b(?:NOVEMBER|OCTOBER|NOV|OCT)\s*[\d\s=.\-]{1,4}\d{4}\b"
    r"|"
    
    r"\b[A-Z]?\d\s*[=\-]\s*\d{4}\b"
    r"|"
    
    r"\b\d\s*[=\-]\s*\d{4}\b"
)
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


def _levenshtein(a: str, b: str) -> int:
    """Standard Levenshtein edit distance. Used by
    fuzzy_death_keyword to detect OCR-misread variants of
    DECEASED. Tiny implementation to avoid pulling in a
    third-party lib (the text is short, edit-distance is
    fine inline)."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            ins = cur[j] + 1
            dele = prev[j + 1] + 1
            sub = prev[j] + (ca != cb)
            cur.append(min(ins, dele, sub))
        prev = cur
    return prev[-1]


# Words we know are common OCR misreads of DECEASED on these
# pension cards. Spot-checked from the 221 NO_KEYWORD_BUT_DATE
# residuals after the L4 stamp-fragment fix (issue #139 follow-up
# 2026-07-31). Listed explicitly rather than via Levenshtein
# because the misreads are stylistically specific (Tesseract
# char-swap patterns) and a small fixed list is more
# auditable than a fuzzy threshold.
DEATH_KEYWORD_OCR_MISREADS = frozenset({
    "peceased", "peceaged", "dededsed", "deceasea", "deczased",
    "dechashd", "dechased", "dseeased", "dbcbasbd",
    "vecoa", "vecoad", "amceased", "ceceased",
    "deceased", "deceaged", "dece", "decea", "ceased",
    "dccascd", "dcd",
})


def fuzzy_death_keyword(text: str) -> bool:
    """Return True if text contains a death keyword OR a known
    OCR misread of one.

    The strict `DEATH_KEYWORDS` regex misses common OCR
    mistakes like 'peceased', 'Dededsed', 'Decea sed',
    'DBCBASBD', 'DECHASHD', 'DECZASED', 'vecoa'. Without
    this fuzzy pass, real death dates get flagged as
    NO_KEYWORD_BUT_DATE in the audit (the L4 follow-up
    residual set).

    The matcher:
    1. Checks strict DEATH_KEYWORDS first (cheap, exact).
    2. Tokenizes, lowercases each 4-10 letter word.
    3. Accepts if the word is in DEATH_KEYWORD_OCR_MISREADS.
    4. Accepts if the word starts with dec/dea/ded/die AND
       is within Levenshtein distance 2 of 'deceased' or
       'died' (catches novel future misreads).

    The threshold (distance 2, length 4-10) is tight enough
    to avoid false matches on words like 'address', 'company',
    'rejected', 'remarks' that share letters with the death
    keywords.
    """
    return _fuzzy_keyword_match(text) is not None


def _fuzzy_keyword_match(text: str) -> tuple[int, int] | None:
    """Like fuzzy_death_keyword but returns the (start, end)
    span of the matched word (or the first strict DEATH_KEYWORDS
    match span). Returns None if no match.

    Used by find_death_date to compute `keyword_spans` for the
    proximity-to-death-keyword scoring without re-implementing
    the fuzzy rules.
    """
    if not text:
        return None
    m = DEATH_KEYWORDS.search(text)
    if m:
        return (m.start(), m.end())
    for wm in re.finditer(r"[A-Za-z]{3,12}", text):
        w = wm.group(0)
        wl = w.lower()
        if wl in DEATH_KEYWORD_OCR_MISREADS:
            return (wm.start(), wm.end())
        if len(wl) < 4 or len(wl) > 10:
            continue
        if not (
            wl.startswith("dec") or wl.startswith("dea")
            or wl.startswith("ded") or wl.startswith("die")
        ):
            continue
        target = (
            "deceased" if wl.startswith(("dec", "dea", "ded"))
            else "died"
        )
        if _levenshtein(wl, target) <= 2:
            return (wm.start(), wm.end())
    return None

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
    # Issue #144 (2026-08-01): Month YYYY without day. Widow
    # cards often record the soldier's death as 'he died June
    # 1863' (Civil War deaths have no exact day on the card).
    # Year-only kind but month is preserved for scoring.
    (re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\.,]?\s+"
        r"(\d{4})\b", re.I),
     lambda m: (
         "year-only", int(m.group(2)), _month_to_int(m.group(1)),
         None, str(int(m.group(2)))
     ) if MIN_YEAR <= int(m.group(2)) <= MAX_YEAR else None),
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
        
        if ORPHAN_STAMP_RE.search(chunk):
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
    
    _dropped_text = " ".join(_dropped)

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
        # Issue #144 follow-up (2026-08-02): fallback for OCR-garbled
        # DECEASED stamps where DATE_PATTERNS didn't match but a
        # 4-digit year IS in the same ±60-char window as a death
        # keyword. The common failure mode is "DECEASED LecerlvoO"
        # where the date token is fully mangled; the year digit
        # survives but the date regex can't parse it. Without this
        # fallback the parser returns None and the audit's H6
        # EMPTY_BUT_STAMP_PRESENT fires. With it we recover ~212/591
        # EMPTY records.
        #
        # Restricted: only fires when the text already had a death
        # keyword match AND at least one bare 4-digit year
        # (1860-1949) in the keyword's window. Returns a year-only
        # candidate (no month/day) — less precise than a full date
        # but better than None.
        kw_iter = 0
        while kw_iter < len(text):
            m = _fuzzy_keyword_match(text[kw_iter:])
            if m is None:
                break
            s, e = m
            abs_s, abs_e = kw_iter + s, kw_iter + e
            win_s = max(0, abs_s - 60)
            win_e = min(len(text), abs_e + 60)
            window = text[win_s:win_e]
            best = None
            best_dist = 999
            for ym in re.finditer(r"\b(18[6-9]\d|19[0-4]\d)\b", window):
                y = int(ym.group(1))
                dist = min(abs(ym.start() + win_s - abs_s),
                           abs(ym.start() + win_s - abs_e))
                if dist < best_dist:
                    best_dist = dist
                    best = (y, win_s + ym.start(), win_s + ym.end())
            if best is not None:
                y, ms, me = best
                candidates.append((
                    f"{y}",
                    {
                        "kind": "year",
                        "year": y,
                        "month": None,
                        "day": None,
                        "iso": f"{y:04d}",
                        "match": f"{y}",
                        "span": [ms, me],
                    },
                ))
                break
            kw_iter = kw_iter + e
        if not candidates:
            return None, ""

    # Prefer dates that appear within ~40 chars of a death keyword.
    # Use the fuzzy matcher (strict regex + known OCR misreads +
    # Levenshtein-2 for novel variants) so we don't miss real
    # death dates where OCR garbled the word (issue #139 follow-up).
    keyword_spans = []
    cursor = 0
    while cursor < len(text):
        m = _fuzzy_keyword_match(text[cursor:])
        if m is None:
            break
        s, e = m
        keyword_spans.append((cursor + s, cursor + e))
        cursor = cursor + e
    soldier_lower = soldier_name.strip().lower() if soldier_name else ""

    def score(c: tuple[str, dict]) -> tuple[int, int, int, int, int]:
        match_text, info = c
        ms, me = info["span"]
        if not keyword_spans:
            # No keyword at all: deprioritize. L2 (2026-07-29)
            # adds a within-cluster-penalty so the chosen year
            # is the one closest to the median of all candidates
            # (catches a 1915 grant-stamp year when a 1929
            # death year is also present in the OCR text).
            years = [info2["year"] for _, info2 in candidates
                     if info2.get("year")]
            if years:
                years_sorted = sorted(years)
                median_year = years_sorted[len(years_sorted) // 2]
                # Penalties for far-from-median; war-end and
                # grant-stamp years (1865, 1915) typically end
                # up as outliers in widow-card OCR text.
                penalty = min(abs(info["year"] - median_year), 99)
            else:
                penalty = 0
            return (1, 0, 0, info["span"][0], penalty)
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
        return (0, 0 if soldier_in_window else 1, 0, min_dist, 0)

    # Precision filters (post-sort, pre-pick). We try the best
    # candidate first; if it triggers a filter, fall through to
    # the next candidate. The filters are strong signals but not
    # absolute, so we keep the highest-scoring candidate that
    # doesn't trip any of them.
    candidates.sort(key=score)
    chosen_info = None
    chosen_window = ""
    # Issue #139 follow-up: when the only year in cleaned text
    # is 1915 (or 1865) AND the stripper dropped chunks
    # containing GRANTED/REJECTED (or war-end keywords), the
    # surviving 1915 (or 1865) is almost certainly a stamp
    # fragment that escaped the line-level strip. Reject it
    # so the pensioner goes to manual review instead of
    # getting a wrong death year downstream.
    if (
        _dropped_text
        and len(candidates) == 1
        and not keyword_spans
    ):
        only_year = candidates[0][1]["year"]
        stamp_dropped = (
            GRANT_RE.search(_dropped_text)
            or FILED_RE.search(_dropped_text)
        )
        war_dropped = WAR_END_RE.search(_dropped_text)
        if only_year == 1915 and stamp_dropped:
            return None, ""
        if only_year == 1865 and war_dropped:
            return None, ""
    # Issue #144 follow-up (2026-08-02): the existing 1915/1865
    # gate above only fires when len(candidates) == 1 AND no
    # keyword spans exist. When strip_form_lines dropped a
    # GRANTED stamp (so the GRANTED word is gone from cleaned
    # text) but 1915 also survived as a date candidate — and
    # there are 2+ candidates and/or DECEASED keywords somewhere
    # on the card — the soft gate is bypassed and the parser
    # happily picks 1915 as the death year (issue #144 audit
    # surfaced 1,350 GRANTED_PICK findings, mostly via this
    # path). Fix: pre-emptively drop 1915/1865 candidates from
    # the sort when their WINDOW (after the existing ±60-char
    # window is computed) has no death keyword AND a stamp was
    # stripped. If a death keyword IS in the window — e.g.
    # "DECEASED 7 Nov 1915" plus a stripped "GRANTED OCT 7
    # 1915" line — keep the candidate (the 1915 IS the real
    # death year, not a stamp fragment).
    if _dropped_text:
        stamp_dropped = (
            GRANT_RE.search(_dropped_text)
            or FILED_RE.search(_dropped_text)
        )
        war_dropped = WAR_END_RE.search(_dropped_text)
        if stamp_dropped or war_dropped:
            survivors = []
            for m, info in candidates:
                # Compute the same window the filter loop below uses
                s = max(0, info["span"][0] - 60)
                e = min(len(text), info["span"][1] + 60)
                win = text[s:e].replace("\n", " ").strip()
                win_has_kw = fuzzy_death_keyword(win)
                drop = False
                if stamp_dropped and info["year"] == 1915 and not win_has_kw:
                    drop = True
                if war_dropped and info["year"] == 1865 and not win_has_kw:
                    drop = True
                if not drop:
                    survivors.append((m, info))
            candidates = survivors
            if not candidates:
                return None, ""
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
        has_kw_in_window = fuzzy_death_keyword(window)
        if GRANT_RE.search(window) and not has_kw_in_window:
            continue
        if FILED_RE.search(window) and not has_kw_in_window:
            continue
        if CAME_TO_RE.search(window) and not has_kw_in_window:
            continue
        if MARRIED_RE.search(window) and not has_kw_in_window:
            continue
        # L3 follow-up (2026-07-29): address-change / short-form
        # correspondence anti-keywords. Catches 'gives Temp
        # Address', 'Changed from X to Y', 'o/c X/X/XX', etc.
        # Same logic as FILED_RE: only reject when no death
        # keyword is in the immediate window (a Deceased stamp
        # adjacent to the phrase should still be allowed).
        if ADDR_CHANGE_RE.search(window) and not has_kw_in_window:
            continue
        if LETTER_DATE_RE.search(window) and not has_kw_in_window:
            continue
        if info["year"] < 1870 and WAR_END_RE.search(window) \
                and not has_kw_in_window:
            continue
        # Issue #144 (2026-08-01): "Entered Home" anti-keyword.
        # Position-ordered check: when "Entered Home" appears
        # BEFORE the candidate and a death keyword appears AFTER,
        # the candidate is the home-entry date, not the death
        # date. Also reject when "Entered Home" is near the
        # candidate and no death keyword is in the window.
        if ENTERED_HOME_RE.search(window):
            eh_before = any(
                eh.end() <= info["span"][0]
                for eh in ENTERED_HOME_RE.finditer(text)
            )
            kw_after = any(
                ks >= info["span"][1]
                for ks, _ in keyword_spans
            ) if keyword_spans else False
            if eh_before and (kw_after or not has_kw_in_window):
                continue
        # Issue #144 (2026-08-01): enlistment anti-keyword. With
        # MIN_YEAR lowered to 1860, Civil War enlistment dates
        # like 'enlisted May 5th 1862' become parseable. Reject
        # them the same way as CAME_TO / MARRIED: only when no
        # death keyword is in the immediate window.
        if ENLISTED_RE.search(window) and not has_kw_in_window:
            continue
        # L2 (2026-07-29) additional filters. When NO death
        # keyword is anywhere in the text, the year 1915 is
        # overwhelmingly the GRANTED stamp year (every card has
        # 'GRANTED OCT 7 1915') — reject it unless the candidate
        # is the only one. Same for 1865 (war-end parole /
        # surrender) when other candidates exist.
        if not keyword_spans:
            other_years = [info2["year"] for _, info2 in candidates
                           if info2 is not info and info2.get("year")]
            if info["year"] == 1915 and other_years:
                continue
            if info["year"] == 1865 and other_years:
                continue
        # L2 (2026-07-29) widow strictness. On widow cards (soldier
        # name supplied), if NO death keyword is present anywhere
        # in the text AND the candidate isn't within ±120 chars of
        # the soldier's name, the year is too suspicious to trust.
        # Widow cards almost always mention the soldier in the
        # 'Widow of <name>' header near the death date; if the
        # parser can't find that adjacency, it's probably a
        # wrong-field date (filing, marriage, came-to).
        if not keyword_spans and soldier_lower:
            ws = max(0, info["span"][0] - 120)
            we = min(len(text), info["span"][1] + 120)
            if soldier_lower not in text[ws:we].lower():
                # L3 follow-up (2026-07-29): dropped the
                # 'only candidate' fallback. When there's no
                # death keyword AND the soldier name isn't
                # near the date, even a single candidate is
                # still suspicious — most likely a filing,
                # correspondence, or address-change date.
                # Returning None forces manual review rather
                # than a wrong-field date flowing downstream.
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
        chosen["near_death_keyword"] = fuzzy_death_keyword(
            combined_text
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