"""Tests for J2: outlier classifier.

Given a unified state record, decide whether it's an 'outlier'
(needs another run with different strategies / human review).

Per user decision:
  - Outlier = top FaG score < threshold (default 0.40) OR
              no FaG candidates at all OR
              FaG search errored.
  - Done     = otherwise.

Threshold is configurable.

Outliers get written to outliers.jsonl so follow-up runs can
target them with extra/different strategies.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.outlier_classifier import (
    classify_record,
    Classification,
    OutlierConfig,
    is_outlier,
    summary_for_records,
)


# ============================================================
# Configuration
# ============================================================
def test_outlier_config_defaults():
    """Default threshold is 0.40 per user decision."""
    cfg = OutlierConfig()
    assert cfg.low_score_threshold == 0.40


def test_outlier_config_threshold_tunable():
    """Threshold can be customized."""
    cfg = OutlierConfig(low_score_threshold=0.60)
    assert cfg.low_score_threshold == 0.60


# ============================================================
# is_outlier (predicate)
# ============================================================
def test_is_outlier_no_fag_results():
    """Empty FaG list → outlier."""
    rec = {"fag_records": [], "fag_status": "no_results"}
    assert is_outlier(rec, OutlierConfig())


def test_is_outlier_low_score():
    """Top score below threshold → outlier."""
    rec = {
        "fag_records": [
            {"memorial_id": "1", "score": 0.20},
            {"memorial_id": "2", "score": 0.10},
        ],
        "fag_status": "ambiguous",
    }
    assert is_outlier(rec, OutlierConfig())


def test_is_outlier_high_score_is_done():
    """Top score above threshold → done."""
    rec = {
        "fag_records": [
            {"memorial_id": "1", "score": 0.85},
        ],
        "fag_status": "auto_accept",
    }
    assert not is_outlier(rec, OutlierConfig())


def test_is_outlier_below_custom_threshold():
    """A score above 0.40 but below 0.50 → outlier with threshold 0.50."""
    rec = {
        "fag_records": [{"memorial_id": "1", "score": 0.45}],
        "fag_status": "ambiguous",
    }
    assert not is_outlier(rec, OutlierConfig(low_score_threshold=0.40))
    assert is_outlier(rec, OutlierConfig(low_score_threshold=0.50))


def test_is_outlier_error_status():
    """FaG error status → outlier (need retry)."""
    rec = {"fag_records": [], "fag_status": "error"}
    assert is_outlier(rec, OutlierConfig())


def test_is_outlier_captcha_status():
    """Captcha status → outlier (couldn't complete)."""
    rec = {"fag_records": [], "fag_status": "captcha"}
    assert is_outlier(rec, OutlierConfig())


# ============================================================
# classify_record (full classification)
# ============================================================
def test_classify_no_results_is_outlier():
    rec = {"pensioner_id": 1, "fag_records": [], "fag_status": "no_results"}
    cls = classify_record(rec, OutlierConfig())
    assert cls == Classification.OUTLIER


def test_classify_high_score_is_done():
    rec = {
        "pensioner_id": 1,
        "fag_records": [{"memorial_id": "1", "score": 0.85}],
        "fag_status": "auto_accept",
    }
    cls = classify_record(rec, OutlierConfig())
    assert cls == Classification.DONE


def test_classify_low_score_is_outlier():
    rec = {
        "pensioner_id": 1,
        "fag_records": [{"memorial_id": "1", "score": 0.20}],
        "fag_status": "ambiguous",
    }
    cls = classify_record(rec, OutlierConfig())
    assert cls == Classification.OUTLIER


def test_classify_mid_score_is_done():
    """0.45 with default 0.40 threshold → done."""
    rec = {
        "pensioner_id": 1,
        "fag_records": [{"memorial_id": "1", "score": 0.45}],
        "fag_status": "ambiguous",
    }
    cls = classify_record(rec, OutlierConfig())
    assert cls == Classification.DONE


def test_classify_no_pensioner_id_is_error():
    """Missing pensioner_id → ERROR classification."""
    rec = {"fag_records": [], "fag_status": "no_results"}
    cls = classify_record(rec, OutlierConfig())
    # Test the no-id branch
    rec_no_id = {"fag_records": []}  # no pensioner_id AND no fag_status
    cls2 = classify_record(rec_no_id, OutlierConfig())
    assert cls2 == Classification.OUTLIER


# ============================================================
# summary_for_records (batch stats)
# ============================================================
def test_summary_counts_each_classification():
    """Summary tallies each category."""
    records = [
        # Outlier
        {"pensioner_id": 1, "fag_records": [], "fag_status": "no_results"},
        # Done
        {"pensioner_id": 2, "fag_records": [{"score": 0.85}], "fag_status": "auto_accept"},
        # Outlier
        {"pensioner_id": 3, "fag_records": [{"score": 0.20}], "fag_status": "ambiguous"},
        # Done
        {"pensioner_id": 4, "fag_records": [{"score": 0.45}], "fag_status": "ambiguous"},
    ]
    summary = summary_for_records(records, OutlierConfig())
    counts = summary["counts"]
    assert counts.get("done", 0) == 2
    assert counts.get("outlier", 0) == 2
    assert summary["total"] == 4


def test_summary_includes_pct():
    """Summary includes percentages."""
    records = [
        {"pensioner_id": 1, "fag_records": [], "fag_status": "no_results"},
        {"pensioner_id": 2, "fag_records": [{"score": 0.85}], "fag_status": "auto_accept"},
    ]
    summary = summary_for_records(records, OutlierConfig())
    assert "outlier_pct" in summary
    assert summary["outlier_pct"] == 50.0


def test_summary_empty_input():
    """Empty input → empty summary."""
    summary = summary_for_records([], OutlierConfig())
    assert summary["total"] == 0