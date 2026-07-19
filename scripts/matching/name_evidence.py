"""NameEvidence: typed name model for record linkage — Phase 3 Slice 3.1.

Normalizes names for comparison across FaG, CGR, DixieData, and
pensioner records. Produces explainable evidence that the decision
policy and Fellegi-Sunter matcher consume.

Key properties:
  - Normalized first/middle/last with variant expansion
  - Nickname detection (common Confederate-era diminutives)
  - Slug-shape comparison (FaG memorial URL format)
  - Initial-based fuzzy matching
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Common 19th-century nickname/diminutive mappings
_NICKNAMES: dict[str, list[str]] = {
    "william": ["will", "bill", "billy", "wm"],
    "james": ["jim", "jimmy", "jas"],
    "john": ["johnny", "jack", "jno", "jn"],
    "robert": ["rob", "bob", "bobby", "robt"],
    "thomas": ["tom", "tommy", "thos"],
    "richard": ["rich", "dick", "richd"],
    "charles": ["charlie", "chas"],
    "joseph": ["joe", "jos"],
    "samuel": ["sam", "sammy", "saml"],
    "george": ["geo"],
    "edward": ["ed", "eddie", "edw"],
    "benjamin": ["ben", "benj"],
    "henry": ["hank", "harry"],
    "francis": ["frank", "fran"],
    "frederick": ["fred", "fredk"],
    "alexander": ["alex", "alexr"],
    "andrew": ["andy", "andw"],
    "daniel": ["dan", "danny", "danl"],
    "matthew": ["matt", "mat"],
    "michael": ["mike", "michl"],
    "nathaniel": ["nat", "nathl"],
    "patrick": ["pat", "patk"],
    "peter": ["pete"],
    "theodore": ["ted", "theo"],
    "christopher": ["chris", "christ"],
    "abraham": ["abe", "abrm"],
    "elizabeth": ["lizzie", "liza", "betty", "bess", "eliza"],
    "margaret": ["maggie", "peggy", "margt"],
    "catherine": ["kate", "katie", "cath"],
    "sarah": ["sally", "sadie", "sar"],
    "mary": ["molly", "polly"],
}


@dataclass
class NameEvidence:
    """Normalized name with variant expansion for comparison.

    Produced once per pensioner — stable, versioned, testable.
    """

    first: str = ""
    middle: str = ""
    last: str = ""
    first_normalized: str = ""
    last_normalized: str = ""
    first_variants: list[str] = field(default_factory=list)
    slug_shape: str = ""  # e.g. "john-smith" — expected FaG memorial URL format
    policy_version: str = "1"

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "NameEvidence":
        """Build NameEvidence from a pensioner or candidate record."""
        first = str(record.get("first_name") or record.get("first") or "").strip()
        middle = str(record.get("middle_name") or record.get("middle") or "").strip()
        last = str(record.get("last_name") or record.get("last") or "").strip()

        first_norm = _normalize(first)
        last_norm = _normalize(last)

        variants = [first_norm]
        if first_norm in _NICKNAMES:
            variants.extend(_NICKNAMES[first_norm])

        slug = f"{first_norm}-{last_norm}".replace(" ", "-")

        return cls(
            first=first,
            middle=middle,
            last=last,
            first_normalized=first_norm,
            last_normalized=last_norm,
            first_variants=variants,
            slug_shape=slug,
        )

    def fuzzy_match(self, other: "NameEvidence") -> float:
        """Return 0.0-1.0 similarity score between two NameEvidence instances."""
        score = 0.0

        # Last name is strongest signal
        if self.last_normalized == other.last_normalized:
            score += 0.50
        elif self.last_normalized and other.last_normalized:
            # Partial match (e.g. one is substring of other)
            if self.last_normalized in other.last_normalized or other.last_normalized in self.last_normalized:
                score += 0.25

        # First name
        if self.first_normalized == other.first_normalized:
            score += 0.35
        elif self.first_normalized and other.first_normalized:
            # Nickname match
            if other.first_normalized in self.first_variants:
                score += 0.30
            elif self.first_variants and other.first_variants:
                if set(self.first_variants) & set(other.first_variants):
                    score += 0.30
            # Initial match (e.g. "J" matches "John")
            elif (
                len(self.first_normalized) == 1
                and other.first_normalized.startswith(self.first_normalized)
            ) or (
                len(other.first_normalized) == 1
                and self.first_normalized.startswith(other.first_normalized)
            ):
                score += 0.15

        # Middle initial
        if self.middle and other.middle:
            if (
                self.middle[0].upper() == other.middle[0].upper()
            ):
                score += 0.05

        return min(score, 1.0)


def _normalize(name: str) -> str:
    """Normalize a name: lowercase, strip punctuation, collapse whitespace."""
    import re
    n = name.lower().strip()
    n = re.sub(r"[^a-z\s]", "", n)
    n = re.sub(r"\s+", " ", n)
    return n.strip()
