"""Scoring evaluation harness — Phase 3 Slice 3.6.

Runs the shared scorer and decision policy against historical
observations to produce evaluation reports. Compares predicted
outcomes against ground-truth labels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.blackboard.decision_policy import (
    Decision,
    DecisionContext,
    classify,
)
from scripts.matching.candidate_scorer import CandidateScorer


@dataclass
class EvalResult:
    """One evaluation row."""

    pensioner_id: int
    predicted_status: str = ""
    predicted_score: float = 0.0
    ground_truth: str = ""  # accepted|rejected|unlabeled
    correct: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalSummary:
    """Aggregate evaluation metrics."""

    total: int = 0
    correct: int = 0
    accuracy: float = 0.0
    precision_auto_accept: float = 0.0
    recall_auto_accept: float = 0.0
    by_status: dict[str, int] = field(default_factory=dict)


class ScoringEvaluator:
    """Evaluates scorer + decision policy against labeled data."""

    def __init__(
        self,
        scorer: CandidateScorer | None = None,
        policy_version: str = "1",
    ) -> None:
        self.scorer = scorer or CandidateScorer()
        self.policy_version = policy_version

    def evaluate(
        self,
        local_records: list[dict[str, Any]],
        ground_truth: dict[int, str] | None = None,
    ) -> tuple[list[EvalResult], EvalSummary]:
        """Score all records and compare against ground truth."""
        gt = ground_truth or {}
        results: list[EvalResult] = []

        for record in local_records:
            pid = record.get("pensioner_id", 0)
            candidates = record.get("fag_records", []) or []

            # Score
            scored = self.scorer.score_all(record, candidates)
            top_score = scored[0].score if scored else 0.0

            # Classify
            ctx = DecisionContext(
                candidates=[
                    s.to_dict() for s in scored
                ],
                local_death_year=str(record.get("death_year", "")),
            )
            decision = classify(ctx)

            # Ground truth
            truth = gt.get(pid, "unlabeled")
            correct = False
            if truth == "accepted" and decision.status == "auto_accept":
                correct = True
            elif truth == "rejected" and decision.status != "auto_accept":
                correct = True
            elif truth == "unlabeled":
                correct = True  # no penalty for unlabeled

            results.append(
                EvalResult(
                    pensioner_id=pid,
                    predicted_status=decision.status,
                    predicted_score=top_score,
                    ground_truth=truth,
                    correct=correct,
                    details={"decision": decision.to_dict()},
                )
            )

        # Build summary
        total = len(results)
        n_correct = sum(1 for r in results if r.correct)
        auto_accept = [r for r in results if r.predicted_status == "auto_accept"]
        tp = sum(
            1 for r in auto_accept if r.ground_truth == "accepted"
        )
        fp = sum(
            1 for r in auto_accept if r.ground_truth == "rejected"
        )
        fn = sum(
            1 for r in results
            if r.ground_truth == "accepted" and r.predicted_status != "auto_accept"
        )

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        by_status: dict[str, int] = {}
        for r in results:
            by_status[r.predicted_status] = by_status.get(r.predicted_status, 0) + 1

        summary = EvalSummary(
            total=total,
            correct=n_correct,
            accuracy=n_correct / total if total else 0.0,
            precision_auto_accept=precision,
            recall_auto_accept=recall,
            by_status=by_status,
        )

        return results, summary

    def run_from_file(
        self, state_path: Path, ground_truth_path: Path | None = None
    ) -> EvalSummary:
        """Load state.jsonl + optional ground truth CSV, evaluate, return summary."""
        records = []
        if state_path.exists():
            for line in state_path.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    records.append(json.loads(line))

        ground_truth: dict[int, str] = {}
        if ground_truth_path and ground_truth_path.exists():
            import csv
            with ground_truth_path.open(encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = int(row.get("pensioner_id", 0))
                    ground_truth[pid] = row.get("decision", "unlabeled")

        _results, summary = self.evaluate(records, ground_truth)
        return summary
