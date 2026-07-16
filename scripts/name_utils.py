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

    Implements the standard Soundex algorithm:
      - First letter preserved uppercase.
      - Remaining letters coded by group:
          B,F,P,V           -> 1
          C,G,J,K,Q,S,X,Z   -> 2
          D,T               -> 3
          L                 -> 4
          M,N               -> 5
          R                 -> 6
          A,E,I,O,U,Y,H,W   -> 0 (vowels and H/W dropped)
      - Adjacent duplicates collapsed (e.g. "Pfister" -> P236, not P223).
      - Vowels/H/W separate duplicate runs (so "Robert" -> R163,
        "Rupert" -> R163 — same code).
      - Padded with '0' to 4 chars.

    Reference: https://en.wikipedia.org/wiki/Soundex

    Note: the original search_fag soundex (pre-T016) was buggy —
    it omitted the AEIOUYHW mapping and produced wrong codes
    like "Robert" -> R000. This implementation is the corrected
    version; callers comparing two soundex codes for equality
    are unaffected since both sides use the same impl.
    """
    name = normalise(name)
    if not name:
        return ""
    code = name[0].upper()
    mapping = {"BFPV": "1", "CGJKQSXZ": "2", "DT": "3", "L": "4",
               "MN": "5", "R": "6", "AEIOUYHW": "0"}
    last_code = ""
    for c in name[1:]:
        cu = c.upper()
        for k, v in mapping.items():
            if cu in k:
                # Collapse adjacent duplicates only; a vowel/H/W
                # separates runs so the next consonant can re-emit.
                if v != "0" and v != last_code:
                    code += v
                last_code = v
                break
        else:
            # Unknown character (shouldn't happen post-normalise).
            last_code = ""
    return code.ljust(4, '0')[:4]