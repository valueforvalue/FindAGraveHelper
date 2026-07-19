"""BlackboardScheduler: event-guided dispatcher for Knowledge Sources.

Reads durable work from the Blackboard store, claims ready items,
invokes eligible Knowledge Sources, and atomically posts outputs
and completion. Replaces the central god-loop with event-guided
dispatch.

Usage:
    store = SqliteBlackboardStore(db_path)
    store.open()
    scheduler = BlackboardScheduler(store)
    scheduler.register(IngestionKS())
    scheduler.register(FaGScraperKS())
    scheduler.run()
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from scripts.blackboard.schema import Observation, WorkItem, WorkState
from scripts.blackboard.store import BlackboardStore

log = logging.getLogger("scheduler")


# ============================================================
# KnowledgeSource protocol
# ============================================================


@runtime_checkable
class KnowledgeSource(Protocol):
    """A component that can produce observations from work items.

    Knowledge Sources are autonomous: the scheduler invokes them
    when eligible work exists. They never sleep or own browser state.
    """

    name: str

    def eligible(self, item: WorkItem) -> bool:
        """Return True if this KS can handle the given work item."""
        ...

    def invoke(
        self,
        item: WorkItem,
        store: BlackboardStore,
    ) -> list[Observation]:
        """Execute the work and return observations.

        The scheduler persists observations and marks the work
        complete after invoke() returns.
        """
        ...

    def estimated_cost(self, item: WorkItem) -> int:
        """Estimated request count for scheduling decisions."""
        ...


# ============================================================
# Scheduler
# ============================================================


class BlackboardScheduler:
    """Dispatches Knowledge Sources from durable work.

    Loop: claim ready work → find eligible KS → invoke → persist
    observations → complete work. Honors not_before and stale
    lease reclamation.
    """

    def __init__(
        self,
        store: BlackboardStore,
        lease_seconds: int = 30,
    ) -> None:
        self.store = store
        self.lease_seconds = lease_seconds
        self._knowledge_sources: list[KnowledgeSource] = []
        self._ks_by_name: dict[str, KnowledgeSource] = {}

    def register(self, ks: KnowledgeSource) -> None:
        """Register a Knowledge Source for dispatch."""
        self._knowledge_sources.append(ks)
        self._ks_by_name[ks.name] = ks
        log.info("Registered KnowledgeSource: %s", ks.name)

    def run(self, max_iterations: int | None = None) -> int:
        """Run the event loop until no more work or max_iterations.

        Returns the number of work items processed.
        """
        processed = 0
        while max_iterations is None or processed < max_iterations:
            dispatched = self._dispatch_one()
            if not dispatched:
                break
            processed += 1

        log.info("Scheduler finished: %d work items processed.", processed)
        return processed

    # ----------------------------------------------------------
    # Internal
    # ----------------------------------------------------------

    def _dispatch_one(self) -> bool:
        """Claim one work item and invoke the first eligible KS.

        Tries each registered KS in order until one claims work
        and produces output.
        """
        for ks in self._knowledge_sources:
            item = self.store.claim_work(ks.name, self.lease_seconds)
            if item is None:
                continue

            if not ks.eligible(item):
                # Not eligible — mark blocked so we don't keep trying
                self.store.complete_work(
                    item.work_id, WorkState.BLOCKED
                )
                continue

            try:
                observations = ks.invoke(item, self.store)
            except Exception as exc:
                log.error(
                    "KnowledgeSource %s failed on work %s: %s",
                    ks.name, item.work_id, exc,
                )
                self.store.complete_work(
                    item.work_id, WorkState.RETRYABLE
                )
                return True  # Count as dispatched (will retry)

            observation_ids = [o.observation_id for o in observations]
            self.store.complete_work(
                item.work_id, WorkState.SUCCEEDED, observation_ids
            )
            log.info(
                "KS %s completed work %s (%d observations).",
                ks.name, item.work_id, len(observations),
            )
            return True

        return False
