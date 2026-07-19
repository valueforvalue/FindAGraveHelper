"""Tests for CandidateScorerKS + DeepRefinerKS — Phase 6 Slice 6.3."""

from scripts.blackboard.schema import WorkItem, WorkState
from scripts.knowledge.candidate_scorer import CandidateScorerKS, DeepRefinerKS


def test_candidate_scorer_eligible():
    ks = CandidateScorerKS()
    item = WorkItem(
        work_id="w1", pensioner_id=1, knowledge_source="CandidateScorerKS"
    )
    assert ks.eligible(item) is True


def test_candidate_scorer_not_eligible():
    ks = CandidateScorerKS()
    item = WorkItem(work_id="w1", pensioner_id=1, knowledge_source="OtherKS")
    assert ks.eligible(item) is False


def test_deep_refiner_eligible():
    ks = DeepRefinerKS()
    item = WorkItem(
        work_id="w1", pensioner_id=1, knowledge_source="DeepRefinerKS"
    )
    assert ks.eligible(item) is True


def test_deep_refiner_max_refinements():
    """DeepRefinerKS has a max refinement budget."""
    ks = DeepRefinerKS()
    assert ks.MAX_REFINEMENTS == 5


def test_deep_refiner_estimated_cost():
    ks = DeepRefinerKS()
    item = WorkItem(work_id="w1", pensioner_id=1, knowledge_source="DeepRefinerKS")
    assert ks.estimated_cost(item) == 1
