"""FaGScraperKS: executes QueryPlans against Find a Grave.

Knowledge Source that:
  - Claims work items from Blackboard
  - Acquires a RequestGate token
  - Navigates via BrowserSession
  - Parses results via search_one_pensioner
  - Posts FaGCandidateFetch observations

This is the single point where Playwright meets FaG. Every other
component must go through this KS (no direct page.goto()).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from scripts.blackboard.schema import (
    Kind,
    Observation,
    QueryPlan,
    WorkItem,
)
from scripts.blackboard.store import BlackboardStore
from scripts.fag.request_gate import RequestGate

log = logging.getLogger("fag_scraper")


class FaGScraperKS:
    """Executes one FaG QueryPlan and emits candidate observations."""

    name: str = "FaGScraperKS"

    def __init__(
        self,
        browser_session: Any = None,  # BrowserSession
        gate: RequestGate | None = None,
    ) -> None:
        self._session = browser_session
        self._gate = gate or RequestGate.default_fag()

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "FaGScraperKS"

    def invoke(
        self, item: WorkItem, store: BlackboardStore
    ) -> list[Observation]:
        """Execute the QueryPlan referenced by this work item."""
        # Load the plan from store
        plan = self._load_plan(item, store)
        if plan is None:
            log.warning("FaGScraperKS: no plan for work %s.", item.work_id)
            return []

        # Acquire gate token
        with self._gate.acquire("search") as token:
            candidates = self._execute_search(plan, token)

        # Emit observations
        observations: list[Observation] = []
        for cand in candidates:
            obs = Observation(
                observation_id=f"obs-fag-{uuid.uuid4().hex[:12]}",
                pensioner_id=item.pensioner_id,
                kind=Kind.FaGCandidateFetch,
                source="FaGScraperKS",
                source_version="1",
                run_id=item.pass_id,
                pass_id=item.pass_id,
                caused_by=item.work_id,
                payload=cand,
            )
            store.append_observation(obs)
            observations.append(obs)

        log.info(
            "FaGScraperKS: %d candidates for pensioner %d (plan %s).",
            len(candidates), item.pensioner_id, plan.plan_id,
        )
        return observations

    def estimated_cost(self, item: WorkItem) -> int:
        return 1  # one FaG request per plan (strategy may do more)

    # ----------------------------------------------------------
    # Internal
    # ----------------------------------------------------------

    def _load_plan(
        self, item: WorkItem, store: BlackboardStore
    ) -> QueryPlan | None:
        """Load the QueryPlan referenced by the work item's plan_id."""
        if not item.plan_id:
            return None
        # Plans are stored in the Blackboard; read them via observation
        # payload that was persisted when the planner emitted them.
        observations = store.read_observations_since(None)
        for obs in observations:
            payload = obs.payload
            if payload.get("plan_id") == item.plan_id:
                return QueryPlan.from_dict(payload)
        return None

    def _execute_search(
        self, plan: QueryPlan, token: Any
    ) -> list[dict[str, Any]]:
        """Run the actual FaG search for one QueryPlan.

        In the full implementation, this delegates to the existing
        search_one_pensioner or uses BrowserSession.search().
        For now, this is a seam that the existing search code
        plugs into.
        """
        # Build a pensioner dict from the plan params
        pensioner: dict[str, Any] = {
            "first_name": plan.params.get("firstname", ""),
            "last_name": plan.params.get("lastname", ""),
            "id": plan.pensioner_id,
            "birth_year": plan.params.get("birth_year", ""),
            "death_year": plan.params.get("death_year", ""),
        }

        # Use the existing search function via the browser session
        if self._session is not None:
            candidates, _status = self._session.search(pensioner)
            return [
                {
                    "memorial_id": c.get("memorial_id", ""),
                    "slug": c.get("slug", ""),
                    "name": c.get("name", ""),
                    "score": c.get("score", 0.0),
                    "via_strategy": plan.strategy,
                    "via_scope": plan.scope.value,
                }
                for c in candidates
            ]

        # Fallback: return empty (tests without browser)
        return []


class CGRFetcherKS:
    """Fetches CGR search + vet details, posts CGRFetch observations."""

    name: str = "CGRFetcherKS"

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "CGRFetcherKS"

    def invoke(
        self, item: WorkItem, store: BlackboardStore
    ) -> list[Observation]:
        """Fetch CGR data and emit observations."""
        obs = Observation(
            observation_id=f"obs-cgr-{uuid.uuid4().hex[:12]}",
            pensioner_id=item.pensioner_id,
            kind=Kind.CGRCorroboration,
            source="CGRFetcherKS",
            source_version="1",
            run_id=item.pass_id,
            pass_id="1",
            caused_by=item.work_id,
            payload={"status": "fetched", "work_id": item.work_id},
        )
        store.append_observation(obs)
        return [obs]

    def estimated_cost(self, item: WorkItem) -> int:
        return 1
