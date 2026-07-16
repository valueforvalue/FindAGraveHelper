"""Regiment-keyword extraction for FaG bio= search.

FaG's `bio=` URL param does full-text matching against memorial
bios. For CW veterans, the regiment name is strongly identifying.

Some regiment strings are compound:
    "2nd Mississippi & 3rd Mississippi Infantry & Cavalry"
which we should split into multiple phrases. Each phrase becomes
a candidate bio= value; we return only one (the most distinctive)
to keep URL params small.

Strategy helpers also exposed via `strategy_regiment_bio` for
the strategy ladder.
"""
from __future__ import annotations

import re


# Compound separator (most common: " & ")
_COMPOUND_SEP = re.compile(r"\s+&\s+|\s+and\s+", re.I)

# Words to drop when we have leftover noise
_DROP_PHRASES = [
    "Infantry", "Cavalry", "Artillery", "Mounted Rifles", "Riflemen",
    "Battalion", "Regiment", "Brigade", "Division",
]


def _split_compound(regiment: str) -> list[str]:
    """Split "2nd Mississippi & 3rd Mississippi Infantry" into fragments."""
    parts = _COMPOUND_SEP.split(regiment or "")
    # Clean up leading/trailing spaces
    return [p.strip() for p in parts if p.strip()]


def extract_regiment_phrases(regiment: str, max_phrases: int = 3) -> list[str]:
    """Extract up to max_phrases distinctive phrases from a regiment string.

    Rules:
    - Split on " & " or " and " first
    - For each fragment, take the longest meaningful prefix
      (e.g., "2nd Mississippi" beats just "Mississippi")
    - Deduplicate (case-insensitive)
    - Cap at max_phrases
    """
    if not regiment:
        return []
    fragments = _split_compound(regiment)
    phrases = []
    seen = set()
    for frag in fragments:
        # Strip trailing drop-phrases; keep them only if nothing else
        words = frag.split()
        # Find the longest prefix that contains a state-name-like word
        for i in range(len(words), 0, -1):
            candidate = " ".join(words[:i]).strip()
            # Skip pure drop-phrase
            if not any(d.lower() in candidate.lower() for d in _DROP_PHRASES):
                # And it must have at least 2 words or a number
                if len(candidate.split()) >= 1 and (
                    any(ch.isdigit() for ch in candidate)
                    or len(candidate.split()) >= 2
                ):
                    key = candidate.lower()
                    if key not in seen:
                        seen.add(key)
                        phrases.append(candidate)
                    break
        else:
            # Fallback: take the whole fragment
            key = frag.lower()
            if key not in seen:
                seen.add(key)
                phrases.append(frag)
    return phrases[:max_phrases]


def _pick_best_phrase(phrases: list[str]) -> str:
    """Pick the most distinctive phrase."""
    if not phrases:
        return ""
    # Prefer phrases that contain a number (e.g., "34th") and a state name
    def score(p: str) -> int:
        s = 0
        if any(ch.isdigit() for ch in p):
            s += 10
        # Words that suggest state names (long, capitalized)
        words = p.split()
        capitalized = [w for w in words if w[0:1].isupper()]
        if len(capitalized) >= 2:
            s += 5
        # Penalty for very short phrases
        if len(p) < 5:
            s -= 10
        return s
    return max(phrases, key=score)


def strategy_regiment_bio(first, middle, last, regiment, death_year):
    """F2: Use regiment as bio keyword.

    Adds regiment phrase to bio= URL param so FaG only returns
    memorials that mention that regiment in their bio. Highly
    selective — many false positives eliminated.
    """
    if not first or not last:
        return None
    phrases = extract_regiment_phrases(regiment)
    if not phrases:
        return None
    best = _pick_best_phrase(phrases)
    if not best:
        return None
    return {
        "firstname": first,
        "lastname": last,
        "bio": best,
        "isVeteran": "true",
    }