"""Name helpers shared by search_fag and phonetic_match.

Extracted from search_fag.py (T016 of the refactor). These two
helpers are used by both the FaG search ladder and the CGR
matcher; keeping them in a leaf module breaks the inverted
dependency where phonetic_match reached up into the god-module
search_fag.

Public surface (2 functions):
  - normalise(s) -> str: lowercase + strip non-alpha
  - soundex(name) -> str: classic 4-char Soundex code

Both are defensive about empty / None input (return "").
"""
from __future__ import annotations

import re

__all__ = ["normalise", "soundex"]


def normalise(s: str) -> str:
    """Lowercase + strip everything that isn't a-z.

    The original search_fag normaliser. ASCII-only by design;
    unicode letters like é are stripped rather than transliterated
    so two strings that differ only in diacritics still compare
    unequal (avoiding false matches like "Jose"/"José" being
    treated as identical when the underlying data is mixed).
    """
    return re.sub(r"[^a-z]", "", (s or "").lower())


def soundex(name: str) -> str:
    """Classic 4-character Soundex code (letter + 3 digits).

    The original search_fag Soundex. Uses the standard
    BFPV/CGJKQSXZ/DT/L/MN/R digit mapping. Adjacent duplicates
    are collapsed (e.g. "Pfister" -> P236, not P223). First
    letter preserved uppercase; padded with '0' to 4 chars.
    """
    name = normalise(name)
    if not name:
        return ""
    code = name[0].upper()
    mapping = {"BFPV": "1", "CGJKQSXZ": "2", "DT": "3", "L": "4", "MN": "5", "R": "6"}
    for c in name[1:]:
        for k, v in mapping.items():
            if c in k:
                if code[-1] != v:
                    code += v
                break
    code = code[0] + ''.join(c for c in code[1:] if not c.isalpha())
    return code.ljust(4, '0')[:4]