"""Tests for pairwise weight learner (#60)."""
import json
import tempfile
from pathlib import Path

from scripts.learning.weight_learner import (
    PairwiseWeightLearner,
    LearnedWeights,
    DEFAULT_WEIGHTS,
    FEATURE_NAMES,
)


class TestPairwiseWeightLearner:
    """Core learner tests."""

    def test_empty_returns_defaults(self):
        """No pairs → learned weights equal defaults."""
        learner = PairwiseWeightLearner()
        result = learner.learn()
        assert result.weights == DEFAULT_WEIGHTS
        assert result.pair_count == 0

    def test_single_pair_updates_weights(self):
        """One pair where picked has stronger year_window → year_window upweighted."""
        learner = PairwiseWeightLearner()
        # Picked candidate had year_window=0.8, rejected had 0.2
        learner.add_pair(
            pensioner_id=1,
            picked_features={"last_name": 1.0, "first_name": 1.0, "middle_name": 0.0,
                             "year_window": 0.8, "state": 0.0, "ok_burial": 0.0, "veteran": 0.0},
            rejected_features={"last_name": 1.0, "first_name": 1.0, "middle_name": 0.0,
                               "year_window": 0.2, "state": 0.0, "ok_burial": 0.0, "veteran": 0.0},
            picked_rank=2,
        )
        result = learner.learn()
        assert result.pair_count == 1
        # year_window should be upweighted relative to other features
        # since it was the only differentiating feature
        assert result.weights["year_window"] > result.weights["last_name"]

    def test_year_window_overweighted_downweights(self):
        """When rejected candidates consistently have higher year_window
        than picked, year_window should be downweighted."""
        learner = PairwiseWeightLearner()
        # Add 5 pairs where rejected has higher year_window
        for i in range(5):
            learner.add_pair(
                pensioner_id=i,
                picked_features={"last_name": 1.0, "first_name": 1.0, "middle_name": 0.0,
                                 "year_window": 0.1, "state": 0.0, "ok_burial": 0.0, "veteran": 0.0},
                rejected_features={"last_name": 1.0, "first_name": 1.0, "middle_name": 0.0,
                                   "year_window": 0.9, "state": 0.0, "ok_burial": 0.0, "veteran": 0.0},
                picked_rank=3,
            )
        result = learner.learn()
        # year_window delta is negative (picked had LESS year_window than rejected)
        # So the scorer overweighted year_window → should be downweighted
        assert result.weights["year_window"] < DEFAULT_WEIGHTS["year_window"]

    def test_serialization_roundtrip(self):
        """LearnedWeights survives JSON roundtrip."""
        weights = LearnedWeights(
            weights={"last_name": 1.5, "first_name": 0.8},
            trained_at="2026-01-01",
            pair_count=10,
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            weights.save(f.name)
            loaded = LearnedWeights.load(f.name)
        Path(f.name).unlink()
        assert loaded.weights == weights.weights
        assert loaded.pair_count == 10

    def test_extract_pairs_from_labels(self):
        """Labels with _picked_rank > 1 and _feature_deltas produce pairs."""
        labels = [
            {
                "pensioner_id": 1,
                "human_review_decision": "accepted",
                "_picked_rank": 2,
                "_feature_deltas": {
                    "last_name": 0.0,
                    "first_name": -0.3,
                    "year_window": 0.5,
                },
                "_winning_strategy": "F2-regiment-bio",
            },
            {
                "pensioner_id": 2,
                "human_review_decision": "accepted",
                "_picked_rank": 1,  # rank 1 → no pair (scorer agreed)
            },
            {
                "pensioner_id": 3,
                "human_review_decision": "rejected",  # not accepted → skip
                "_picked_rank": 2,
                "_feature_deltas": {"last_name": 0.1},
            },
        ]
        learner = PairwiseWeightLearner()
        count = learner.extract_pairs_from_labels(labels)
        assert count == 1  # only pensioner 1 produces a pair
        assert learner.pair_count == 1
