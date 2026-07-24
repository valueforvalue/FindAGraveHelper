"""Tests for the CalibratedDecisionKS + CalibratedClassifier wiring (#96).

Pin:
- `CalibratedClassifier.predict_proba(state_row)` reads `best_score`
  from a state row and returns a calibrated probability in [0, 1].
- The new `CalibratedDecisionKS` reads the existing `ScoreObserved`
  observation, runs the classifier, and emits a `DecisionObserved`
  carrying `calibrated_probability`.
- When no classifier is loaded (no recipe flag), the KS is a
  no-op (still emits DecisionObserved, but with
  `calibrated_probability=None`) — the legacy Fellegi-Sunter
  path runs unchanged.
- The `Decision` dataclass carries the new `calibrated_probability`
  field; existing callers that don't set it see `None` (back-compat).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.blackboard.decision_policy import Decision, classify, DecisionContext
from scripts.blackboard.schema import (
    Kind,
    Observation,
    WorkItem,
    WorkState,
)
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.knowledge.calibrated_decision_ks import CalibratedDecisionKS
from scripts.learning.calibrated_classifier import CalibratedClassifier


# ============================================================
# CalibratedClassifier.predict_proba(state_row)
# ============================================================


def test_predict_proba_state_row_returns_calibrated_probability():
    """predict_proba(state_row) reads best_score and returns [0, 1]."""
    clf = CalibratedClassifier()
    # Hand-trained coeffs: logit = 0.0 → sigmoid(0) = 0.5.
    clf._coeffs = [0.0, 0.0]
    p = clf.predict_proba({"best_score": 0.5})
    assert 0.0 <= p <= 1.0
    assert abs(p - 0.5) < 0.01

    # Sanity: positive slope gives a probability > 0.5 for a
    # score > 0.0.
    clf._coeffs = [0.0, 5.0]
    p2 = clf.predict_proba({"best_score": 0.5})
    assert p2 > 0.5


def test_predict_proba_handles_missing_best_score():
    """Missing best_score defaults to 0.0; predict_proba returns a
    finite value, not a crash."""
    clf = CalibratedClassifier()
    p = clf.predict_proba({})
    assert 0.0 <= p <= 1.0


def test_predict_proba_monotonic_in_score():
    """Higher best_score → higher calibrated probability (assuming
    positive coefficient, which is the training-time default)."""
    clf = CalibratedClassifier()
    clf._coeffs = [0.0, 5.0]  # steep positive slope
    low = clf.predict_proba({"best_score": 0.1})
    mid = clf.predict_proba({"best_score": 0.5})
    high = clf.predict_proba({"best_score": 0.9})
    assert low < mid < high


# ============================================================
# Decision schema
# ============================================================


def test_decision_carries_calibrated_probability_field():
    """Decision has a new calibrated_probability field defaulting to None."""
    ctx = DecisionContext(candidates=[])
    decision = classify(ctx)
    # Field exists; back-compat default is None.
    assert hasattr(decision, "calibrated_probability")
    assert decision.calibrated_probability is None


def test_decision_to_dict_includes_calibrated_probability_when_set():
    """When set, to_dict() serializes calibrated_probability."""
    d = Decision(
        status="auto_accept",
        top_score=0.9,
        gap=0.0,
        threshold_used=0.85,
        policy_version="1",
        calibrated_probability=0.97,
    )
    out = d.to_dict()
    assert out["calibrated_probability"] == 0.97


# ============================================================
# CalibratedDecisionKS
# ============================================================


@pytest.fixture
def sqlite_store(tmp_path):
    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    yield store
    store.close()


def _seed_score_observation(
    store: SqliteBlackboardStore, pid: int, *, best_score: float
) -> None:
    """Seed a ScoreObserved with a Decision payload for the pensioner."""
    decision = Decision(
        status="auto_accept",
        top_score=best_score,
        gap=0.0,
        threshold_used=0.85,
        policy_version="1",
    )
    store.append_observation(
        Observation(
            observation_id=f"obs-score-{pid}",
            pensioner_id=pid,
            kind=Kind.ScoreObserved,
            source="CandidateScorerKS",
            source_version="1",
            run_id="r1",
            pass_id="1",
            payload=decision.to_dict(),
        )
    )


def test_ks_emits_decision_observation_with_probability(sqlite_store):
    """With a loaded classifier, the KS emits DecisionObserved
    carrying calibrated_probability."""
    pid = 42
    _seed_score_observation(sqlite_store, pid, best_score=0.9)
    clf = CalibratedClassifier()
    clf._coeffs = [0.0, 5.0]

    ks = CalibratedDecisionKS(classifier=clf)
    item = WorkItem(
        work_id="w-decide-1",
        pensioner_id=pid,
        knowledge_source="CalibratedDecisionKS",
    )
    out = ks.invoke(item, sqlite_store)

    assert len(out) == 1
    obs = out[0]
    assert obs.kind == Kind.DecisionObserved
    assert obs.pensioner_id == pid
    assert "calibrated_probability" in obs.payload
    prob = obs.payload["calibrated_probability"]
    assert prob is not None
    assert 0.0 <= prob <= 1.0
    # The seeded best_score was 0.9; with positive slope, the
    # probability should be > 0.5.
    assert prob > 0.5


def test_ks_emits_observation_with_no_probability_when_classifier_absent(sqlite_store):
    """When no classifier is supplied, the KS still emits a
    DecisionObserved (so the projection path stays in sync) but with
    calibrated_probability=None — the legacy Fellegi-Sunter path
    runs."""
    pid = 7
    _seed_score_observation(sqlite_store, pid, best_score=0.9)

    ks = CalibratedDecisionKS(classifier=None)
    item = WorkItem(
        work_id="w-decide-2",
        pensioner_id=pid,
        knowledge_source="CalibratedDecisionKS",
    )
    out = ks.invoke(item, sqlite_store)

    assert len(out) == 1
    obs = out[0]
    assert obs.kind == Kind.DecisionObserved
    assert obs.payload["calibrated_probability"] is None


def test_ks_no_score_observation_emits_noop(sqlite_store):
    """If no ScoreObserved exists for the pensioner, the KS is a
    no-op (returns no observations, doesn't crash)."""
    ks = CalibratedDecisionKS(classifier=CalibratedClassifier())
    item = WorkItem(
        work_id="w-decide-3",
        pensioner_id=999,
        knowledge_source="CalibratedDecisionKS",
    )
    out = ks.invoke(item, sqlite_store)
    # No ScoreObserved → no DecisionObserved emitted.
    assert out == []


def test_ks_eligible_filter(sqlite_store):
    """The KS only claims work items whose knowledge_source is
    CalibratedDecisionKS."""
    ks = CalibratedDecisionKS(classifier=CalibratedClassifier())
    matching = WorkItem(
        work_id="w-a",
        pensioner_id=1,
        knowledge_source="CalibratedDecisionKS",
    )
    other = WorkItem(
        work_id="w-b",
        pensioner_id=1,
        knowledge_source="CandidateScorerKS",
    )
    assert ks.eligible(matching) is True
    assert ks.eligible(other) is False


def test_classifier_loads_from_json(tmp_path: Path):
    """load(path) reads the persisted coefficients and the KS uses
    them end-to-end."""
    clf = CalibratedClassifier(classifier_version="test-1")
    clf._coeffs = [-1.0, 4.0]
    path = tmp_path / "classifier.json"
    clf.save(path)
    # Round-trip
    loaded = CalibratedClassifier.load(path)
    assert loaded._coeffs == [-1.0, 4.0]
    assert loaded.classifier_version == "test-1"
    # And predict_proba works on the loaded instance.
    p = loaded.predict_proba({"best_score": 0.5})
    # logit = -1.0 + 4.0*0.5 = 1.0 → sigmoid = ~0.73
    assert abs(p - 0.73) < 0.01