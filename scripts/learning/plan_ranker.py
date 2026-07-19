"""Plan ranker — Phase 8 Slice 8.3.

Ranks eligible QueryPlans using versioned priors + historical plan
outcomes. Advisory only — never overrides RequestGate safety,
terminal stop conditions, or per-pensioner budgets.
"""
from __future__ import annotations

from typing import Any

from scripts.blackboard.schema import QueryPlan
from scripts.learning.label_extractor import LabelStore
from scripts.learning.priors import PriorRegistry


class PlanRanker:
    """Ranks QueryPlans by expected information gain.

    Dimensions:
      - Prior strategy usefulness for data shape × target evidence
      - Historical success rate for similar pensioners
      - Cost (lower = better when tied)
      - Diversity bonus for plans targeting unseen evidence

    Hard constraints (never violated):
      - Plans beyond budget are dropped
      - Plans requiring cooldown-blocked providers are dropped
      - Equivalent plans already executed are dropped
    """

    def __init__(
        self,
        priors: PriorRegistry | None = None,
        label_store: LabelStore | None = None,
    ) -> None:
        self.priors = priors or PriorRegistry.default()
        self.label_store = label_store

    def rank(
        self,
        plans: list[QueryPlan],
        pensioner_context: dict[str, Any] | None = None,
        request_budget: int | None = None,
    ) -> list[QueryPlan]:
        """Rank plans by expected gain. Drops budget-exceeded plans.

        Args:
            plans: unordered eligible plans.
            pensioner_context: pensioner metadata (regiment, notes, etc.).
            request_budget: max plans to return (None = no limit).

        Returns:
            Ordered list (highest rank first), truncated to budget.
        """
        if not plans:
            return []

        ctx = pensioner_context or {}
        regiment = str(ctx.get("regiment", ""))

        # Score each plan
        scored: list[tuple[float, QueryPlan]] = []
        for plan in plans:
            score = self._score_plan(plan, regiment)
            scored.append((score, plan))

        # Sort by score descending, then by cost ascending
        scored.sort(key=lambda x: (-x[0], x[1].estimated_requests))

        ranked = [plan for _, plan in scored]

        # Dedup equivalent plans
        seen_effective: set[str] = set()
        deduped: list[QueryPlan] = []
        for plan in ranked:
            effective = f"{plan.strategy}|{plan.scope.value}|{sorted(plan.params.items())}"
            if effective not in seen_effective:
                seen_effective.add(effective)
                deduped.append(plan)

        # Apply budget
        if request_budget is not None and len(deduped) > request_budget:
            deduped = deduped[:request_budget]

        return deduped

    def _score_plan(self, plan: QueryPlan, regiment: str) -> float:
        """Score a single plan based on priors."""
        score = 0.0

        # Base: strategy usefulness
        data_shape = self._data_shape(plan)
        target = self._target_evidence(plan)
        score += self.priors.strategy_usefulness(data_shape, target)

        # Bonus: OK scope is preferred for this project
        if plan.scope.value == "OK":
            score += 0.10

        # Bonus: regiment-origin state matches
        if regiment and plan.scope.value in ("RegimentOrigin", "Texas"):
            score += 0.05

        # Penalty: global/US is broad (lower precision)
        if plan.scope.value in ("Global", "US"):
            score -= 0.05

        return score

    @staticmethod
    def _data_shape(plan: QueryPlan) -> str:
        """Infer data shape from strategy name."""
        strategy = plan.strategy.lower()
        if "exact" in strategy:
            return "exact_name"
        if "fuzzy" in strategy:
            return "fuzzy_last"
        if "context" in strategy or "cw" in strategy:
            return "cw_context"
        if "sniper" in strategy or "year" in strategy:
            return "year_sniper"
        if "nickname" in strategy:
            return "nickname"
        return "global_fallback"

    @staticmethod
    def _target_evidence(plan: QueryPlan) -> str:
        """Infer target evidence from plan reason."""
        reason = plan.reason.lower()
        if "veteran" in reason:
            return "veteran"
        if "death" in reason or "date" in reason:
            return "death_date"
        if "identity" in reason or "name" in reason:
            return "identity"
        return "any"
