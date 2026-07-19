"""Versioned priors for adaptive plan ranking — Phase 8 Slice 8.1.

Deterministic lookup tables for:
  - state_likelihood: ordered state probabilities from regiment/unit text
  - texas_likelihood: probability of Texas relevance from migration evidence
  - strategy_usefulness: expected information gain per strategy category
  - match_probability: calibrated probability from scored features

Each prior carries policy_version, trained_at, training_label_count,
and source_labels for provenance. Default priors are Python literals
(no model file dependency).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PriorRegistry:
    """Versioned collection of priors for plan ranking."""

    policy_version: str = "1"
    trained_at: str = ""
    training_label_count: int = 0
    source_labels: list[str] = field(default_factory=list)

    #: Ordered state probabilities by regiment keyword
    _state_priors: dict[str, list[tuple[str, float]]] = field(default_factory=dict)

    #: Texas migration evidence weights
    _texas_evidence: dict[str, float] = field(default_factory=dict)

    #: Strategy usefulness by (data_shape, target_evidence)
    _strategy_utility: dict[str, float] = field(default_factory=dict)

    #: Match probability calibration points
    _match_calibration: list[tuple[float, float]] = field(
        default_factory=list
    )  # (score, probability)

    @classmethod
    def default(cls) -> "PriorRegistry":
        """Factory with built-in defaults for Confederate pensioner domain."""
        reg = cls(policy_version="1")

        # State likelihood from regiment keywords
        reg._state_priors = {
            "alabama": [("AL", 0.90), ("MS", 0.05), ("GA", 0.03), ("US", 0.02)],
            "arkansas": [("AR", 0.85), ("OK", 0.08), ("TX", 0.04), ("US", 0.03)],
            "florida": [("FL", 0.90), ("GA", 0.05), ("AL", 0.03), ("US", 0.02)],
            "georgia": [("GA", 0.88), ("AL", 0.05), ("SC", 0.04), ("US", 0.03)],
            "kentucky": [("KY", 0.80), ("TN", 0.10), ("VA", 0.05), ("US", 0.05)],
            "louisiana": [("LA", 0.85), ("TX", 0.08), ("MS", 0.04), ("US", 0.03)],
            "mississippi": [("MS", 0.85), ("AL", 0.08), ("LA", 0.04), ("US", 0.03)],
            "missouri": [("MO", 0.80), ("AR", 0.10), ("KS", 0.05), ("US", 0.05)],
            "north carolina": [("NC", 0.85), ("SC", 0.08), ("VA", 0.04), ("US", 0.03)],
            "south carolina": [("SC", 0.85), ("NC", 0.08), ("GA", 0.04), ("US", 0.03)],
            "tennessee": [("TN", 0.85), ("KY", 0.08), ("AL", 0.04), ("US", 0.03)],
            "texas": [("TX", 0.85), ("LA", 0.08), ("AR", 0.04), ("US", 0.03)],
            "virginia": [("VA", 0.85), ("NC", 0.08), ("TN", 0.04), ("US", 0.03)],
        }

        # Texas migration evidence weights
        reg._texas_evidence = {
            "burial_tx": 0.70,
            "notes_texas": 0.60,
            "notes_migrated": 0.50,
            "reconstruction": 0.40,
            "border_state": 0.30,
        }

        # Strategy usefulness (data_shape, target_evidence) -> expected gain
        reg._strategy_utility = {
            ("exact_name", "identity"): 0.90,
            ("exact_name", "veteran"): 0.70,
            ("exact_name", "death_date"): 0.60,
            ("fuzzy_last", "identity"): 0.60,
            ("cw_context", "veteran"): 0.80,
            ("year_sniper", "death_date"): 0.85,
            ("nickname", "identity"): 0.50,
            ("global_fallback", "any"): 0.30,
        }

        # Match probability calibration: (score, probability)
        reg._match_calibration = [
            (0.00, 0.00),
            (0.30, 0.05),
            (0.50, 0.30),
            (0.60, 0.55),
            (0.70, 0.80),
            (0.80, 0.92),
            (0.90, 0.97),
            (1.00, 0.99),
        ]

        return reg

    def state_likelihood(self, regiment: str) -> list[tuple[str, float]]:
        """Ordered state probabilities given regiment text. Falls back to OK."""
        regiment_lower = regiment.lower()
        for state_name, priors in self._state_priors.items():
            if state_name in regiment_lower:
                return priors
        # Default: OK-first since this project targets Oklahoma
        return [("OK", 0.80), ("US", 0.20)]

    def texas_likelihood(self, pensioner: dict[str, Any]) -> float:
        """Probability pensioner has Texas relevance."""
        score = 0.0
        burial = str(pensioner.get("burial_state", "")).upper()
        if burial == "TX":
            score = max(score, self._texas_evidence.get("burial_tx", 0.70))

        notes = str(pensioner.get("notes", "")).lower()
        for hint, weight in self._texas_evidence.items():
            if hint in notes:
                score = max(score, weight)

        return min(score, 0.95)

    def strategy_usefulness(
        self, data_shape: str, target_evidence: str
    ) -> float:
        """Expected information gain for a strategy given data + target."""
        key = (data_shape, target_evidence)
        return self._strategy_utility.get(key, 0.20)

    def match_probability(self, score: float) -> float:
        """Calibrated probability a candidate is correct given its score."""
        if not self._match_calibration:
            return score
        # Linear interpolation between calibration points
        points = sorted(self._match_calibration)
        for i, (s1, p1) in enumerate(points):
            if score <= s1:
                if i == 0:
                    return p1
                s0, p0 = points[i - 1]
                if s1 == s0:
                    return p0
                t = (score - s0) / (s1 - s0)
                return p0 + t * (p1 - p0)
        return points[-1][1]
