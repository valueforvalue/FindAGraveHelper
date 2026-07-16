"""Spouse cross-reference logic.

Given a FaG spouse entry (from extract_spouse) and a unified.json
widow record, decide whether they describe the same family.

The match is strong when:
  - Widow's first name matches FaG spouse's first name (loose: first 3 chars)
  - Widow's last name matches FaG spouse's last name
  - Widow's spouse_name_raw mentions the soldier we're searching for

The match is loose when:
  - Only last name matches (common surname)
  - First name is partial / initial only

The match is None when:
  - Last names differ
  - Or widow has no spouse_name_raw to verify against
"""
from enum import Enum
from typing import Optional


class MatchStrength(Enum):
    STRONG = "strong"
    LOOSE = "loose"


_NICKNAME_RE = __import__("re").compile(r'"([^"]+)"')


def _first_name_match(
    a: str, b: str, raw_a: str = "", raw_b: str = ""
) -> Optional[MatchStrength]:
    """Compare two first names. Returns strong if exact/nickname,
    loose if partial (first 3 chars or initial), None if no match.

    The raw_a / raw_b params let us find nicknames inside quoted
    strings (e.g. 'Fayette J. "Fannie" Rogers').
    """
    a = (a or "").strip().upper()
    b = (b or "").strip().upper()
    if not a or not b:
        return None
    if a == b:
        return MatchStrength.STRONG
    # Nickname in raw_b: e.g. "Fannie" appears in Fayette's raw_name
    if raw_a:
        for nick in _NICKNAME_RE.findall(raw_a):
            if nick.upper() == b:
                return MatchStrength.STRONG
    if raw_b:
        for nick in _NICKNAME_RE.findall(raw_b):
            if nick.upper() == a:
                return MatchStrength.STRONG
    # First 3 chars (handles "Sara" / "Sarah" pairs)
    if len(a) >= 3 and len(b) >= 3 and a[:3] == b[:3]:
        return MatchStrength.LOOSE
    # Initial only
    if a[0] == b[0] and (len(a) == 1 or len(b) == 1):
        return MatchStrength.LOOSE
    return None


def cross_ref_widow_record(
    fag_spouse: dict,
    widow_record: dict,
    soldier_last_name: str,
) -> Optional[dict]:
    """Cross-reference a FaG spouse entry against a unified widow record.

    Returns None if no match, else a dict with:
      - match_strength: 'strong' or 'loose'
      - widow_id: unified record id
      - widow_name: raw_name
      - soldier_in_pension: True if soldier_last_name appears in widow's
        spouse_name_raw
    """
    fag_last = (fag_spouse.get("last_name") or "").strip().upper()
    widow_last = (widow_record.get("last_name") or "").strip().upper()
    if not fag_last or not widow_last:
        return None
    if fag_last != widow_last:
        return None

    # First name match (must be at least loose)
    fname_strength = _first_name_match(
        fag_spouse.get("first_name", ""),
        widow_record.get("first_name", ""),
        fag_spouse.get("raw_name", ""),
        widow_record.get("name_raw", ""),
    )
    if fname_strength is None:
        return None

    # Check that the soldier we're searching for is in the widow's record.
    # If the widow has no spouse_name_raw, we can't verify which soldier
    # she married — fall back to loose match.
    spouse_raw = (widow_record.get("spouse_name_raw") or "").strip().upper()
    soldier_last_upper = (soldier_last_name or "").strip().upper()
    soldier_in_pension = bool(
        spouse_raw and soldier_last_upper and soldier_last_upper in spouse_raw
    )

    if not spouse_raw:
        # Can't verify soldier; only loose match possible.
        return {
            "match_strength": MatchStrength.LOOSE.value,
            "widow_id": widow_record.get("id"),
            "widow_name": widow_record.get("name_raw"),
            "soldier_in_pension": False,
        }

    # Both names match + soldier is in pension record → strong.
    if soldier_in_pension and fname_strength == MatchStrength.STRONG:
        return {
            "match_strength": MatchStrength.STRONG.value,
            "widow_id": widow_record.get("id"),
            "widow_name": widow_record.get("name_raw"),
            "soldier_in_pension": True,
        }

    # Last name matches + soldier is in pension → loose (good enough for
    # a tiebreaker).
    if soldier_in_pension:
        return {
            "match_strength": MatchStrength.LOOSE.value,
            "widow_id": widow_record.get("id"),
            "widow_name": widow_record.get("name_raw"),
            "soldier_in_pension": True,
        }

    # Last name matches but soldier is NOT in pension — likely a
    # different family (widow married multiple times or wrong record).
    return None