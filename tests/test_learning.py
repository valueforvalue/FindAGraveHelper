"""Tests for Phase 8 self-learning modules."""

from scripts.learning.priors import PriorRegistry
from scripts.learning.plan_ranker import PlanRanker
from scripts.learning.calibrated_classifier import (
    CalibratedClassifier,
    EvaluationHarness,
    EvalReport,
)
from scripts.learning.label_extractor import (
    LabelExtractor,
    LabelSnapshot,
    LabelStore,
)
from scripts.blackboard.schema import PlanScope, QueryPlan


# ============================================================
# Priors
# ============================================================


def test_priors_default_loads():
    """Default priors load without network or file I/O."""
    reg = PriorRegistry.default()
    assert reg.policy_version == "1"


def test_state_likelihood_returns_ok_for_known_regiment():
    """Known regiment returns state list with first entry."""
    reg = PriorRegistry.default()
    result = reg.state_likelihood("5th Alabama Infantry")
    assert len(result) > 0
    assert result[0][0] == "AL"


def test_state_likelihood_defaults_to_ok():
    """Unknown regiment defaults to OK-first."""
    reg = PriorRegistry.default()
    result = reg.state_likelihood("Some Unknown Unit")
    assert result[0][0] == "OK"


def test_texas_likelihood_no_evidence_returns_low():
    """No evidence -> low Texas probability."""
    reg = PriorRegistry.default()
    prob = reg.texas_likelihood({})
    assert prob < 0.10


def test_texas_likelihood_burial_returns_high():
    """Texas burial -> high probability."""
    reg = PriorRegistry.default()
    prob = reg.texas_likelihood({"burial_state": "TX"})
    assert prob >= 0.60


def test_match_probability_interpolates():
    """match_probability interpolates between calibration points."""
    reg = PriorRegistry.default()
    p = reg.match_probability(0.70)
    assert 0.70 < p < 0.90


# ============================================================
# Plan ranker
# ============================================================


def test_ranker_ok_first():
    """OK-scope plans rank highest for this project."""
    ranker = PlanRanker()
    plans = [
        QueryPlan(plan_id="us", pensioner_id=1, strategy="B1-exact",
                  scope=PlanScope.US, estimated_requests=1),
        QueryPlan(plan_id="ok", pensioner_id=1, strategy="B1-exact",
                  scope=PlanScope.OK, estimated_requests=1),
    ]
    ranked = ranker.rank(plans)
    assert ranked[0].plan_id == "ok"


def test_ranker_respects_budget():
    """Plan ranker truncates to request budget."""
    ranker = PlanRanker()
    plans = [
        QueryPlan(plan_id=f"p{i}", pensioner_id=1, strategy=f"strat-{i}",
                  params={"id": str(i)}, scope=PlanScope.OK, estimated_requests=1)
        for i in range(10)
    ]
    ranked = ranker.rank(plans, request_budget=3)
    assert len(ranked) == 3


def test_ranker_dedup_equivalent_plans():
    """Equivalent plans are deduplicated."""
    ranker = PlanRanker()
    p1 = QueryPlan(plan_id="a", pensioner_id=1, strategy="B1-exact",
                   params={"a": "1"}, scope=PlanScope.OK)
    p2 = QueryPlan(plan_id="b", pensioner_id=1, strategy="B1-exact",
                   params={"a": "1"}, scope=PlanScope.OK)
    ranked = ranker.rank([p1, p2])
    assert len(ranked) == 1


# ============================================================
# Calibrated classifier
# ============================================================


def test_classifier_predict_proba_default():
    """Default (untrained) classifier returns probability."""
    cc = CalibratedClassifier()
    prob = cc.predict_proba({"best_score": 0.80})
    assert 0.0 < prob < 1.0


def test_classifier_accept_threshold():
    """accept() uses min_precision threshold."""
    cc = CalibratedClassifier()
    assert cc.accept(0.96, min_precision=0.95) is True
    assert cc.accept(0.90, min_precision=0.95) is False


def test_classifier_version():
    """Classifier has a version for audit trail."""
    cc = CalibratedClassifier()
    assert cc.classifier_version == "1"


def test_train_on_synthetic_data():
    """Training on synthetic data produces non-zero coefficients."""
    cc = CalibratedClassifier()
    labels = [
        LabelSnapshot(pensioner_id=1, human_review_decision="accepted"),
        LabelSnapshot(pensioner_id=2, human_review_decision="accepted"),
        LabelSnapshot(pensioner_id=3, human_review_decision="rejected"),
        LabelSnapshot(pensioner_id=4, human_review_decision="rejected"),
    ]
    features = [
        {"best_score": 0.90},
        {"best_score": 0.85},
        {"best_score": 0.30},
        {"best_score": 0.20},
    ]
    cc.train(labels, features)
    # High score should give high probability after training
    prob_high = cc.predict_proba({"best_score": 0.90})
    prob_low = cc.predict_proba({"best_score": 0.20})
    assert prob_high > prob_low


def test_evaluation_harness_empty():
    """Empty eval split returns safe defaults."""
    harness = EvaluationHarness()
    cc = CalibratedClassifier()
    report = harness.evaluate(cc, [], [])
    assert report.sample_count == 0


# ============================================================
# Label extraction
# ============================================================


def test_label_extractor(tmp_path):
    """LabelExtractor produces LabelSnapshots from projection rows."""
    extractor = LabelExtractor()
    rows = [
        {"pensioner_id": 1, "status": "auto_accept", "best_score": 0.85},
        {"pensioner_id": 2, "status": "needs_review", "best_score": 0.50,
         "human_decision": "accepted"},
    ]
    labels = extractor.extract(rows)
    assert len(labels) == 2
    assert labels[0].human_review_decision == "unreviewed"
    assert labels[1].human_review_decision == "accepted"


def test_label_store_temporal_split(tmp_path):
    """LabelStore supports temporal train/eval splits."""
    store = LabelStore(tmp_path / "labels.db")
    store.insert_snapshot(
        LabelSnapshot(pensioner_id=1, extracted_at="2026-01-01T00:00:00Z")
    )
    store.insert_snapshot(
        LabelSnapshot(pensioner_id=2, extracted_at="2026-06-01T00:00:00Z")
    )

    train = store.training_split("2026-03-01T00:00:00Z")
    assert len(train) == 1
    assert train[0].pensioner_id == 1

    eval_split = store.evaluation_split("2026-03-01T00:00:00Z")
    assert len(eval_split) == 1
    assert eval_split[0].pensioner_id == 2

    store.close()
