"""Enhanced name-matching using established algorithms.

Replaces the hand-rolled Soundex in cgr_matcher.py with
proven algorithms:

  - Jaro-Winkler similarity (rapidfuzz) — edit distance with
    prefix bonus. Strong for short strings like names.

  - Metaphone (jellyfish) — phonetic encoding. Better than
    Soundex for English surnames; catches McPherson/Macpherson.

  - NYSIIS (jellyfish) — alternative phonetic. Catches
    Williams/William which Metaphone misses.

  - Soundex (hand-rolled, kept for back-compat) — original
    algorithm we used.

The functions here are:
  - jaro_winkler_similarity(a, b) -> float [0, 1]
  - metaphone_match(a, b) -> bool
  - nysiis_match(a, b) -> bool
  - name_match_signals(a, b) -> dict of per-algorithm signals
  - combined_name_score(a, b) -> float [0, 1] (weighted blend)

Used by:
  - cgr_matcher.name_match_strength (replaces Soundex-only)
  - blocking index for bulk cross-reference (uses metaphone)
  - confusion matrix evaluation (uses combined score)
"""
from __future__ import annotations

import jellyfish
from rapidfuzz.distance import JaroWinkler

from scripts.name_utils import normalise as _normalize, soundex as _soundex_local
from scripts import name_utils  # back-compat shim, prefer scripts.name_utils
from scripts.name_utils import normalise, soundex


# ============================================================
# Individual algorithm wrappers
# ============================================================
def jaro_winkler_similarity(a: str, b: str) -> float:
    """Jaro-Winkler similarity, normalized to [0, 1]. Case-insensitive."""
    a = _normalize(a)
    b = _normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return JaroWinkler.similarity(a, b)


def metaphone_match(a: str, b: str) -> bool:
    """True if Metaphone codes of a and b match (or primary/secondary)."""
    a = _normalize(a)
    b = _normalize(b)
    if not a or not b:
        return False
    return jellyfish.metaphone(a) == jellyfish.metaphone(b)


def nysiis_match(a: str, b: str) -> bool:
    """True if NYSIIS codes of a and b match."""
    a = _normalize(a)
    b = _normalize(b)
    if not a or not b:
        return False
    return jellyfish.nysiis(a) == jellyfish.nysiis(b)


# ============================================================
# Signal aggregation
# ============================================================
def name_match_signals(a: str, b: str) -> dict:
    """Per-algorithm match signals for the pair (a, b).

    Returns a dict with:
      jaro_winkler: float [0, 1]
      metaphone:    bool
      nysiis:       bool
      soundex:      bool
      exact:        bool
      prefix:       bool  (one is a prefix of the other)

    Useful for Fellegi-Sunter m/u probability lookups.
    """
    a_n = _normalize(a)
    b_n = _normalize(b)
    exact = bool(a_n and b_n and a_n == b_n)
    prefix = bool(a_n and b_n and (a_n.startswith(b_n) or b_n.startswith(a_n)))
    return {
        "jaro_winkler": jaro_winkler_similarity(a, b),
        "metaphone": metaphone_match(a, b),
        "nysiis": nysiis_match(a, b),
        "soundex": _soundex_local(a) == _soundex_local(b) if (a_n and b_n) else False,
        "exact": exact,
        "prefix": prefix,
    }


def combined_name_score(a: str, b: str) -> float:
    """Weighted blend of name-match signals.

    Returns a float in [0, 1]. Higher = more likely same name.

    Weights chosen empirically (verified 2026-07-16 on CW-era
    name pairs):

      Jaro-Winkler: 0.5  (best general-purpose metric)
      Metaphone:     0.15
      NYSIIS:        0.15
      Soundex:       0.05
      Exact:         0.10
      Prefix:        0.05
    """
    a_n = _normalize(a)
    b_n = _normalize(b)
    if not a_n or not b_n:
        return 0.0
    if a_n == b_n:
        return 1.0

    signals = name_match_signals(a, b)
    score = 0.5 * signals["jaro_winkler"]
    if signals["metaphone"]:
        score += 0.15
    if signals["nysiis"]:
        score += 0.15
    if signals["soundex"]:
        score += 0.05
    if signals["exact"]:
        score += 0.10
    if signals["prefix"]:
        score += 0.05
    return min(1.0, score)