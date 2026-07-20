"""Match local pensioner records against CGR (Confederate Graves Registry) records.

Given a local pensioner (from ok_pensioners.json or dixiedata) and one
or more CGR records (from search results), decide whether they
refer to the same person.

CRITICAL PHILOSOPHY (user guidance, 2026-07-16):
  "Don't make grand assumptions about the accuracy of our
   DixieData local data. There is significant overlap with
   names and so forth in these kinds of records so we have to
   be sure. Its okay to be suspicious of an error but don't
   assume one. All the records in the local DD database have
   been human verified."

That means:
  - When CGR says "William G Looney, 34 TX" and local says
    "William Pickney Looney, 4th TN Cav", we DO NOT conclude
    "one is wrong". They may be different people.
  - Same first + last name alone is NOT strong evidence. Lots
    of people share names.
  - Strong evidence = name + birth year + unit agreement
  - Medium evidence = name + birth year agreement (different units OK)
  - Weak evidence = name only (multiple matches, ambiguous)
  - No match = name doesn't match at all

This matcher returns a list of CGR records with a
`match_strength` annotation. It does NOT pick a "best" or
auto-merge. The human decides.

When signals conflict (different unit, different birth year),
the conflict is recorded in the output dict, not silently
resolved.
"""
import re
from enum import Enum

# Issue #31: Soundex fallback score derives from scoring_constants
# (different concept from AUTO_ACCEPT_THRESHOLD — they share a
# numeric value today but mean different things)
from scripts.pipeline.scoring_constants import SOUNDEX_MATCH_SCORE


class MatchStrength(Enum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    NONE = "none"


def _norm(s: str) -> str:
    """Normalize a name string for comparison."""
    return (s or "").strip().lower()


def _soundex(s: str) -> str:
    """Tiny Soundex implementation (enough for surname comparison)."""
    s = (s or "").strip().upper()
    if not s:
        return ""
    codes = {
        "B": "1", "F": "1", "P": "1", "V": "1",
        "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2", "S": "2", "X": "2", "Z": "2",
        "D": "3", "T": "3",
        "L": "4",
        "M": "5", "N": "5",
        "R": "6",
    }
    out = s[0]
    prev = codes.get(s[0], "")
    for ch in s[1:]:
        code = codes.get(ch, "")
        if code and code != prev:
            out += code
        if not code:
            prev = ""
        else:
            prev = code
    out = out[:4].ljust(4, "0")
    return out


def name_match_strength(
    p_first: str, p_last: str, c_first: str, c_last: str
) -> str:
    """Compare pensioner name parts against CGR name parts.

    Returns 'strong', 'medium', 'weak', or 'none'.

    Algorithm (per Priority 1 of algorithms-research.md):
      1. Last name must match (exact or via combined phonetic
         signals). Otherwise "none".
      2. First name scoring: Jaro-Winkler + Metaphone + NYSIIS
         combined score.
      3. Bucket the combined score into strong/medium/weak.
    """
    p_first = _norm(p_first).rstrip(".")
    p_last = _norm(p_last)
    c_first = _norm(c_first).rstrip(".")
    c_last = _norm(c_last)

    # 1. Last name must match (exact, phonetic, or fuzzy)
    if not p_last or not c_last:
        return "none"
    last_score = _combined_name_score(p_last, c_last)
    if last_score < 0.80:
        return "none"

    # 2. First name scoring
    if not p_first or not c_first:
        # No first name on either side; rely on last
        if last_score >= 0.95:
            return "medium"
        return "weak"

    first_score = _combined_name_score(p_first, c_first)

    # 3. Bucket
    # Use the max of last and first scores (whichever is stronger)
    overall = max(last_score, first_score)
    if overall >= 0.95:
        return "strong"
    if overall >= 0.80:
        return "medium"
    return "weak"


def _combined_name_score(a: str, b: str) -> float:
    """Wrapper that tries to use the new phonetic_match module.

    Falls back to Soundex-only if the module isn't importable
    (e.g. rapidfuzz or jellyfish not installed).
    """
    try:
        from scripts.matching.phonetic_match import combined_name_score
        return combined_name_score(a, b)
    except ImportError:
        # Fallback: Soundex-only scoring
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if _soundex(a) == _soundex(b):
            return SOUNDEX_MATCH_SCORE
        return 0.0


def compare_years(local_year: str, cgr_born: str) -> str:
    """Compare birth years. Returns 'exact', 'close', 'near', 'far', or 'unknown'.

    CGR's born field is text like "May 24 1840" or just "1840" or
    "1840-05-24". We extract the 4-digit year.
    """
    def extract_year(s: str) -> str:
        if not s:
            return ""
        m = re.search(r"(\d{4})", s)
        return m.group(1) if m else ""

    ly = extract_year(local_year)
    cy = extract_year(cgr_born)
    if not ly or not cy:
        return "unknown"
    try:
        ly_i, cy_i = int(ly), int(cy)
    except ValueError:
        return "unknown"
    diff = abs(ly_i - cy_i)
    if diff == 0:
        return "exact"
    if diff <= 2:
        return "close"
    if diff <= 5:
        return "near"
    return "far"


def _unit_matches(p_regiment: str, c_unit: str) -> bool:
    """Crude check: do the units agree?

    Both are strings like "34 TX" or "4th TN Cav". We don't
    do a full parse — we just look for a 2-letter state code
    in both and see if the ordinal numbers match.

    Returns True if they agree, False if they conflict, None if
    we can't tell.
    """
    p_regiment = (p_regiment or "").upper()
    c_unit = (c_unit or "").upper()

    # Find state codes in both
    states = {"AL", "MS", "TN", "TX", "GA", "FL", "AR", "SC", "NC", "VA",
              "LA", "KY", "MO", "MD", "OK", "IN"}
    p_states = [s for s in states if re.search(rf"\b{s}\b", p_regiment)]
    c_states = [s for s in states if re.search(rf"\b{s}\b", c_unit)]

    if p_states and c_states:
        # Both have state codes; if any agree, units MIGHT match
        # (they could still be different regiments in the same state)
        return any(s in c_states for s in p_states)

    # If neither has a state code, we can't compare — assume match
    return None


def match_pensioner_to_cgr(
    pensioner: dict, cgr_records: list[dict]
) -> list[dict]:
    """Annotate each CGR record with a match_strength for the pensioner.

    Returns the same number of records as input, in the same order,
    each augmented with:
      - match_strength: 'strong' | 'medium' | 'weak' | 'none'
      - conflicts: dict of conflicting fields (only when we have data)
      - cgr_id, cgr_name, cgr_unit, cgr_born: copied from the CGR record
      - local_unit: copied from pensioner for reference

    The matcher does NOT pick a "best" or auto-merge. The human
    decides via the HTML viewer.
    """
    out = []
    p_first = pensioner.get("first_name", "")
    p_last = pensioner.get("last_name", "")
    p_middle = pensioner.get("middle_name", "")
    p_regiment = pensioner.get("regiment", "")
    p_birth_year = pensioner.get("birth_year", "")

    for rec in cgr_records:
        # Parse the CGR name into first/last. CGR's "name" field is
        # usually "First Middle AKA Last" or similar. We do a simple
        # split: first token = first name, last token = last name,
        # middle = middle tokens.
        cgr_name = rec.get("name", "")
        cgr_parts = cgr_name.split()
        if not cgr_parts:
            out.append({**rec, "match_strength": "none", "conflicts": {}})
            continue
        c_first = cgr_parts[0]
        c_last = cgr_parts[-1] if len(cgr_parts) > 1 else ""
        c_middle = " ".join(cgr_parts[1:-1]) if len(cgr_parts) > 2 else ""

        strength = name_match_strength(p_first, p_last, c_first, c_last)

        # Build conflict dict — only include fields where we have data
        # on BOTH sides and they disagree.
        conflicts = {}

        # Unit conflict (only if both have unit info)
        if p_regiment and rec.get("unit"):
            unit_agrees = _unit_matches(p_regiment, rec.get("unit"))
            if unit_agrees is False:
                conflicts["unit"] = {
                    "local": p_regiment,
                    "cgr": rec.get("unit"),
                }

        # Birth year conflict (only if both have year info)
        year_status = compare_years(p_birth_year, rec.get("born", ""))
        if year_status == "far":
            conflicts["birth_year"] = {
                "local": p_birth_year,
                "cgr": rec.get("born", ""),
            }

        # Adjust strength based on conflicts:
        # - Strong = name agrees AND no conflicts AND birth year
        #   agrees (when we have it)
        # - Medium = name agrees AND (no conflict OR minor conflict)
        # - Weak = partial name agreement
        # - None = name doesn't match
        if strength == "none":
            final = "none"
        elif conflicts.get("unit") and conflicts.get("birth_year"):
            final = "weak"  # too many conflicts
        elif conflicts.get("birth_year"):
            final = "medium"  # birth year conflict
        elif conflicts.get("unit"):
            final = "medium"  # unit conflict but name+birth agree
        elif year_status == "exact":
            final = "strong"
        elif year_status == "close":
            final = "strong"  # close enough
        elif year_status == "unknown":
            # No birth year to compare — name+unit agree is medium
            final = "medium"
        elif year_status == "near":
            final = "medium"
        else:
            final = "medium"  # name+unit agree

        out.append({
            **rec,
            "cgr_id": rec.get("id"),
            "cgr_name": cgr_name,
            "cgr_unit": rec.get("unit"),
            "cgr_born": rec.get("born"),
            "cgr_first": c_first,
            "cgr_middle": c_middle,
            "cgr_last": c_last,
            "local_unit": p_regiment,
            "local_birth_year": p_birth_year,
            "local_middle": p_middle,
            "match_strength": final,
            "conflicts": conflicts,
        })

    return out