"""CandidateScorer: versioned scoring facade — Phase 3 Slice 3.2.

Wraps scripts/fag/scoring.py score_candidate with policy versioning
and batch scoring. Every score carries scorer_version for audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.fag.scoring import score_candidate as _score_candidate


SCORER_VERSION = "1"


@dataclass
class CandidateScore:
    """Versioned score + breakdown for one candidate."""

    memorial_id: str
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    scorer_version: str = SCORER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "memorial_id": self.memorial_id,
            "score": self.score,
            "score_breakdown": dict(self.breakdown),
            "scorer_version": self.scorer_version,
        }


class CandidateScorer:
    """Scores candidates against a local pensioner record.

    Delegates to the existing score_candidate function but adds
    version tracking and batch scoring.
    """

    def __init__(self, scorer_version: str = SCORER_VERSION) -> None:
        self.scorer_version = scorer_version

    def score(
        self, local: dict[str, Any], candidate: dict[str, Any]
    ) -> CandidateScore:
        """Score one candidate. Returns typed CandidateScore."""
        raw_score, breakdown = _score_candidate(local, candidate)
        return CandidateScore(
            memorial_id=str(candidate.get("memorial_id", "")),
            score=raw_score,
            breakdown=breakdown,
            scorer_version=self.scorer_version,
        )

    def score_all(
        self, local: dict[str, Any], candidates: list[dict[str, Any]]
    ) -> list[CandidateScore]:
        """Score all candidates, sorted by score descending."""
        scores = [self.score(local, c) for c in candidates]
        scores.sort(key=lambda s: s.score, reverse=True)
        return scores
