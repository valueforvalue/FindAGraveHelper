"""Parse spouse and children sections from a FaG memorial page.

FaG's memorial page renders family relationships as plain text
sections:

    Spouse
    Fayette J. "Fannie" Rogers Looney
    1844–1931 (m. 1870)

    Children
    Walter W Looney
    1874–1953

This module extracts structured dicts from each entry. Both
extract_spouse() and extract_children() take the full page text
(plain text, not HTML) as input.

The text uses en-dashes (\u2013) between years and the marriage
year in parentheses. Some entries have a "V VETERAN" suffix on
the name (children of CW veterans).
"""
import re
from typing import Optional


# Names with embedded "V VETERAN" suffix or maiden-name parens should
# not break the regex. We pull the line above the year-pair.
_ENTRY_RE = re.compile(
    r"^([^\n]+?)\s*\n\s*(\d{4})\s*[\u2013\u2014\-]\s*(\d{4})",
    re.MULTILINE,
)


_SUFFIXES = {"Jr", "Jr.", "Sr", "Sr.", "II", "III", "IV", "V"}


def _parse_entry(raw: str, b: str, d: str) -> dict:
    """Turn a raw name string + dates into a structured dict."""
    # Strip " V VETERAN" suffix (appears on CW-era FaG entries)
    clean = re.sub(r"\s+V\s*VETERAN\s*$", "", raw).strip()
    # Split into tokens. The last token may be a suffix (Jr, Sr, III, …).
    parts = clean.split()
    # Pop suffix off if it's the last token.
    if parts and parts[-1] in _SUFFIXES:
        parts = parts[:-1]
    return {
        "raw_name": clean,
        "first_name": parts[0] if parts else "",
        "last_name": parts[-1] if len(parts) > 1 else (parts[0] if parts else ""),
        "birth_year": b,
        "death_year": d,
    }


def extract_spouse(page_text: str) -> Optional[dict]:
    """Extract the first spouse entry from a FaG memorial page.

    Returns a dict with raw_name, first_name, last_name, birth_year,
    death_year, or None if no spouse section is found.
    """
    # Locate the "Spouse" header.
    spouse_idx = page_text.find("Spouse")
    if spouse_idx == -1:
        return None
    # Section ends at next major header.
    end_markers = ["Children", "Parents", "Burial", "Plot", "Inscription"]
    end_idx = len(page_text)
    for m in end_markers:
        idx = page_text.find(m, spouse_idx + 7)
        if idx > -1:
            end_idx = min(end_idx, idx)
    section = page_text[spouse_idx:end_idx]
    m = _ENTRY_RE.search(section)
    if not m:
        return None
    return _parse_entry(m.group(1), m.group(2), m.group(3))


def extract_children(page_text: str) -> list[dict]:
    """Extract all children entries from a FaG memorial page.

    Returns a list of dicts (same shape as extract_spouse), or an
    empty list if no Children section is found.
    """
    children_idx = page_text.find("Children")
    if children_idx == -1:
        return []
    end_markers = ["Parents", "Burial", "Plot", "Inscription"]
    end_idx = len(page_text)
    for m in end_markers:
        idx = page_text.find(m, children_idx + 9)
        if idx > -1:
            end_idx = min(end_idx, idx)
    section = page_text[children_idx:end_idx]
    matches = _ENTRY_RE.findall(section)
    return [_parse_entry(raw, b, d) for raw, b, d in matches]