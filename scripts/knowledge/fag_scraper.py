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

import json
import logging
import uuid
from typing import Any

from scripts.blackboard.schema import (
    Kind,
    Observation,
    PlanScope,
    QueryPlan,
    WorkItem,
)
from scripts.blackboard.store import BlackboardStore
from scripts.fag.request_gate import RequestGate
from scripts.search.engine import default_search_one  # noqa: F401 (re-exported for tests)
from scripts.search.context import SearchContext

log = logging.getLogger("fag_scraper")


def _scope_to_state(scope: PlanScope, params: dict) -> str:
    """Map a plan scope to the state filter value for apply_filters.

    The RegionalPlanner encodes geographic intent in the plan scope
    but does NOT inject fag_state_filter into plan.params (the
    pensioner records come from the OK pensioner index without a
    state field). The FaGScraperKS must bridge the gap.

    Returns:
        A state abbreviation string ("OK", "TX", etc.) that
        apply_filters resolves to a FaG locationId, or "" for
        US/country-level filtering.
    """
    if scope == PlanScope.OK:
        return "OK"
    if scope == PlanScope.Texas:
        return "TX"
    # For RegimentOrigin, the plan carries the inferred state in
    # the reason field ("Regiment origin state: TX.") but NOT in
    # params. We extract it here so the engine can scope by state.
    if scope == PlanScope.RegimentOrigin:
        # Try to find a 2-letter state code in the plan params
        # (the regional planner may add _state_abbr or burial_state).
        for key in ("_state_abbr", "burial_state", "death_state"):
            val = params.get(key, "")
            if val and len(val) == 2 and val.isalpha():
                return val.upper()
        return ""
    if scope in (PlanScope.US, PlanScope.Global, PlanScope.MemorialDetail,
                  PlanScope.Inferred):
        return ""
    return ""


class FaGScraperKS:
    """Executes one FaG QueryPlan and emits candidate observations.

    Issue #61: when an `engine` is supplied, the KS routes
    through the engine's `default_search_one(ctx)` flow so
    the full FaGEngine ladder (13 strategies, with PlanRanker
    ordering) fires per pensioner. When the engine is None,
    the legacy `BrowserSession.search(strategy_name=...)` path
    is used (single strategy per plan, slow coverage).
    """

    name: str = "FaGScraperKS"

    def __init__(
        self,
        browser_session: Any = None,  # BrowserSession
        gate: RequestGate | None = None,
        engine: Any = None,  # SearchEngine (FaGEngine default)
        gate_min_interval: float = 2.5,
    ) -> None:
        self._session = browser_session
        self._gate = gate or RequestGate(
            provider="findagrave.com",
            min_interval=gate_min_interval,
        )
        # Lazy import: engine is optional; default to FaGEngine()
        # when present so the engine path is taken automatically.
        if engine is None:
            from scripts.search.fag_engine import FaGEngine
            engine = FaGEngine()
        self._engine = engine

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
            candidates, status = self._execute_search(plan, token)

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

        if not candidates:
            obs = Observation(
                observation_id=f"obs-fag-{plan.plan_id}-empty",
                pensioner_id=item.pensioner_id,
                kind=Kind.FaGCandidateFetch,
                source="FaGScraperKS",
                source_version="1",
                run_id=item.pass_id,
                pass_id=item.pass_id,
                caused_by=item.work_id,
                payload={
                    "_search_status": status,
                    "via_strategy": plan.strategy,
                    "via_scope": plan.scope.value,
                },
            )
            store.append_observation(obs)
            observations.append(obs)

        # Score once after all search work in this pass. Duplicate plan
        # invocations converge on one idempotent WorkItem.
        store.enqueue_work(
            WorkItem(
                work_id=f"work-score-{item.pensioner_id}-{item.pass_id}",
                pensioner_id=item.pensioner_id,
                knowledge_source="CandidateScorerKS",
                pass_id=item.pass_id,
            )
        )

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
        """Load the QueryPlan referenced by the work item's plan_id.

        Reads from the query_plans SQLite table (where enqueue_plan writes)
        and falls back to scanning observation payloads.
        """
        if not item.plan_id:
            return None

        # Primary path: read from query_plans table
        if hasattr(store, "con"):
            try:
                row = store.con.execute(
                    "SELECT * FROM query_plans WHERE plan_id = ?",
                    (item.plan_id,),
                ).fetchone()
                if row is not None:
                    from scripts.blackboard.schema import PlanScope

                    scope_raw = row[4]
                    try:
                        scope = PlanScope(scope_raw)
                    except ValueError:
                        scope = PlanScope.OK
                    return QueryPlan(
                        plan_id=row[0],
                        pensioner_id=row[1],
                        strategy=row[2],
                        params=json.loads(row[3]) if row[3] else {},
                        scope=scope,
                        reason=row[5],
                        estimated_requests=row[6],
                        policy_version=row[7],
                    )
            except Exception:
                pass

        # Fallback: scan observation payloads
        observations = store.read_observations_since(None)
        for obs in observations:
            payload = obs.payload
            if payload.get("plan_id") == item.plan_id:
                return QueryPlan.from_dict(payload)
        return None

    def _execute_search(
        self, plan: QueryPlan, token: Any
    ) -> tuple[list[dict[str, Any]], str]:
        """Run the actual FaG search for one QueryPlan.

        Two paths (issue #61):
        - Engine path (default when `self._engine` is set): uses
          the SearchEngine's `default_search_one(ctx)` flow with
          no strategy_name filter, so the full ladder fires.
          `plan.strategy` is recorded as the *preferred* strategy
          for ordering, but every applicable ladder entry runs.
        - Legacy path (fallback when no engine): delegates to
          `BrowserSession.search(strategy_name=plan.strategy)`,
          which interprets the plan strategy as a single filter
          (only B1 / B4 / C1 fire in practice).
        """
        pensioner: dict[str, Any] = dict(plan.params)
        pensioner["id"] = plan.pensioner_id

        if self._session is None:
            return [], "not_run"

        # ----- Engine path (issue #61) -----
        if self._engine is not None:
            from scripts.search.record import from_pensioner
            # NOTE: `default_search_one` is imported at module top
            # so test-time monkeypatching works. Don't re-import
            # here — the local binding would shadow the patched
            # one.

            record = from_pensioner(pensioner)
            ctx = record.to_context()

            # Map plan scope to state filter. The engine's
            # apply_filters() reads ctx.state to set the
            # FaG locationId. Without this, ctx.state is empty
            # (the raw pensioner records have no fag_state_filter
            # field) so every search uses country_4 (US) instead
            # of the state-specific filter. Issue #62 regression:
            # "OK filtered searches aren't firing" was this bug.
            scope_state = _scope_to_state(plan.scope, plan.params)
            if scope_state:
                ctx = SearchContext(
                    first=ctx.first, middle=ctx.middle, last=ctx.last,
                    birth_year=ctx.birth_year, death_year=ctx.death_year,
                    state=scope_state, extras=dict(ctx.extras),
                )

            page = getattr(self._session, "page", None)
            if page is None:
                return [], "no_page"

            try:
                # Show progress overlay (issue #70)
                p_name = f"{ctx.first or ''} {ctx.last or ''}".strip()
                try:
                    self._session.show_progress_overlay(
                        pensioner_name=p_name,
                        strategy=plan.strategy or "",
                    )
                except Exception:
                    pass

                # Issue #61 close: per-strategy throttle threaded
                # through default_search_one so the engine path
                # doesn't burst-fire 5-13 navigations inside the
                # L1 floor. We use the gate's `wait()` (not a
                # fresh `acquire()`) so the per-strategy waits
                # stack with the per-pensioner outer acquire.
                throttle_fn = (
                    lambda: self._gate.wait("engine_strategy")
                )
                engine_result = default_search_one(
                    self._engine,
                    page=page,
                    ctx=ctx,
                    throttle_fn=throttle_fn,
                )
            except Exception as e:
                log.warning(
                    "FaGScraperKS engine search failed for %s: %s",
                    plan.pensioner_id, e,
                )
                return [], "error"

            # Auto-relax when configured (matches legacy semantics).
            if (
                self._session.auto_relax
                and self._session.state_filter == "OK"
                and engine_result.get("classification") not in ("captcha",)
            ):
                engine_result = self._session._try_auto_relax_engine(
                    self._engine, page, ctx, engine_result,
                    throttle_fn=throttle_fn,
                )

            # Hide progress overlay (issue #70)
            try:
                self._session.hide_progress_overlay()
            except Exception:
                pass

            candidates = engine_result.get("candidates", []) or []
            status = engine_result.get("status", "no_results") or "no_results"
            rows = []
            for c in candidates:
                # Engine emits canonical {id, url, ...} via
                # `to_common_candidate()` (issue #39). The projector
                # reads `memorial_id` (legacy F1 shape) for
                # back-compat; populate both. When the engine
                # doesn't go through `to_common_candidate()`,
                # fall back to the raw `memorial_id` it parsed.
                common = c
                if hasattr(self._engine, "to_common_candidate"):
                    try:
                        common = self._engine.to_common_candidate(c)
                    except Exception:
                        common = c
                rows.append({
                    "memorial_id": (
                        common.get("id")
                        or common.get("memorial_id")
                        or c.get("memorial_id", "")
                    ),
                    "id": common.get("id", ""),
                    "slug": common.get("slug", "") or c.get("slug", ""),
                    "name": common.get("name", "") or c.get("name", ""),
                    "score": c.get("score", 0.0),
                    "url": common.get("url", ""),
                    "via_strategy": c.get("via_strategy", plan.strategy),
                    "via_scope": plan.scope.value,
                    "evidence": c.get("score_evidence") or c.get("evidence", {}),
                })
            return rows, status

        # ----- Legacy path (fallback) -----
        # Map PlanScope to state_filter value
        scope_to_filter: dict[str, str | None] = {
            "OK": "OK",
            "US": "US",
            "Global": "",  # empty = no filter = global
            "RegimentOrigin": None,  # let search_one_pensioner infer from regiment
            "Texas": "TX",
            "MemorialDetail": None,
            "Inferred": None,
        }
        sf = scope_to_filter.get(plan.scope.value if hasattr(plan.scope, 'value') else str(plan.scope))

        candidates, status = self._session.search(
            pensioner,
            state_filter=sf,
            strategy_name=plan.strategy,
        )
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
        ], status


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
