"""RegionalPlannerKS: emits typed QueryPlans from pensioner evidence.

Knowledge Source that reads pensioner observations and emits one
QueryPlan per pensioner scope, ordered by the project's geographic
priority: OK → regiment-origin → Texas → inferred → US.

Public surface:
  - RegionalPlannerKS (implements KnowledgeSource protocol)
  - plan_for_pensioner(pensioner) -> list[QueryPlan]
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from scripts.blackboard.schema import (
    Observation,
    PlanScope,
    QueryPlan,
    WorkItem,
)
from scripts.blackboard.store import BlackboardStore

log = logging.getLogger("regional_planner")


class RegionalPlannerKS:
    """Emits ordered QueryPlans for a pensioner based on geographic policy.

    Policy priority (configurable):
      1. Oklahoma (default for this project)
      2. Regiment-origin state (inferred from unit text)
      3. Texas (if migration evidence exists)
      4. Inferred likely states
      5. US-wide fallback
    """

    name: str = "RegionalPlannerKS"

    # Known regiment-to-state mappings
    _REGIMENT_STATE: dict[str, str] = {
        "alabama": "AL",
        "arkansas": "AR",
        "florida": "FL",
        "georgia": "GA",
        "kentucky": "KY",
        "louisiana": "LA",
        "mississippi": "MS",
        "missouri": "MO",
        "north carolina": "NC",
        "south carolina": "SC",
        "tennessee": "TN",
        "texas": "TX",
        "virginia": "VA",
    }

    # Texas migration indicators
    _TEXAS_HINTS = ("texas", "tx", "reconstruction", "migrated to texas")

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "RegionalPlannerKS"

    def invoke(
        self, item: WorkItem, store: BlackboardStore
    ) -> list[Observation]:
        """Read pensioner evidence, emit QueryPlans."""
        # Load pensioner data from prior observations
        observations = store.read_observations_since(None)
        pensioner_data: dict[str, Any] = {}
        for obs in observations:
            if obs.pensioner_id == item.pensioner_id:
                pensioner_data.update(obs.payload)

        plans = self.plan_for_pensioner(pensioner_data, item.pensioner_id)

        plan_observations: list[Observation] = []
        for plan in plans:
            store.enqueue_plan(plan)
            plan_observations.append(
                Observation(
                    observation_id=f"obs-plan-{uuid.uuid4().hex[:12]}",
                    pensioner_id=item.pensioner_id,
                    kind="FaGSearchPlan",  # type: ignore[arg-type]
                    source="RegionalPlannerKS",
                    source_version="1",
                    run_id=item.pass_id,
                    pass_id="1",
                    caused_by=item.work_id,
                    payload=plan.to_dict(),
                )
            )

        # Enqueue FaG scraper work for each plan
        for plan in plans:
            store.enqueue_work(
                WorkItem(
                    work_id=f"work-fag-{uuid.uuid4().hex[:12]}",
                    pensioner_id=item.pensioner_id,
                    knowledge_source="FaGScraperKS",
                    plan_id=plan.plan_id,
                    pass_id="1",
                )
            )

        log.info(
            "RegionalPlannerKS: %d plans for pensioner %d.",
            len(plans), item.pensioner_id,
        )
        return plan_observations

    def estimated_cost(self, item: WorkItem) -> int:
        return 1  # no network requests; just local computation

    # ----------------------------------------------------------
    # Plan generation
    # ----------------------------------------------------------

    def plan_for_pensioner(
        self, pensioner: dict[str, Any], pensioner_id: int
    ) -> list[QueryPlan]:
        """Generate ordered QueryPlans for a pensioner.

        Returns plans in priority order. Caller may truncate based
        on request budget.
        """
        plans: list[QueryPlan] = []

        first = str(pensioner.get("first_name") or pensioner.get("first") or "")
        last = str(pensioner.get("last_name") or pensioner.get("last") or "")
        regiment = str(pensioner.get("regiment") or "").lower()
        birth_year = str(pensioner.get("birth_year") or "")

        base_params: dict[str, Any] = {}
        if first:
            base_params["firstname"] = first
        if last:
            base_params["lastname"] = last

        if not last:
            return plans  # can't search without at least a last name

        # 1. Oklahoma (always first for this project)
        plans.append(
            QueryPlan(
                plan_id=f"plan-ok-{uuid.uuid4().hex[:8]}",
                pensioner_id=pensioner_id,
                strategy="B1-exact",
                params=dict(base_params),
                scope=PlanScope.OK,
                reason="Project default: Oklahoma-first search.",
                estimated_requests=1,
            )
        )

        # 2. Regiment-origin state
        origin_state = self._infer_origin_state(regiment)
        if origin_state and origin_state != "OK":
            plans.append(
                QueryPlan(
                    plan_id=f"plan-regiment-{uuid.uuid4().hex[:8]}",
                    pensioner_id=pensioner_id,
                    strategy="B1-exact",
                    params=dict(base_params),
                    scope=PlanScope(origin_state)
                    if origin_state in {"US"}
                    else PlanScope.RegimentOrigin,
                    reason=f"Regiment origin state: {origin_state}.",
                    estimated_requests=1,
                )
            )

        # 3. Texas (if migration evidence)
        if self._has_texas_evidence(pensioner):
            plans.append(
                QueryPlan(
                    plan_id=f"plan-texas-{uuid.uuid4().hex[:8]}",
                    pensioner_id=pensioner_id,
                    strategy="B1-exact",
                    params=dict(base_params),
                    scope=PlanScope.Texas,
                    reason="Texas migration evidence detected.",
                    estimated_requests=1,
                )
            )

        # 4. US-wide fallback
        plans.append(
            QueryPlan(
                plan_id=f"plan-us-{uuid.uuid4().hex[:8]}",
                pensioner_id=pensioner_id,
                strategy="B4-fuzzy-last",
                params=dict(base_params),
                scope=PlanScope.US,
                reason="US-wide fallback after narrow scopes.",
                estimated_requests=1,
            )
        )

        return plans

    def _infer_origin_state(self, regiment: str) -> str | None:
        """Infer likely state from regiment/unit text."""
        if not regiment:
            return None
        for state_name, abbr in self._REGIMENT_STATE.items():
            if state_name in regiment:
                return abbr
        return None

    def _has_texas_evidence(self, pensioner: dict[str, Any]) -> bool:
        """Check for Texas migration/residence evidence."""
        hints = str(pensioner.get("notes") or "").lower()
        burial = str(pensioner.get("burial_state") or "").upper()
        if burial == "TX":
            return True
        for hint in self._TEXAS_HINTS:
            if hint in hints:
                return True
        return False
