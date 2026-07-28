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

DEFAULT_IN_DIR = Path("data/pilot/img")
DEFAULT_INPUT_JSON = Path(
    "docs/research/digitalprairie/ok_pensioners_sample_50.json"
)
DEFAULT_OUT = Path("data/pilot/red_ocr_results.json")
DEFAULT_SUMMARY = Path("data/pilot/red_ocr_summary.json")

# Year bounds for plausibility. OK Confederate pensioners were alive
# during/after the war; their death dates fall roughly 1865-1940 with
# most 1900-1940. Anything outside this window is almost certainly
# OCR noise (page numbers, regiment years, etc.).
MIN_YEAR = 1865
MAX_YEAR = 1940

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
    (re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
        r"(\d{1,2}),?\s+(\d{4})\b", re.I),
     lambda m: _try_date(
         int(m.group(3)), _month_to_int(m.group(1)), int(m.group(2)))),
    # 29 Jun 1935 / 29 June, 1935
    (re.compile(
        r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*\.?,?\s+(\d{4})\b", re.I),
     lambda m: _try_date(
         int(m.group(3)), _month_to_int(m.group(2)), int(m.group(1)))),
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


def find_death_date(text: str) -> tuple[dict | None, str]:
    """Return (parsed_date_dict, source_text_window).

    Strategy:
    1. If any death keyword is present, search the surrounding
       text window for a date; prefer the closest match.
    2. If no keyword, fall back to the first plausible date in
       the whole text (less reliable).
    """
    if not text:
        return None, ""

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

    def score(c: tuple[str, dict]) -> tuple[int, int]:
        match_text, info = c
        if not keyword_spans:
            # No keyword at all: deprioritize.
            return (1, info["span"][0])
        ms, me = info["span"]
        # Prefer the candidate closest to ANY keyword.
        min_dist = min(min(abs(ms - ke), abs(me - ks))
                       for ks, ke in keyword_spans)
        return (0, min_dist)

    candidates.sort(key=score)
    chosen_text, chosen_info = candidates[0]

    # Build a small context window around the chosen match for
    # human review.
    s = max(0, chosen_info["span"][0] - 30)
    e = min(len(text), chosen_info["span"][1] + 30)
    window = text[s:e].replace("\n", " ").strip()

    return chosen_info, window


def process_image(path: Path) -> dict:
    """Run red-OCR + fallback OCR + date parsing on one image."""
    img = Image.open(path).convert("RGB")
    red_img = build_red_mask(img)

    red_text = ocr_image(red_img)
    red_parsed, red_window = find_death_date(red_text)

    full_text = ""
    full_parsed = None
    full_window = ""
    source_pass = "red"
    if red_parsed is None:
        full_text = ocr_image(img)
        full_parsed, full_window = find_death_date(full_text)
        if full_parsed is not None:
            source_pass = "full-fallback"

    chosen = red_parsed or full_parsed
    chosen_window = red_window or full_window

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
    for i, row in enumerate(rows):
        pcid = row.get("pensioncard_id")
        if pcid is not None:
            pcid_to_pensioner[int(pcid)] = {
                "pensioner_id": row.get("id"),
                "pensioner_index": i,
                "name_raw": row.get("name_raw"),
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
            }

    images = sorted(args.in_dir.glob("*.jpg"))
    if args.limit:
        images = images[: args.limit]
    logging.info("processing %d images from %s", len(images), args.in_dir)

    results = []
    for i, path in enumerate(images, 1):
        # filename: <pcid>__<page_id>.jpg
        try:
            pcid = int(path.stem.split("__")[0])
        except Exception:
            pcid = None
        pensioner = pcid_to_pensioner.get(pcid) if pcid is not None else None
        logging.info("[%d/%d] %s", i, len(images), path.name)
        try:
            r = process_image(path)
        except Exception as e:
            logging.warning("OCR failed %s: %s", path.name, e)
            r = {"image": path.name, "error": str(e)}
        r["pensioncard_id"] = pcid
        r["pensioner"] = pensioner
        results.append(r)

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
        and any(kw in (r.get("red_text", "") or "")
                for kw in ("deceased", "died", "death"))
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