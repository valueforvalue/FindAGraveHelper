"""Confusion-matrix evaluation harness for record linkage.

A confusion matrix has 4 cells:

  |              | Predicted match | Predicted no-match |
  | Actual match | True Positive   | False Negative      |
  | Actual no    | False Positive  | True Negative       |

Metrics derived:
  - Precision = TP / (TP + FP)  — when we say "match", how often right?
  - Recall    = TP / (TP + FN)  — of all true matches, how many found?
  - F1        = 2*P*R / (P+R)   — harmonic mean
  - Accuracy   = (TP+TN) / total

For record linkage, we operate at a THRESHOLD — e.g. score >= 0.75
counts as a match. This module helps us pick the threshold that
maximizes F1 (or any other metric) by sweeping candidate thresholds
and computing the matrix at each.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class ConfusionMatrix:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    def add(self, other: "ConfusionMatrix") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn
        self.tn += other.tn

    def __repr__(self) -> str:
        return f"CM(TP={self.tp}, FP={self.fp}, FN={self.fn}, TN={self.tn})"


def compute_confusion_matrix(
    pairs: Iterable[tuple[bool, float]],
    threshold: float,
) -> ConfusionMatrix:
    """Compute the confusion matrix at a given threshold.

    pairs: iterable of (actual_match: bool, predicted_score: float)
    threshold: scores >= threshold count as "predicted match"
    """
    cm = ConfusionMatrix()
    for actual, score in pairs:
        predicted = score >= threshold
        if actual and predicted:
            cm.tp += 1
        elif actual and not predicted:
            cm.fn += 1
        elif not actual and predicted:
            cm.fp += 1
        else:
            cm.tn += 1
    return cm


def precision(cm: ConfusionMatrix) -> float:
    """TP / (TP + FP). 0.0 if no predictions."""
    denom = cm.tp + cm.fp
    if denom == 0:
        return 0.0
    return cm.tp / denom


def recall(cm: ConfusionMatrix) -> float:
    """TP / (TP + FN). 0.0 if no actuals."""
    denom = cm.tp + cm.fn
    if denom == 0:
        return 0.0
    return cm.tp / denom


def f1_score(cm: ConfusionMatrix) -> float:
    """2 * P * R / (P + R). 0.0 if P+R=0."""
    p = precision(cm)
    r = recall(cm)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def accuracy(cm: ConfusionMatrix) -> float:
    """(TP+TN) / total."""
    if cm.total == 0:
        return 0.0
    return (cm.tp + cm.tn) / cm.total


@dataclass
class ThresholdResult:
    threshold: float
    precision: float
    recall: float
    f1: float
    accuracy: float
    confusion_matrix: ConfusionMatrix


def _candidate_thresholds(pairs: Iterable[tuple[bool, float]]) -> list[float]:
    """Generate candidate thresholds from observed scores.

    Returns the unique scores (midpoint between each adjacent pair),
    plus 0.0 and 1.0 as boundary cases.
    """
    scores = sorted({s for _, s in pairs})
    if not scores:
        return [0.5]
    cands = set()
    cands.add(0.0)
    cands.add(1.0)
    for s in scores:
        cands.add(s)
    # Midpoints
    for i in range(len(scores) - 1):
        cands.add((scores[i] + scores[i+1]) / 2)
    return sorted(cands)


def best_threshold(
    pairs: Iterable[tuple[bool, float]],
    metric: str = "f1",
) -> ThresholdResult:
    """Find the threshold that maximizes the given metric (default F1).

    Returns a ThresholdResult with the chosen threshold, the metrics
    at that threshold, and the confusion matrix.
    """
    pairs = list(pairs)
    if not pairs:
        return ThresholdResult(
            threshold=0.0, precision=0.0, recall=0.0, f1=0.0,
            accuracy=0.0, confusion_matrix=ConfusionMatrix(),
        )

    best_result: ThresholdResult | None = None
    for th in _candidate_thresholds(pairs):
        cm = compute_confusion_matrix(pairs, th)
        p = precision(cm)
        r = recall(cm)
        f1 = f1_score(cm)
        acc = accuracy(cm)
        if metric == "f1":
            score = f1
        elif metric == "precision":
            score = p
        elif metric == "recall":
            score = r
        else:
            score = f1
        if best_result is None or score > getattr(best_result, metric if metric != "f1" else "f1"):
            best_result = ThresholdResult(
                threshold=th, precision=p, recall=r, f1=f1,
                accuracy=acc, confusion_matrix=cm,
            )
    return best_result