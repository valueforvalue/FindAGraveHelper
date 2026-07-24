"""End-to-end test: run the full searcher on ground truth,
evaluate with the confusion matrix.

This is the integration test that proves our improvements
work. It runs the actual searcher (with all the new
algorithms) on the actual ground truth (576 records from
dixiedata) and measures precision/recall/F1.

The searcher is run ONCE per session, then multiple assertions
read the same state file. (Running the searcher 4 times would
take 12+ min for the same data.)
"""
import csv
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.matching.evaluation import (
    ConfusionMatrix,
    compute_confusion_matrix,
    best_threshold,
)


GT_CSV = Path("C:/tmp/ground_truth.csv")
GT_OUT_DIR = Path("C:/tmp/fag_gt_e2e")
GT_STATE = GT_OUT_DIR / "results.jsonl"  # current CLI writes results.jsonl

# Per-test skipif: the e2e tests need (a) the operator-downloaded
# ground-truth CSV at C:/tmp/ground_truth.csv and (b) a real FaG
# session. The smoke test in this module uses a tiny fixture CSV
# (tests/fixtures/ground_truth_smoke.csv) and runs no live searcher.
# Issue #91.
REQUIRES_OPERATOR_GT = pytest.mark.skipif(
    not GT_CSV.exists(),
    reason=(
        f"{GT_CSV} not present. Download the operator ground-truth "
        f"CSV (see issue #91 and "
        f"docs/learnings/2026-07-22-e2e-gt-skip.md) to enable the "
        f"live e2e tests in this module."
    ),
)


def _load_ground_truth():
    """Load the ground-truth CSV (576 records)."""
    return list(csv.DictReader(open(GT_CSV, encoding="utf-8")))


def _ensure_searcher_run():
    """Run the searcher ONCE per session. Subsequent calls are no-ops.

    This is critical: the searcher takes 2-3 min per run, and we
    have 4+ assertions in this file. We use a sentinel file to
    detect whether the state file is "fresh" (just generated) or
    stale (from a previous test run).
    """
    import subprocess
    sentinel = GT_STATE.with_suffix(".e2e_sentinel")
    if sentinel.exists():
        return  # already ran in this session
    # Clean up any prior run output so we start fresh.
    if GT_STATE.exists():
        GT_STATE.unlink()
    if GT_OUT_DIR.exists():
        import shutil
        shutil.rmtree(GT_OUT_DIR, ignore_errors=True)
    result = subprocess.run(
        [
            "python", "scripts/run_unified.py",
            "--input-csv", str(GT_CSV),
            "--out", str(GT_OUT_DIR),
            "--limit", "50",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,  # 10 min
    )
    if result.returncode != 0:
        pytest.fail(f"Searcher failed: {result.stderr[-500:]}")
    sentinel.touch()


def _load_state():
    """Load the state file (one JSON per line)."""
    return [json.loads(l) for l in open(GT_STATE, encoding="utf-8")]


def _build_pairs(state):
    """Build (actual_match, predicted_score) pairs from state records.

    actual_match: True if the top-ranked candidate (if any) matches
                  the ground truth
    predicted_score: the best_score from the state record
    """
    pairs = []
    for r in state:
        gt = r.get("ground_truth", {})
        actual = gt.get("found", False)
        score = r.get("best_score", 0.0)
        pairs.append((actual, score))
    return pairs


@pytest.fixture(scope="module")
def state_records():
    """Module-scoped fixture: run the searcher once, share results."""
    _ensure_searcher_run()
    return _load_state()


@REQUIRES_OPERATOR_GT
def test_e2e_searcher_evaluates_with_confusion_matrix(state_records):
    """End-to-end: run the searcher, evaluate precision/recall/F1."""
    pairs = _build_pairs(state_records)
    assert len(pairs) == 50

    result = best_threshold(pairs, metric="f1")
    print(f"\nBest threshold: {result.threshold:.3f}")
    print(f"Precision: {result.precision:.3f}")
    print(f"Recall: {result.recall:.3f}")
    print(f"F1: {result.f1:.3f}")
    print(f"Confusion matrix: {result.confusion_matrix}")

    assert result.f1 > 0.5


@REQUIRES_OPERATOR_GT
def test_e2e_rank1_hit_rate(state_records):
    """Of the 50 ground-truth records, how many have the right
    answer at rank 1?"""
    hit1 = sum(1 for r in state_records if r.get("ground_truth", {}).get("rank") == 1)
    print(f"\nRank-1 hits: {hit1}/50 = {hit1/50*100:.1f}%")
    assert hit1 >= 35


@REQUIRES_OPERATOR_GT
def test_e2e_auto_accept_precision(state_records):
    """Of the auto-accepts, how many are correct?"""
    auto = [r for r in state_records if r["status"] == "auto_accept"]
    if not auto:
        pytest.skip("No auto-accepts in this run")
    correct = sum(1 for r in auto if r.get("ground_truth", {}).get("rank") == 1)
    precision = correct / len(auto) if auto else 0
    print(f"\nAuto-accept precision: {correct}/{len(auto)} = {precision*100:.1f}%")
    assert precision >= 0.7


@REQUIRES_OPERATOR_GT
def test_e2e_in_top_5(state_records):
    """What fraction of correct answers are in top 5?"""
    top5 = sum(
        1 for r in state_records
        if 0 < r.get("ground_truth", {}).get("rank", 99) <= 5
    )
    print(f"\nTop-5 hits: {top5}/50 = {top5/50*100:.1f}%")
    assert top5 >= 35


# ------------------------------------------------------------
# Smoke test: exercise the evaluation helpers with the bundled
# fixture CSV. Runs with no operator data and no live FaG, so
# it always collects and passes. Pin for the evaluation plumbing
# only — do NOT assert precision/recall thresholds here.
# (Issue #91.)
# ------------------------------------------------------------

SMOKE_FIXTURE_CSV = (
    Path(__file__).parent / "fixtures" / "ground_truth_smoke.csv"
)


def test_e2e_smoke_evaluation_helpers_with_fixture():
    """Bundled 3-row fixture exercises compute_confusion_matrix
    and best_threshold. No live FaG required; the operator
    ground-truth CSV is not needed for this case."""
    rows = list(csv.DictReader(open(SMOKE_FIXTURE_CSV, encoding="utf-8")))
    assert len(rows) == 3
    assert all("memorial_id" in r for r in rows)

    # Synthesize (actual, score) pairs from the fixture rows.
    pairs = [
        (True, 0.95),   # rank-1 match
        (False, 0.30),  # wrong match
        (True, 0.10),   # miss
    ]
    cm = compute_confusion_matrix(pairs, threshold=0.5)
    assert cm.tp == 1
    assert cm.fp == 0
    assert cm.fn == 1
    assert cm.tn == 1

    result = best_threshold(pairs, metric="f1")
    assert 0.0 <= result.threshold <= 1.0
    assert 0.0 <= result.precision <= 1.0
    assert 0.0 <= result.recall <= 1.0
    assert 0.0 <= result.f1 <= 1.0