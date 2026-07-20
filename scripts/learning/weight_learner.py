"""Pairwise weight learner (#60) — learns scoring weights from
reviewer pick-vs-rank comparisons.

When a reviewer picks candidate #3 (score 0.45) instead of #1 (score 0.82),
the feature deltas between them reveal which evidence the scorer overvalues.
This module learns corrected weights from those pairwise comparisons.

Algorithm: for each pensioner with a picked candidate at rank > 1,
build a pair (picked, higher_ranked_rejected). Label picked=1, rejected=0.
Fit logistic regression on feature delta vectors. Output coefficients
become corrected weights.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Feature names in the scorer's evidence breakdown (common names).
FEATURE_NAMES = [
    "last_name",
    "first_name",
    "middle_name",
    "year_window",
    "state",
    "ok_burial",
    "veteran",
]

# Default weights from scoring_constants / fag/scoring.py
DEFAULT_WEIGHTS: dict[str, float] = {
    "last_name": 1.0,
    "first_name": 1.0,
    "middle_name": 1.0,
    "year_window": 0.5,
    "state": 0.1,
    "ok_burial": 0.3,
    "veteran": 0.8,
}


@dataclass
class PairwiseExample:
    """One training pair: picked candidate vs higher-ranked rejected."""
    pensioner_id: int
    picked_features: dict[str, float]
    rejected_features: dict[str, float]
    picked_rank: int = 1
    picked_strategy: str = ""


@dataclass
class LearnedWeights:
    """Learned feature weights from pairwise comparisons."""
    weights: dict[str, float] = field(default_factory=dict)
    trained_at: str = ""
    pair_count: int = 0
    feature_count: int = 0

    def to_dict(self) -> dict:
        return {
            "weights": self.weights,
            "trained_at": self.trained_at,
            "pair_count": self.pair_count,
            "feature_count": self.feature_count,
        }

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "LearnedWeights":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            weights=raw.get("weights", {}),
            trained_at=raw.get("trained_at", ""),
            pair_count=raw.get("pair_count", 0),
            feature_count=raw.get("feature_count", 0),
        )


class PairwiseWeightLearner:
    """Learns corrected feature weights from pairwise comparisons.

    For each pensioner where the reviewer picked a candidate ranked >1,
    we compare the picked candidate's features against each
    higher-ranked-but-rejected candidate's features. The difference
    vectors are fed to logistic regression.

    Features where rejected consistently outscores picked are
    overweighted by the scorer → downweight.
    Features where picked outscores rejected are underweighted → upweight.
    """

    def __init__(self, default_weights: dict[str, float] | None = None) -> None:
        self._defaults = dict(default_weights or DEFAULT_WEIGHTS)
        self._pairs: list[PairwiseExample] = []

    @property
    def pair_count(self) -> int:
        return len(self._pairs)

    def add_pair(
        self,
        pensioner_id: int,
        picked_features: dict[str, float],
        rejected_features: dict[str, float],
        picked_rank: int = 1,
        picked_strategy: str = "",
    ) -> None:
        """Add one training pair."""
        self._pairs.append(PairwiseExample(
            pensioner_id=pensioner_id,
            picked_features=dict(picked_features),
            rejected_features=dict(rejected_features),
            picked_rank=picked_rank,
            picked_strategy=picked_strategy,
        ))

    def extract_pairs_from_labels(
        self,
        labels: list[dict[str, Any]],
    ) -> int:
        """Extract training pairs from scraper export labels (#54).

        Each label dict may carry:
          - _picked_rank: rank of picked candidate (>1 means scorer ranked wrong)
          - _feature_deltas: {feature_name: delta} between picked and #1
          - _winning_strategy: which strategy found the pick
          - _picked_score, _top_score: scores
          - human_review_decision: must be 'accepted'

        When _picked_rank > 1, the delta between picked and #1 tells us
        what the scorer got wrong. Positive delta means picked had MORE
        evidence on that feature than #1 — scorer undervalued it.
        Negative delta means picked had LESS evidence — scorer overvalued it.
        """
        count = 0
        for label in labels:
            if label.get("human_review_decision") != "accepted":
                continue
            rank = label.get("_picked_rank", 1)
            if not rank or rank <= 1:
                continue
            deltas = label.get("_feature_deltas", {})
            if not deltas:
                continue
            pid = label.get("pensioner_id") or label.get("_source_pensioner_id", 0)

            # picked_features = baseline + delta (positive delta = picked had more)
            # rejected_features = baseline (the #1 candidate's features)
            # We reconstruct: rejected had the baseline, picked had baseline + delta.
            # For learning, we use the raw features: rejected is the #1 candidate.
            picked: dict[str, float] = {}
            rejected: dict[str, float] = {}
            for feat in FEATURE_NAMES:
                delta = deltas.get(feat, 0.0)
                # Since we only have deltas, we set baseline=0.5 for all features
                # and let the delta encode the difference.
                baseline = 0.5
                # Positive delta: picked had MORE evidence
                picked[feat] = baseline + delta
                # Negative delta: rejected (rank 1) had MORE evidence
                rejected[feat] = baseline
                if delta < 0:
                    rejected[feat] = baseline + abs(delta)

            self.add_pair(
                pensioner_id=int(pid),
                picked_features=picked,
                rejected_features=rejected,
                picked_rank=rank,
                picked_strategy=label.get("_winning_strategy", ""),
            )
            count += 1
        return count

    def learn(self) -> LearnedWeights:
        """Fit logistic regression on pairwise deltas, return corrected weights.

        Uses a simple logistic regression on per-feature delta vectors.
        The coefficient for each feature indicates how strongly that feature
        predicts the pick when it differs from the rejected candidate.

        Returns:
            LearnedWeights with updated weights reflecting feature importance.
        """
        import time

        if not self._pairs:
            return LearnedWeights(weights=dict(self._defaults))

        # Build feature delta vectors and labels
        n_features = len(FEATURE_NAMES)
        xs: list[list[float]] = []  # per-pair feature vectors
        ys: list[float] = []       # 1.0 for picked (always picked in our pairs)

        for pair in self._pairs:
            row = []
            # Feature vector: delta per feature + intercept bias
            for feat in FEATURE_NAMES:
                picked_val = pair.picked_features.get(feat, 0.0)
                rejected_val = pair.rejected_features.get(feat, 0.0)
                delta = picked_val - rejected_val
                row.append(delta)
            row.append(1.0)  # bias term
            xs.append(row)
            ys.append(1.0)  # picked is always the positive class

        if not xs:
            return LearnedWeights(weights=dict(self._defaults))

        # Negative class: zero vector (no advantage over self)
        for _ in range(len(xs)):
            neg_row = [0.0] * (n_features + 1)
            neg_row[-1] = 1.0  # bias
            xs.append(neg_row)
            ys.append(0.0)

        # Simple logistic regression via gradient descent
        m = n_features + 1  # features + bias
        coeffs = [0.0] * m
        lr = 0.1
        for _ in range(100):
            grad = [0.0] * m
            for i in range(len(xs)):
                logit = sum(coeffs[j] * xs[i][j] for j in range(m))
                # Clamp to avoid overflow
                logit = max(-20.0, min(20.0, logit))
                prob = 1.0 / (1.0 + math.exp(-logit))
                err = prob - ys[i]
                for j in range(m):
                    grad[j] += err * xs[i][j]
            for j in range(m):
                coeffs[j] -= lr * grad[j] / len(xs)

        # Convert coefficients to weights.
        # Positive coeff → feature helps predict the pick → upweight.
        # Negative coeff → feature doesn't help → downweight.
        # Clamp to [0.1, 2.0] and normalize.
        raw_weights: dict[str, float] = {}
        for i, feat in enumerate(FEATURE_NAMES):
            raw_weights[feat] = max(0.1, min(2.0, self._defaults.get(feat, 1.0) + coeffs[i] * 2.0))

        # Normalize so max weight is 2.0
        max_w = max(raw_weights.values()) if raw_weights else 1.0
        if max_w > 0:
            for feat in raw_weights:
                raw_weights[feat] = round(raw_weights[feat] / max_w * 2.0, 4)

        return LearnedWeights(
            weights=raw_weights,
            trained_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            pair_count=len(self._pairs),
            feature_count=n_features,
        )
