"""CandidateScorerKS + DeepRefinerKS: scoring and refinement Knowledge Sources.

CandidateScorerKS reads FaGCandidateFetch observations, runs the
shared scorer, and posts ScoreObserved.

DeepRefinerKS reads ScoreObserved with ambiguous/low-score status
and emits new QueryPlans for refinement (spouse, global, nickname).
"""
from __future__ import annotations

import hashlib
import logging
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


def _stable_id(*parts: str) -> str:
    value = "\x1f".join(parts)
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


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
            and o.payload.get("memorial_id")
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
            observation_id=f"obs-score-{item.pensioner_id}-{item.pass_id}",
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

        # Queue refinement after persisting decision. Scheduler invokes this
        # only after all initial scraper items have completed.
        store.enqueue_work(
            WorkItem(
                work_id=f"work-refine-{item.pensioner_id}",
                pensioner_id=item.pensioner_id,
                knowledge_source="DeepRefinerKS",
                pass_id=item.pass_id,
            )
        )

        # Issue #96: queue a CalibratedDecisionKS work item so the
        # scheduler invokes it next. When no classifier is loaded,
        # the KS is a no-op (still emits a DecisionObserved with
        # calibrated_probability=None so the projection path
        # stays in sync).
        store.enqueue_work(
            WorkItem(
                work_id=f"work-decide-{item.pensioner_id}",
                pensioner_id=item.pensioner_id,
                knowledge_source="CalibratedDecisionKS",
                pass_id=item.pass_id,
            )
        )

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

    Issue #76: 3-tier staged refinements based on pass-1 score.
      - auto_accept (>= skip_refine_above): skip entirely
      - needs_review (LOW_SCORE_THRESHOLD <= score < skip): strategy-replay
      - low_score / no_candidates (< LOW_SCORE_THRESHOLD): surrounding-states

    Triggers:
      - No candidates -> surrounding-states, US-wide, spouse, nickname
      - Low score -> surrounding-states + US-fuzzy + spouse/nickname
      - Ambiguous / needs_review -> strategy-replay on OK scope
    """

    name: str = "DeepRefinerKS"

    # Surrounding states for OK-located pensioners (issue #76).
    _SURROUNDING_STATES = ["AR", "KS", "MO", "TX", "CO", "NM"]

    # Map state codes to PlanScope enum members.
    _STATE_TO_SCOPE: dict[str, PlanScope] = {
        "AR": PlanScope.AR,
        "KS": PlanScope.KS,
        "MO": PlanScope.MO,
        "TX": PlanScope.Texas,
        "CO": PlanScope.CO,
        "NM": PlanScope.NM,
    }

    def __init__(
        self,
        max_refinements: int = 6,
        skip_refine_above: float = 0.85,
        bail_on_auto_accept: bool = True,
    ) -> None:
        self.max_refinements = max_refinements
        self.skip_refine_above = skip_refine_above
        self.bail_on_auto_accept = bail_on_auto_accept

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

        top_score = float(score_obs[0].payload.get("top_score", 0.0))
        status = str(score_obs[0].payload.get("status", "needs_review"))

        # Tier 1: auto_accept — skip refinement entirely (#76).
        if top_score >= self.skip_refine_above:
            return []

        pensioner_obs = [
            o
            for o in observations
            if o.pensioner_id == item.pensioner_id
            and o.kind == Kind.PensionerImported
        ]
        pensioner_params = dict(pensioner_obs[0].payload) if pensioner_obs else {}

        # Issue #77: read already-tried (strategy, scope) combos so
        # we don't duplicate work across this run.
        tried = self._read_tried_combos(item.pensioner_id, store)

        plans = self._generate_refinements(
            item.pensioner_id, top_score, status, pensioner_params, tried
        )
        plans = plans[: self.max_refinements]
        plan_obs: list[Observation] = []

        for plan in plans:
            store.enqueue_plan(plan)
            store.enqueue_work(
                WorkItem(
                    work_id=f"work-fag-{plan.plan_id}",
                    pensioner_id=item.pensioner_id,
                    knowledge_source="FaGScraperKS",
                    plan_id=plan.plan_id,
                    pass_id="2",  # refinement pass
                )
            )
            plan_observation = Observation(
                observation_id=f"obs-refine-{plan.plan_id}",
                pensioner_id=item.pensioner_id,
                kind=Kind.FaGSearchPlan,
                source="DeepRefinerKS",
                source_version="2",
                run_id=item.pass_id,
                pass_id="2",
                caused_by=item.work_id,
                payload=plan.to_dict(),
            )
            store.append_observation(plan_observation)
            plan_obs.append(plan_observation)

        log.info(
            "DeepRefinerKS: %d refinement plans for pensioner %d.",
            len(plan_obs), item.pensioner_id,
        )
        return plan_obs

    def estimated_cost(self, item: WorkItem) -> int:
        return 1

    # ----------------------------------------------------------
    # Refinement logic (3-tier, issue #76)
    # ----------------------------------------------------------

    def _generate_refinements(
        self,
        pensioner_id: int,
        top_score: float,
        status: str,
        pensioner_params: dict[str, Any],
        tried: set[tuple[str, str]],
    ) -> list[QueryPlan]:
        """Generate refinement plans based on score tier.

        Tier 2 (needs_review, 0.40 <= score < skip_refine_above):
          - Strategy-replay plans: nickname, spouse, fuzzy on OK scope
          - Regiment-origin state if not already in pass 1

        Tier 3 (low_score / no_candidates, score < 0.40):
          - Surrounding states: AR, KS, MO, TX, CO, NM
          - US-wide fuzzy-last
          - Spouse + nickname
        """
        from scripts.pipeline.scoring_constants import LOW_SCORE_THRESHOLD

        plans: list[QueryPlan] = []
        params = dict(pensioner_params or {})
        first = str(params.get("first_name") or params.get("first") or "")
        last = str(params.get("last_name") or params.get("last") or "")
        regiment = str(params.get("regiment") or "").lower()

        if not last:
            return plans

        if top_score < LOW_SCORE_THRESHOLD or status == "no_candidates":
            # ── Tier 3: low_score / no_candidates ──
            log.info("DeepRefinerKS: pensioner %d (score=%.3f) -> tier 3 (surrounding + US + spouse).",
                     pensioner_id, top_score)

            # Surrounding states
            for state in self._SURROUNDING_STATES:
                scope = self._STATE_TO_SCOPE.get(state, PlanScope.US)
                key = ("B1-exact", state)
                if key in tried:
                    continue
                plans.append(
                    QueryPlan(
                        plan_id=(
                            f"plan-refine-{state}-{pensioner_id}-"
                            f"{_stable_id(str(pensioner_id), state, 'B1-exact')}"
                        ),
                        pensioner_id=pensioner_id,
                        strategy="B1-exact",
                        params=dict(params),
                        scope=scope,
                        reason=f"Refinement: surrounding state {state}.",
                        estimated_requests=1,
                    )
                )

            # US-wide fuzzy-last
            key = ("B4-fuzzy-last", "US")
            if key not in tried:
                plans.append(
                    QueryPlan(
                        plan_id=(
                            f"plan-refine-us-{pensioner_id}-"
                            f"{_stable_id(str(pensioner_id), 'US', 'B4-fuzzy-last')}"
                        ),
                        pensioner_id=pensioner_id,
                        strategy="B4-fuzzy-last",
                        params=dict(params),
                        scope=PlanScope.US,
                        reason="Refinement: no/low candidates; trying US-wide.",
                        estimated_requests=1,
                    )
                )

            # Spouse cross-search
            spouse_last = str(params.get("spouse_last_name") or params.get("spouse_last") or "")
            spouse_first = str(params.get("spouse_first_name") or params.get("spouse_first") or "")
            if spouse_last and spouse_first:
                key = ("C1-cw-context", "OK")
                if key not in tried:
                    sp_params = dict(params)
                    sp_params["pensioner_spouse_first"] = spouse_first
                    sp_params["pensioner_spouse_last"] = spouse_last
                    plans.append(
                        QueryPlan(
                            plan_id=(
                                f"plan-refine-spouse-{pensioner_id}-"
                                f"{_stable_id(str(pensioner_id), 'OK', 'spouse')}"
                            ),
                            pensioner_id=pensioner_id,
                            strategy="C1-cw-context",
                            params=sp_params,
                            scope=PlanScope.OK,
                            reason="Refinement: spouse cross-search on OK scope.",
                            estimated_requests=1,
                        )
                    )

            # Nickname expansion
            key = ("F3-nickname", "OK")
            if key not in tried:
                plans.append(
                    QueryPlan(
                        plan_id=(
                            f"plan-refine-nickname-{pensioner_id}-"
                            f"{_stable_id(str(pensioner_id), 'OK', 'F3-nickname')}"
                        ),
                        pensioner_id=pensioner_id,
                        strategy="F3-nickname",
                        params=dict(params),
                        scope=PlanScope.OK,
                        reason="Refinement: nickname expansion on OK scope.",
                        estimated_requests=1,
                    )
                )

        else:
            # ── Tier 2: needs_review / ambiguous ──
            log.info("DeepRefinerKS: pensioner %d (score=%.3f) -> tier 2 (strategy replay).",
                     pensioner_id, top_score)

            # Strategy-replay: re-run B3-first-initial-fuzzy on OK scope
            key = ("B3-first-initial-fuzzy", "OK")
            if key not in tried:
                plans.append(
                    QueryPlan(
                        plan_id=(
                            f"plan-refine-replay-fuzzy-{pensioner_id}-"
                            f"{_stable_id(str(pensioner_id), 'OK', 'B3-first-initial-fuzzy')}"
                        ),
                        pensioner_id=pensioner_id,
                        strategy="B3-first-initial-fuzzy",
                        params=dict(params),
                        scope=PlanScope.OK,
                        reason="Refinement: strategy replay with fuzzy first-name.",
                        estimated_requests=1,
                    )
                )

            # Nickname expansion
            key = ("F3-nickname", "OK")
            if key not in tried:
                plans.append(
                    QueryPlan(
                        plan_id=(
                            f"plan-refine-nickname-{pensioner_id}-"
                            f"{_stable_id(str(pensioner_id), 'OK', 'F3-nickname')}"
                        ),
                        pensioner_id=pensioner_id,
                        strategy="F3-nickname",
                        params=dict(params),
                        scope=PlanScope.OK,
                        reason="Refinement: nickname expansion on OK scope.",
                        estimated_requests=1,
                    )
                )

            # Regiment-origin state if regiment names a state AND not in pass 1
            origin = self._infer_origin_state(regiment)
            if origin and origin != "OK":
                origin_scope = self._STATE_TO_SCOPE.get(
                    origin,
                    PlanScope.RegimentOrigin,
                )
                key = ("B1-exact", origin)
                if key not in tried:
                    plans.append(
                        QueryPlan(
                            plan_id=(
                                f"plan-refine-regiment-{pensioner_id}-"
                                f"{_stable_id(str(pensioner_id), origin, 'B1-exact')}"
                            ),
                            pensioner_id=pensioner_id,
                            strategy="B1-exact",
                            params=dict(params),
                            scope=origin_scope,
                            reason=f"Refinement: regiment origin state {origin}.",
                            estimated_requests=1,
                        )
                    )

            # Spouse cross-search if spouse name is available
            spouse_last = str(params.get("spouse_last_name") or params.get("spouse_last") or "")
            spouse_first = str(params.get("spouse_first_name") or params.get("spouse_first") or "")
            if spouse_last and spouse_first:
                key = ("C1-cw-context", "OK")
                if key not in tried:
                    sp_params = dict(params)
                    sp_params["pensioner_spouse_first"] = spouse_first
                    sp_params["pensioner_spouse_last"] = spouse_last
                    plans.append(
                        QueryPlan(
                            plan_id=(
                                f"plan-refine-spouse-{pensioner_id}-"
                                f"{_stable_id(str(pensioner_id), 'OK', 'spouse')}"
                            ),
                            pensioner_id=pensioner_id,
                            strategy="C1-cw-context",
                            params=sp_params,
                            scope=PlanScope.OK,
                            reason="Refinement: spouse cross-search on OK scope.",
                            estimated_requests=1,
                        )
                    )

        return plans

    # ----------------------------------------------------------
    # Tried-combo tracking (issue #77)
    # ----------------------------------------------------------

    def _read_tried_combos(
        self, pensioner_id: int, store: BlackboardStore
    ) -> set[tuple[str, str]]:
        """Return (strategy_name, scope) combos already tried for this
        pensioner in the current run. Reads observations from the store."""
        observations = store.read_observations_since(None)
        tried: set[tuple[str, str]] = set()
        for o in observations:
            if o.pensioner_id != pensioner_id:
                continue
            if o.kind != Kind.FaGSearchPlan:
                continue
            strategy = str(o.payload.get("strategy", ""))
            scope_raw = o.payload.get("scope", "")
            scope = str(scope_raw.value) if hasattr(scope_raw, "value") else str(scope_raw)
            if strategy and scope:
                tried.add((strategy, scope))
        return tried

    # ----------------------------------------------------------
    # Origin-state inference (mirrors RegionalPlannerKS._infer_origin_state)
    # ----------------------------------------------------------

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

    def _infer_origin_state(self, regiment: str) -> str | None:
        """Infer likely state from regiment/unit text."""
        if not regiment:
            return None
        for state_name, abbr in self._REGIMENT_STATE.items():
            if state_name in regiment:
                return abbr
        return None


# Restore the original PlanScope import -- it's used by QueryPlan constructors.
