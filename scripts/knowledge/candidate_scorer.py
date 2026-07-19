"""CandidateScorerKS + DeepRefinerKS: scoring and refinement Knowledge Sources.

CandidateScorerKS reads FaGCandidateFetch observations, runs the
shared scorer, and posts ScoreObserved.

DeepRefinerKS reads ScoreObserved with ambiguous/low-score status
and emits new QueryPlans for refinement (spouse, global, nickname).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from scripts.blackboard.decision_policy import (
    Decision,
    DecisionContext,
    classify,
)
from scripts.blackboard.schema import (
    Kind,
    Observation,
    PlanScope,
    QueryPlan,
    WorkItem,
)
from scripts.blackboard.store import BlackboardStore

log = logging.getLogger("knowledge_sources")


# ============================================================
# CandidateScorerKS
# ============================================================


class CandidateScorerKS:
    """Consumes FaGCandidateFetch observations, emits ScoreObserved."""

    name: str = "CandidateScorerKS"

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "CandidateScorerKS"

    def invoke(
        self, item: WorkItem, store: BlackboardStore
    ) -> list[Observation]:
        """Score all candidates for this pensioner and classify."""
        observations = store.read_observations_since(None)
        candidates = [
            o.payload
            for o in observations
            if o.pensioner_id == item.pensioner_id
            and o.kind == Kind.FaGCandidateFetch
        ]

        # Get pensioner context for decision
        pensioner_obs = [
            o
            for o in observations
            if o.pensioner_id == item.pensioner_id
            and o.kind == Kind.PensionerImported
        ]
        pensioner_data: dict[str, Any] = {}
        if pensioner_obs:
            pensioner_data = pensioner_obs[0].payload

        local_dy = str(pensioner_data.get("death_year") or "").strip()
        ctx = DecisionContext(
            candidates=candidates,
            local_death_year=local_dy if local_dy else None,
        )
        decision = classify(ctx)

        # Emit ScoreObserved
        obs = Observation(
            observation_id=f"obs-score-{uuid.uuid4().hex[:12]}",
            pensioner_id=item.pensioner_id,
            kind=Kind.ScoreObserved,
            source="CandidateScorerKS",
            source_version="1",
            run_id=item.pass_id,
            pass_id="1",
            caused_by=item.work_id,
            payload=decision.to_dict(),
        )
        store.append_observation(obs)

        log.info(
            "CandidateScorerKS: pensioner %d -> %s (score=%.3f).",
            item.pensioner_id, decision.status, decision.top_score,
        )
        return [obs]

    def estimated_cost(self, item: WorkItem) -> int:
        return 1


# ============================================================
# DeepRefinerKS
# ============================================================


class DeepRefinerKS:
    """Reads ambiguous/low-score outcomes and emits refinement QueryPlans.

    Triggers:
      - No candidates -> try US-wide, nickname, spouse
      - Low score / ambiguous -> try spouse, global, nickname
      - Top-two gap too close -> target missing evidence
    """

    name: str = "DeepRefinerKS"

    # Maximum refinement plans per pensioner
    MAX_REFINEMENTS = 5

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "DeepRefinerKS"

    def invoke(
        self, item: WorkItem, store: BlackboardStore
    ) -> list[Observation]:
        """Generate refinement plans based on current score state."""
        observations = store.read_observations_since(None)
        score_obs = [
            o
            for o in observations
            if o.pensioner_id == item.pensioner_id
            and o.kind == Kind.ScoreObserved
        ]

        if not score_obs:
            return []

        decision = Decision(
            status=score_obs[0].payload.get("status", "needs_review"),
            top_score=score_obs[0].payload.get("top_score", 0.0),
        )

        # Don't refine if already auto-accepted
        if decision.status == "auto_accept":
            return []

        plans = self._generate_refinements(item.pensioner_id, decision)
        plan_obs: list[Observation] = []

        for plan in plans[: self.MAX_REFINEMENTS]:
            store.enqueue_plan(plan)
            store.enqueue_work(
                WorkItem(
                    work_id=f"work-fag-refine-{uuid.uuid4().hex[:12]}",
                    pensioner_id=item.pensioner_id,
                    knowledge_source="FaGScraperKS",
                    plan_id=plan.plan_id,
                    pass_id="2",  # refinement pass
                )
            )
            plan_obs.append(
                Observation(
                    observation_id=f"obs-refine-{uuid.uuid4().hex[:12]}",
                    pensioner_id=item.pensioner_id,
                    kind=Kind.FaGSearchPlan,
                    source="DeepRefinerKS",
                    source_version="1",
                    run_id=item.pass_id,
                    pass_id="2",
                    caused_by=item.work_id,
                    payload=plan.to_dict(),
                )
            )

        log.info(
            "DeepRefinerKS: %d refinement plans for pensioner %d.",
            len(plan_obs), item.pensioner_id,
        )
        return plan_obs

    def estimated_cost(self, item: WorkItem) -> int:
        return 1

    # ----------------------------------------------------------
    # Refinement logic
    # ----------------------------------------------------------

    def _generate_refinements(
        self, pensioner_id: int, decision: Decision
    ) -> list[QueryPlan]:
        """Generate refinement plans based on score state."""
        plans: list[QueryPlan] = []

        if decision.status == "no_candidates" or decision.top_score < 0.30:
            # Try broader scopes
            plans.append(
                QueryPlan(
                    plan_id=f"plan-refine-us-{uuid.uuid4().hex[:8]}",
                    pensioner_id=pensioner_id,
                    strategy="B4-fuzzy-last",
                    params={},
                    scope=PlanScope.US,
                    reason="Refinement: no/low candidates; trying US-wide.",
                    estimated_requests=1,
                )
            )

        if decision.status in ("needs_review", "ambiguous"):
            # Try nickname + spouse scopes
            plans.append(
                QueryPlan(
                    plan_id=f"plan-refine-global-{uuid.uuid4().hex[:8]}",
                    pensioner_id=pensioner_id,
                    strategy="C1-cw-context",
                    params={},
                    scope=PlanScope.Global,
                    reason="Refinement: ambiguous result; trying global.",
                    estimated_requests=1,
                )
            )

        if decision.status == "low_score":
            plans.append(
                QueryPlan(
                    plan_id=f"plan-refine-global-{uuid.uuid4().hex[:8]}",
                    pensioner_id=pensioner_id,
                    strategy="B1-exact",
                    params={},
                    scope=PlanScope.Global,
                    reason="Refinement: low score; trying global exact.",
                    estimated_requests=1,
                )
            )

        return plans
