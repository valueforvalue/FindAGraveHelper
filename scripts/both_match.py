"""BOTH MATCH detector.

Detects when CGR and FaG both point to the same person, using
two methods (per user decision):

  - direct_link:  CGR record has a findagrave.com URL pointing
                  to a specific memorial that FaG also found.
                  Match is essentially certain.
  - corroboration: CGR + FaG agree on a person by inference —
                   name match + death year within ±2 + burial
                   state OK (the OK burial is allowed to differ
                   since user clarified OK-connected != OK-buried).
                   Match is high-confidence but not certain.

The detector returns a BothMatchResult for view.html to display
with the method clearly labeled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class MatchMethod(Enum):
    """How BOTH MATCH was detected."""
    DIRECT_LINK = "direct_link"
    CORROBORATION = "corroboration"
    NONE = "none"


@dataclass
class BothMatchResult:
    """A BOTH MATCH finding."""
    method: MatchMethod
    cgr_cem_id: str = ""
    fag_memorial_id: str = ""
    reason: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "method": self.method.value,
            "cgr_cem_id": self.cgr_cem_id,
            "fag_memorial_id": self.fag_memorial_id,
            "reason": self.reason,
            "confidence": self.confidence,
        }


# ============================================================
# Year matching helpers
# ============================================================
_YEAR_RE = re.compile(r"\b(\d{4})\b")


def _extract_years(died_str: str) -> list[int]:
    """Pull years from a date string. '1932-02-28' → [1932]."""
    if not died_str:
        return []
    return [int(y) for y in _YEAR_RE.findall(str(died_str))]


def _years_match(died_str1: str, died_str2: str, tolerance: int = 2) -> bool:
    """Two death year strings 'match' if within tolerance."""
    y1 = _extract_years(died_str1)
    y2 = _extract_years(died_str2)
    if not y1 or not y2:
        return False
    return any(abs(a - b) <= tolerance for a in y1 for b in y2)


def _normalise_name(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _names_match(cgr_first: str, cgr_last: str,
                 fag_first: str, fag_last: str) -> bool:
    """Soft name match (exact or fuzzy initial)."""
    cf = _normalise_name(cgr_first)
    cl = _normalise_name(cgr_last)
    ff = _normalise_name(fag_first)
    fl = _normalise_name(fag_last)
    if not cl or not fl:
        return False
    # Last name must match (exact prefix or strong fuzzy)
    last_match = cl == fl or (
        len(cl) > 2 and len(fl) > 2 and (
            cl.startswith(fl[:3]) or fl.startswith(cl[:3])
        )
    )
    first_match = cf == ff or (
        cf and ff and cf[0] == ff[0]
    )
    return last_match and first_match


# ============================================================
# Direct-link check
# ============================================================
def check_direct_link(cgr_link: dict | None, fag_candidate: dict) -> BothMatchResult | None:
    """CGR record has an FaG URL → check if FaG candidate matches."""
    if not cgr_link or not fag_candidate:
        return None
    cgr_id = str(cgr_link.get("memorial_id", ""))
    fag_id = str(fag_candidate.get("memorial_id", ""))
    if cgr_id and fag_id and cgr_id == fag_id:
        return BothMatchResult(
            method=MatchMethod.DIRECT_LINK,
            fag_memorial_id=fag_id,
            reason=f"CGR source contains direct FaG link to memorial {fag_id}",
            confidence=1.0,
        )
    return None


# ============================================================
# Corroboration (inferred match)
# ============================================================
def corroborate(
    cgr_record: dict,
    fag_candidate: dict,
    pensioner: dict | None = None,
) -> BothMatchResult | None:
    """Decide whether CGR + FaG agree on the same person.

    Returns BothMatchResult with confidence based on how much
    corroboration we found, or None.
    """
    # Extract names
    cgr_first = cgr_record.get("cgr_first") or cgr_record.get("first_name") or ""
    cgr_last = cgr_record.get("cgr_last") or cgr_record.get("last_name") or ""
    if (not cgr_first or not cgr_last) and cgr_record.get("cgr_name"):
        parts = cgr_record["cgr_name"].split()
        if not cgr_first:
            cgr_first = parts[0] if parts else ""
        if not cgr_last:
            cgr_last = parts[-1] if len(parts) > 1 else ""
    # FaG candidates have 'name' (full) and 'slug' (parseable)
    fag_name = fag_candidate.get("name", "")
    fag_slug = fag_candidate.get("slug", "")
    fag_first = fag_candidate.get("first_name") or fag_candidate.get("parsed_first") or ""
    fag_last = fag_candidate.get("last_name") or fag_candidate.get("parsed_last") or ""
    if (not fag_first or not fag_last) and (fag_name or fag_slug):
        # Parse from "William Pickney Looney" or "william-pickney-looney"
        if fag_slug:
            parts = fag_slug.split("-")
            if not fag_first:
                fag_first = parts[0] if parts else ""
            if not fag_last:
                fag_last = parts[-1] if len(parts) > 1 else ""
        elif fag_name:
            parts = fag_name.split()
            if not fag_first:
                fag_first = parts[0]
            if not fag_last:
                fag_last = parts[-1] if len(parts) > 1 else ""

    if not _names_match(cgr_first, cgr_last, fag_first, fag_last):
        return None

    # Death year match
    cgr_died = (
        cgr_record.get("died")
        or cgr_record.get("cgr_died")
        or cgr_record.get("died_date")
    )
    fag_died = ""
    if isinstance(fag_candidate.get("details"), dict):
        fag_died = fag_candidate["details"].get("death_year", "") or ""
    elif isinstance(fag_candidate.get("death_year"), str):
        fag_died = fag_candidate["death_year"]

    year_match = _years_match(cgr_died, fag_died, tolerance=2)

    # State match (tied to burial)
    cgr_state = (cgr_record.get("died_state") or "").upper()
    fag_state = ""
    if isinstance(fag_candidate.get("details"), dict):
        # details may have a 'state' sub-key
        fag_state = (fag_candidate["details"].get("state") or "").upper()
    if not fag_state:
        fag_state = (fag_candidate.get("details_state") or "").upper()
    if not fag_state:
        # Try the candidate top-level 'state' or 'burial_state'
        fag_state = (fag_candidate.get("state") or fag_candidate.get("burial_state") or "").upper()
    state_match = bool(cgr_state) and bool(fag_state) and cgr_state == fag_state

    # How strong is the corroboration?
    # If BOTH years are present but disagree beyond tolerance, reject.
    if cgr_died and fag_died and not year_match:
        return None
    if year_match and state_match:
        confidence = 0.95
        reason = "name + death year + burial state all agree"
    elif year_match:
        confidence = 0.80
        reason = "name + death year agree (burial state differs)"
    elif state_match:
        confidence = 0.70
        reason = "name + burial state agree (no death year in CGR)"
    elif cgr_died and not fag_died:
        # FaG has no death year to compare, but name matches
        confidence = 0.60
        reason = "name matches (no death-year corroboration available)"
    elif fag_died and not cgr_died:
        confidence = 0.60
        reason = "name matches (no death-year corroboration available)"
    else:
        return None

    return BothMatchResult(
        method=MatchMethod.CORROBORATION,
        cgr_cem_id=str(cgr_record.get("cemetery_id", "")),
        fag_memorial_id=str(fag_candidate.get("memorial_id", "")),
        reason=reason,
        confidence=confidence,
    )


# ============================================================
# Orchestrator
# ============================================================
def detect_both_match(
    pensioner: dict,
    cgr_records: list[dict],
    fag_records: list[dict],
    fag_link: dict | None = None,
) -> BothMatchResult | None:
    """Detect BOTH MATCH for a pensioner.

    Tries direct link first (highest confidence).
    Falls back to corroboration over the top candidates.
    """
    if not cgr_records or not fag_records:
        return None

    # Try direct link on each FaG candidate
    if fag_link:
        for fag in fag_records:
            result = check_direct_link(fag_link, fag)
            if result:
                return result

    # Corroboration: try strong CGR records first
    strong = [c for c in cgr_records if c.get("match_strength") == "strong"]
    candidates_for_corr = strong if strong else cgr_records

    for cgr in candidates_for_corr:
        for fag in fag_records:  # top ranked first
            result = corroborate(cgr, fag, pensioner)
            if result:
                return result
    return None