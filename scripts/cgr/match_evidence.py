"""CGRMatchEvidence: unified CGR match strength extractor — Phase 3 Slice 3.4.

One shared extractor for CGR corroboration, dedup, and FaG cross-ref.
Uses NameEvidence for name comparison. Returns typed match strength
with explainable dimensions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.matching.name_evidence import NameEvidence

# Match strength buckets
MATCH_STRONG = "strong"
MATCH_MEDIUM = "medium"
MATCH_WEAK = "weak"
MATCH_NONE = "none"


@dataclass
class MatchStrength:
    """Typed match result between a pensioner and CGR record."""

    strength: str = MATCH_NONE  # strong|medium|weak|none
    name_score: float = 0.0
    year_match: bool = False
    unit_match: bool = False
    state_match: bool = False
    year_conflict: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)
    policy_version: str = "1"


class CGRMatchEvidence:
    """Extracts match evidence between pensioner and CGR veteran record."""

    def __init__(self, policy_version: str = "1") -> None:
        self.policy_version = policy_version

    def match_strength(
        self,
        pensioner: dict[str, Any],
        cgr_row: dict[str, Any],
    ) -> MatchStrength:
        """Compute match strength between pensioner and CGR row."""
        p_name = NameEvidence.from_record(pensioner)
        c_name = NameEvidence.from_record({
            "first_name": cgr_row.get("first_name", ""),
            "last_name": cgr_row.get("last_name", ""),
            "middle_name": cgr_row.get("middle_name", ""),
        })

        name_score = p_name.fuzzy_match(c_name)

        # Year comparison
        p_birth = _safe_int(pensioner.get("birth_year"))
        p_death = _safe_int(pensioner.get("death_year"))
        c_birth = _safe_int(cgr_row.get("born"))
        c_death = _safe_int(cgr_row.get("died"))

        year_match = False
        year_conflict = False
        if p_birth and c_birth:
            if abs(p_birth - c_birth) <= 2:
                year_match = True
            elif abs(p_birth - c_birth) > 10:
                year_conflict = True

        # Unit comparison
        p_unit = str(pensioner.get("regiment", "")).lower()
        c_unit = str(cgr_row.get("unit", "")).lower()
        unit_match = bool(p_unit) and bool(c_unit) and (
            p_unit in c_unit or c_unit in p_unit
        )

        # State comparison
        p_state = str(pensioner.get("_state_abbr", "")).upper()
        c_state = str(cgr_row.get("state", "")).upper()
        state_match = bool(p_state) and p_state == c_state

        # Determine strength
        if name_score >= 0.80 and year_match and not year_conflict:
            strength = MATCH_STRONG
        elif name_score >= 0.60 and (year_match or unit_match):
            strength = MATCH_MEDIUM
        elif name_score >= 0.40:
            strength = MATCH_WEAK
        else:
            strength = MATCH_NONE

        # Demote if year conflict
        if year_conflict and strength == MATCH_STRONG:
            strength = MATCH_MEDIUM

        return MatchStrength(
            strength=strength,
            name_score=name_score,
            year_match=year_match,
            unit_match=unit_match,
            state_match=state_match,
            year_conflict=year_conflict,
            evidence={
                "pensioner_name": f"{p_name.first} {p_name.last}",
                "cgr_name": f"{c_name.first} {c_name.last}",
                "pensioner_unit": p_unit,
                "cgr_unit": c_unit,
            },
            policy_version=self.policy_version,
        )

    def same_person(
        self,
        rec_a: dict[str, Any],
        rec_b: dict[str, Any],
    ) -> bool:
        """Return True if two CGR records likely represent the same person."""
        result = self.match_strength(rec_a, rec_b)
        return result.strength == MATCH_STRONG


def _safe_int(val: Any) -> int | None:
    """Parse an int safely, returning None on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
