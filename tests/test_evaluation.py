"""Tests for the confusion-matrix evaluation harness.

A confusion matrix for record linkage has 4 cells:

  |              | Predicted match | Predicted no-match |
  | Actual match | True Positive   | False Negative      |
  | Actual no    | False Positive  | True Negative       |

Metrics derived:
  - Precision = TP / (TP + FP)  — when we say "match", how often right?
  - Recall    = TP / (TP + FN)  — of all true matches, how many found?
  - F1        = 2*P*R / (P+R)   — harmonic mean
  - Accuracy   = (TP+TN) / total

For record linkage, we operate at a THRESHOLD — e.g. score >= 0.75
counts as a match. The harness helps us pick the threshold that
maximizes F1.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.matching.evaluation import (
    ConfusionMatrix,
    compute_confusion_matrix,
    precision,
    recall,
    f1_score,
    best_threshold,
)


# ============================================================
# ConfusionMatrix basic ops
# ============================================================
def test_confusion_matrix_starts_at_zero():
    cm = ConfusionMatrix()
    assert cm.tp == 0
    assert cm.fp == 0
    assert cm.fn == 0
    assert cm.tn == 0


def test_confusion_matrix_total():
    """Total = TP + FP + FN + TN."""
    cm = ConfusionMatrix(tp=5, fp=2, fn=1, tn=10)
    assert cm.total == 18


def test_confusion_matrix_add():
    cm = ConfusionMatrix(tp=1, fp=2, fn=3, tn=4)
    cm.add(ConfusionMatrix(tp=10, fp=20, fn=30, tn=40))
    assert cm.tp == 11
    assert cm.fp == 22
    assert cm.fn == 33
    assert cm.tn == 44


def test_confusion_matrix_repr():
    cm = ConfusionMatrix(tp=5, fp=2, fn=1, tn=10)
    s = repr(cm)
    assert "TP=5" in s
    assert "FP=2" in s


# ============================================================
# compute_confusion_matrix
# ============================================================
def _sample_pairs():
    """Sample (actual_match, predicted_score) pairs."""
    return [
        (True, 0.95),  # match
        (True, 0.85),  # match
        (True, 0.65),  # match
        (False, 0.40), # no match
        (False, 0.20), # no match
    ]


def test_compute_at_high_threshold():
    """Threshold 0.8: only the 0.85 and 0.95 are matches.
    TP=2 (actual=True, pred=match). FP=0. FN=1 (actual=True, pred=no).
    TN=2 (actual=False, pred=no)."""
    pairs = _sample_pairs()
    cm = compute_confusion_matrix(pairs, threshold=0.8)
    assert cm.tp == 2
    assert cm.fp == 0
    assert cm.fn == 1
    assert cm.tn == 2


def test_compute_at_low_threshold():
    """Threshold 0.3: scores 0.95, 0.85, 0.65, 0.40 become matches.
    TP=3 (all 3 actuals predicted match), FP=1 (0.40 with actual=False),
    FN=0, TN=1 (only 0.20 with actual=False stays non-match)."""
    pairs = _sample_pairs()
    cm = compute_confusion_matrix(pairs, threshold=0.3)
    assert cm.tp == 3
    assert cm.fp == 1
    assert cm.fn == 0
    assert cm.tn == 1


def test_compute_at_very_high_threshold():
    """Threshold 0.99: nothing is a match.
    TP=0, FP=0, FN=3, TN=2."""
    pairs = _sample_pairs()
    cm = compute_confusion_matrix(pairs, threshold=0.99)
    assert cm.tp == 0
    assert cm.fp == 0
    assert cm.fn == 3
    assert cm.tn == 2


def test_compute_handles_empty():
    """Empty pairs -> zero matrix."""
    cm = compute_confusion_matrix([], threshold=0.5)
    assert cm.tp == 0
    assert cm.fp == 0


def test_compute_uses_predicted_match():
    """If actual is True but pred < threshold, it's FN."""
    cm = compute_confusion_matrix([(True, 0.5)], threshold=0.7)
    assert cm.fn == 1
    assert cm.tp == 0


def test_compute_uses_actual_match():
    """If actual is False but pred >= threshold, it's FP."""
    cm = compute_confusion_matrix([(False, 0.8)], threshold=0.7)
    assert cm.fp == 1
    assert cm.tn == 0


# ============================================================
# Metrics
# ============================================================
def test_precision_perfect():
    """Precision when no FPs = 1.0."""
    cm = ConfusionMatrix(tp=5, fp=0, fn=3, tn=10)
    assert precision(cm) == 1.0


def test_precision_with_fps():
    cm = ConfusionMatrix(tp=5, fp=5, fn=3, tn=10)
    # 5 / (5+5) = 0.5
    assert precision(cm) == 0.5


def test_precision_zero_denominator():
    """If TP+FP=0, precision is 0 (no predictions made)."""
    cm = ConfusionMatrix(tp=0, fp=0, fn=5, tn=10)
    assert precision(cm) == 0.0


def test_recall_perfect():
    """Recall when no FNs = 1.0."""
    cm = ConfusionMatrix(tp=5, fp=2, fn=0, tn=10)
    assert recall(cm) == 1.0


def test_recall_with_fns():
    cm = ConfusionMatrix(tp=5, fp=2, fn=5, tn=10)
    # 5 / (5+5) = 0.5
    assert recall(cm) == 0.5


def test_recall_zero_denominator():
    """If TP+FN=0, recall is 0 (no actual matches to find)."""
    cm = ConfusionMatrix(tp=0, fp=2, fn=0, tn=10)
    assert recall(cm) == 0.0


def test_f1_balanced():
    """F1 = 2*P*R / (P+R) when P=R."""
    # P=R=0.5 -> F1=0.5
    cm = ConfusionMatrix(tp=5, fp=5, fn=5, tn=5)
    p = precision(cm)
    r = recall(cm)
    assert f1_score(cm) == 2 * p * r / (p + r)


def test_f1_perfect():
    cm = ConfusionMatrix(tp=10, fp=0, fn=0, tn=5)
    assert f1_score(cm) == 1.0


def test_f1_zero():
    cm = ConfusionMatrix(tp=0, fp=5, fn=5, tn=5)
    assert f1_score(cm) == 0.0


def test_f1_handles_zero_precision_recall():
    cm = ConfusionMatrix(tp=0, fp=0, fn=0, tn=10)
    assert f1_score(cm) == 0.0  # no positives, no F1


# ============================================================
# best_threshold
# ============================================================
def test_best_threshold_picks_highest_f1():
    """Given a set of (actual, score) pairs, find the threshold
    that maximizes F1."""
    # Make a clean separation: matches score >= 0.7, non-matches < 0.7
    pairs = [
        (True, 0.95), (True, 0.90), (True, 0.85), (True, 0.80),
        (False, 0.50), (False, 0.40), (False, 0.30), (False, 0.20),
    ]
    result = best_threshold(pairs)
    # The threshold should be somewhere between 0.50 and 0.80
    assert 0.5 <= result.threshold <= 0.85
    # F1 should be 1.0 (perfect separation)
    assert result.f1 == 1.0
    # Precision and recall should be 1.0
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_best_threshold_with_overlap():
    """When scores overlap, the threshold is a compromise."""
    pairs = [
        (True, 0.9), (True, 0.6),  # one clear, one borderline
        (False, 0.7), (False, 0.4),  # one borderline, one clear no
    ]
    result = best_threshold(pairs)
    # No threshold gives perfect F1; we just get the best one
    assert 0.0 < result.f1 < 1.0


def test_best_threshold_handles_empty():
    result = best_threshold([])
    assert result.threshold == 0.0
    assert result.f1 == 0.0


def test_best_threshold_explores_range():
    """best_threshold tests multiple thresholds, not just one."""
    pairs = [
        (True, 0.95), (True, 0.85),
        (False, 0.50), (False, 0.40),
    ]
    result = best_threshold(pairs)
    # We expect it to find threshold around 0.65-0.85
    assert result.threshold > 0.5


def test_best_threshold_with_named_result():
    """The result has threshold, precision, recall, f1 fields."""
    from scripts.matching.evaluation import ThresholdResult
    result = best_threshold([(True, 0.9), (False, 0.1)])
    assert isinstance(result, ThresholdResult)
    assert hasattr(result, "threshold")
    assert hasattr(result, "precision")
    assert hasattr(result, "recall")
    assert hasattr(result, "f1")
    assert hasattr(result, "confusion_matrix")


# ============================================================
# Integration: evaluate the actual search_fag.py harness
# ============================================================
def test_evaluate_against_ground_truth():
    """Run the searcher against ground truth, evaluate with confusion matrix."""
    # Simulated: 5 predictions, 4 are correct
    predictions = [
        (True, 0.95),  # actual match, predicted match
        (True, 0.85),  # actual match, predicted match
        (True, 0.65),  # actual match, predicted no-match (below threshold)
        (False, 0.40), # actual no-match, predicted no-match
        (False, 0.20), # actual no-match, predicted no-match
    ]
    cm = compute_confusion_matrix(predictions, threshold=0.7)
    p = precision(cm)  # 2/(2+0) = 1.0
    r = recall(cm)     # 2/(2+1) = 0.67
    f1 = f1_score(cm)  # 2*1*0.67/(1+0.67) = 0.80
    assert p == 1.0
    assert abs(r - 2/3) < 0.01
    assert abs(f1 - 0.80) < 0.01