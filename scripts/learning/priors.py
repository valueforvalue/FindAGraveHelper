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

    # ------------------------------------------------------------------
    # Self-learning (issue #54): update priors from reviewer decisions
    # ------------------------------------------------------------------

    def update_from_labels(
        self,
        labels: list[Any],  # list[LabelSnapshot]
        label_features: list[dict[str, Any]] | None = None,
        strategy_stats: dict[str, dict[str, int]] | None = None,
    ) -> None:
        """Update priors from accumulated reviewer decisions.

        Args:
            labels: list of LabelSnapshot with human_review_decision.
            label_features: optional per-label feature dicts with
                best_score, winning_strategy, feature_deltas, etc.
            strategy_stats: optional per-strategy counts:
                {strategy_name: {total: N, accepted: M, top1: K}}.
        """
        import time

        self.trained_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.training_label_count = len(labels)

        # Update match probability calibration from (score, accepted) pairs.
        if label_features:
            calibration: list[tuple[float, float]] = []
            for feat in label_features:
                score = float(feat.get("best_score", 0.0))
                accepted = 1.0 if feat.get("accepted") else 0.0
                calibration.append((score, accepted))
            if calibration:
                calibration.sort()
                # Bin into deciles and average
                n = len(calibration)
                binned: list[tuple[float, float]] = []
                for i in range(10):
                    lo = i * n // 10
                    hi = (i + 1) * n // 10
                    if lo >= hi:
                        continue
                    chunk = calibration[lo:hi]
                    avg_score = sum(s for s, _ in chunk) / len(chunk)
                    avg_prob = sum(a for _, a in chunk) / len(chunk)
                    binned.append((round(avg_score, 3), round(avg_prob, 3)))
                if binned:
                    self._match_calibration = binned

        # Update strategy utility from per-strategy stats.
        if strategy_stats:
            for name, stats in strategy_stats.items():
                total = stats.get("total", 0)
                accepted = stats.get("accepted", 0)
                top1 = stats.get("top1", 0)
                if total > 0:
                    # Weight: accepted count weighted by top1 ratio
                    # (top1 picks are stronger evidence than rank-N picks)
                    utility = (accepted / total) * (0.5 + 0.5 * (top1 / max(accepted, 1)))
                    self._strategy_utility[name] = round(utility, 4)

    def save(self, path: str | Path) -> None:
        """Persist priors to a JSON file."""
        import json
        from pathlib import Path
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        d = {
            "policy_version": self.policy_version,
            "trained_at": self.trained_at,
            "training_label_count": self.training_label_count,
            "source_labels": self.source_labels,
            "_state_priors": {k: list(v) for k, v in self._state_priors.items()},
            "_texas_evidence": dict(self._texas_evidence),
            "_strategy_utility": dict(self._strategy_utility),
            "_match_calibration": list(self._match_calibration),
        }
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "PriorRegistry":
        """Load priors from a JSON file."""
        import json
        from pathlib import Path
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        reg = cls(
            policy_version=raw.get("policy_version", "1"),
            trained_at=raw.get("trained_at", ""),
            training_label_count=raw.get("training_label_count", 0),
            source_labels=raw.get("source_labels", []),
        )
        reg._state_priors = {k: [(s, float(p)) for s, p in v] for k, v in raw.get("_state_priors", {}).items()}
        reg._texas_evidence = {k: float(v) for k, v in raw.get("_texas_evidence", {}).items()}
        reg._strategy_utility = {k: float(v) for k, v in raw.get("_strategy_utility", {}).items()}
        reg._match_calibration = [(float(s), float(p)) for s, p in raw.get("_match_calibration", [])]
        return reg
