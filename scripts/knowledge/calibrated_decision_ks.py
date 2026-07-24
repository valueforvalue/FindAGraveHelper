"""CalibratedDecisionKS: emits DecisionObserved with calibrated_probability (issue #96).

Reads the existing `ScoreObserved` observation for a pensioner
(issued by `CandidateScorerKS`), runs the loaded
`CalibratedClassifier.predict_proba(state_row)`, and emits a
`DecisionObserved` carrying the calibrated probability.

Falls back to a no-op when no classifier is supplied: the KS
still emits a `DecisionObserved` (so the projection path stays
in sync) but with `calibrated_probability=None`. The legacy
Fellegi-Sunter path runs unchanged.

The KS is registered after `DeepRefinerKS` in
`run_unified.py` so the new observation lands in the
projection row's `decision.calibrated_probability` field.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from scripts.blackboard.decision_policy import Decision
from scripts.blackboard.schema import (
    Kind,
    Observation,
    WorkItem,
)
from scripts.blackboard.store import BlackboardStore
from scripts.learning.calibrated_classifier import CalibratedClassifier

log = logging.getLogger("calibrated_decision_ks")


def _stable_id(*parts: str) -> str:
    value = "\x1f".join(parts)
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


class CalibratedDecisionKS:
    """Consumes ScoreObserved, emits DecisionObserved with calibrated_probability."""

    name: str = "CalibratedDecisionKS"

    def __init__(
        self,
        *,
        classifier: Optional[CalibratedClassifier] = None,
    ) -> None:
        self._classifier = classifier

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "CalibratedDecisionKS"

    def invoke(
        self, item: WorkItem, store: BlackboardStore
    ) -> list[Observation]:
        """Read ScoreObserved, run calibration, emit DecisionObserved.

        Returns an empty list when no ScoreObserved exists for the
        pensioner (the KS is a no-op in that case — the scheduler
        will move on; the existing per-record pipeline continues
        to work because the ProjectionBuilder reads ScoreObserved
        directly when DecisionObserved is absent).
        """
        all_obs = store.read_observations_since(None)
        score_obs = next(
            (
                o
                for o in all_obs
                if o.pensioner_id == item.pensioner_id
                and o.kind == Kind.ScoreObserved
            ),
            None,
        )
        if score_obs is None:
            log.debug(
                "No ScoreObserved for pensioner %d; CalibratedDecisionKS no-op",
                item.pensioner_id,
            )
            return []

        # Reconstruct a Decision from the ScoreObserved payload.
        # The observation's payload IS the Decision.to_dict() shape
        # (see CandidateScorerKS.invoke).
        decision_dict = dict(score_obs.payload)
        decision = Decision(
            status=decision_dict.get("status", "needs_review"),
            policy_version=decision_dict.get("policy_version", "1"),
            top_score=float(decision_dict.get("top_score", 0.0) or 0.0),
            second_score=float(decision_dict.get("second_score", 0.0) or 0.0),
            candidate_count=int(decision_dict.get("candidate_count", 0) or 0),
            gap=float(decision_dict.get("gap", 0.0) or 0.0),
            threshold_used=float(decision_dict.get("threshold_used", 0.0) or 0.0),
            reason=decision_dict.get("reason", ""),
        )

        # Calibrate. None when no classifier is loaded.
        if self._classifier is not None:
            decision.calibrated_probability = self._classifier.predict_proba(
                {"best_score": decision.top_score}
            )
        # else: leave as None — the Fellegi-Sunter path produced
        # the verdict; the calibrated field stays None for the
        # projection layer to detect.

        obs = Observation(
            observation_id=f"obs-decision-{_stable_id(str(item.pensioner_id), item.pass_id or '1')}",
            pensioner_id=item.pensioner_id,
            kind=Kind.DecisionObserved,
            source="CalibratedDecisionKS",
            source_version="1",
            run_id=item.pass_id or "1",
            pass_id="post",
            caused_by=score_obs.observation_id,
            payload=decision.to_dict(),
        )
        store.append_observation(obs)
        return [obs]