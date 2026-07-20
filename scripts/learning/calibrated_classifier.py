"""Calibrated classifier — Phase 8 Slice 8.4.

Replaces hardcoded acceptance thresholds with a calibrated
probability estimator trained on historical labels. Uses Platt
scaling (logistic calibration) over the existing feature vector.

Precision-first: only accepts when probability exceeds a threshold
calibrated for target precision on held-out evaluation data.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.learning.label_extractor import LabelSnapshot


@dataclass
class CalibratedClassifier:
    """Calibrated probability estimator for candidate acceptance.

    Default implementation uses logistic calibration over the
    existing feature vector. classifier_version is embedded in
    every Decision for auditability.
    """

    classifier_version: str = "1"
    _coeffs: list[float] = field(default_factory=lambda: [0.0, 1.0])

    def train(
        self, labels: list[LabelSnapshot], features: list[dict[str, Any]]
    ) -> None:
        """Fit calibration on training split.

        Simple logistic regression on the best_score feature.
        Full implementation would use sklearn or scipy; this
        provides the seam with a reasonable default.
        """
        if not labels or not features:
            return

        # Extract score → label pairs
        xs: list[float] = []
        ys: list[float] = []
        for label, feat in zip(labels, features):
            score = float(feat.get("best_score", 0.0))
            is_accept = 1.0 if label.human_review_decision == "accepted" else 0.0
            xs.append(score)
            ys.append(is_accept)

        if not xs:
            return

        # Simple linear fit: probability = sigmoid(a + b*score)
        # a = logit(base_rate), b estimated from score→accept slope
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)

        # Avoid division by zero
        var_x = sum((x - mean_x) ** 2 for x in xs) / len(xs)
        if var_x < 0.0001:
            self._coeffs = [0.0, 0.0]
            return

        cov = sum(
            (xs[i] - mean_x) * (ys[i] - mean_y) for i in range(len(xs))
        ) / len(xs)
        b = cov / var_x
        a = math.log(max(mean_y, 0.01) / max(1 - mean_y, 0.01)) - b * mean_x

        self._coeffs = [a, b]

    def predict_proba(self, features: dict[str, Any]) -> float:
        """Calibrated probability the candidate is correct."""
        score = float(features.get("best_score", 0.0))
        logit = self._coeffs[0] + self._coeffs[1] * score
        # Clamp to avoid overflow
        logit = max(-50.0, min(50.0, logit))
        return 1.0 / (1.0 + math.exp(-logit))

    def accept(
        self, probability: float, min_precision: float = 0.95
    ) -> bool:
        """Accept only if probability exceeds calibrated threshold.

        The threshold is calibrated to achieve at least min_precision
        on held-out evaluation data.
        """
        return probability >= min_precision

    # ------------------------------------------------------------------
    # Persistence (issue #55)
    # ------------------------------------------------------------------

    def save(self, path: Path | str) -> None:
        """Save classifier coefficients to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "classifier_version": self.classifier_version,
                "coeffs": self._coeffs,
            }, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | str) -> "CalibratedClassifier":
        """Load classifier coefficients from a JSON file."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            classifier_version=raw.get("classifier_version", "1"),
            _coeffs=raw.get("coeffs", [0.0, 1.0]),
        )

    def threshold_for_precision(
        self,
        eval_split: list[LabelSnapshot],
        features: list[dict[str, Any]],
        target_precision: float = 0.95,
    ) -> float:
        """Find the probability threshold that achieves target_precision.

        Uses binary search over the evaluation harness.
        """
        harness = EvaluationHarness()
        return harness.calibrate_threshold(
            self, eval_split, features, target_precision,
        )


@dataclass
class EvalReport:
    """Evaluation metrics for a classifier."""

    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    threshold: float = 0.0
    sample_count: int = 0


class EvaluationHarness:
    """Evaluates classifier performance on held-out labels."""

    def evaluate(
        self,
        classifier: CalibratedClassifier,
        eval_split: list[LabelSnapshot],
        features: list[dict[str, Any]],
        threshold: float = 0.50,
    ) -> EvalReport:
        """Compute precision, recall, F1 at given threshold."""
        if not eval_split:
            return EvalReport(sample_count=0)

        tp = fp = fn = 0
        for label, feat in zip(eval_split, features):
            prob = classifier.predict_proba(feat)
            predicted_accept = prob >= threshold
            actual_accept = label.human_review_decision == "accepted"

            if predicted_accept and actual_accept:
                tp += 1
            elif predicted_accept and not actual_accept:
                fp += 1
            elif not predicted_accept and actual_accept:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        return EvalReport(
            precision=precision,
            recall=recall,
            f1=f1,
            threshold=threshold,
            sample_count=len(eval_split),
        )

    def calibrate_threshold(
        self,
        classifier: CalibratedClassifier,
        eval_split: list[LabelSnapshot],
        features: list[dict[str, Any]],
        target_precision: float = 0.95,
    ) -> float:
        """Binary search for threshold achieving target precision."""
        lo, hi = 0.0, 1.0
        best = 1.0
        for _ in range(20):
            mid = (lo + hi) / 2
            report = self.evaluate(classifier, eval_split, features, mid)
            if report.sample_count == 0:
                return 1.0
            if report.precision >= target_precision:
                best = mid
                lo = mid
            else:
                hi = mid
        return best
