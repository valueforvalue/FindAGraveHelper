"""BlackboardScheduler: event-guided dispatcher for Knowledge Sources.

Reads durable work from the Blackboard store, claims ready items,
invokes eligible Knowledge Sources, and atomically posts outputs
and completion. Replaces the central god-loop with event-guided
dispatch.

Issue #97: heartbeat leases. While a KnowledgeSource's invoke()
runs, the Scheduler spawns a background thread that calls
`store.heartbeat(work_id)` every `lease_seconds / 2` seconds,
extending the lease deadline. A healthy KS survives past its
initial budget; a crashed KS stops heartbeating and is reclaimed
at the deadline.

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
import threading
import time
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


def _heartbeat_loop(
    store: BlackboardStore,
    work_id: str,
    lease_seconds: int,
    stop_event: threading.Event,
) -> None:
    """Heartbeat driver (issue #97). Runs on a daemon thread.

    Calls `store.heartbeat(work_id, lease_seconds)` every
    `lease_seconds / 2` seconds until `stop_event` is set (by
    the scheduler after invoke() returns or raises). A crashed
    KS leaves this thread to die with the process; a healthy
    one stops it cleanly via the event.
    """
    interval = max(1.0, lease_seconds / 2.0)
    while not stop_event.wait(interval):
        try:
            store.heartbeat(work_id, lease_seconds=lease_seconds)
        except KeyError:
            # Work item was deleted/renamed under us; stop the loop.
            return
        except Exception as exc:
            log.warning(
                "Heartbeat for work %s failed (continuing): %s",
                work_id,
                exc,
            )


class BlackboardScheduler:
    """Dispatches Knowledge Sources from durable work.

    Loop: claim ready work → find eligible KS → invoke → persist
    observations → complete work. Honors not_before and stale
    lease reclamation. Issue #97: heartbeat thread per claim
    extends the lease deadline while invoke() runs.
    """

    def __init__(
        self,
        store: BlackboardStore,
        lease_seconds: int = 30,
        max_attempts: int = 3,
    ) -> None:
        self.store = store
        self.lease_seconds = lease_seconds
        self.max_attempts = max(max_attempts, 1)
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

        Issue #97: spawns a heartbeat thread per claim so a long-
        running invoke() survives past its initial lease budget.
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

            # Heartbeat thread: refresh lease_deadline_at every
            # lease_seconds / 2 while invoke() runs. The thread is
            # a daemon so a crashed KS can't leave it orphaned.
            stop_event = threading.Event()
            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop,
                args=(
                    self.store,
                    item.work_id,
                    self.lease_seconds,
                    stop_event,
                ),
                daemon=True,
                name=f"heartbeat-{item.work_id}",
            )
            heartbeat_thread.start()

            try:
                observations = ks.invoke(item, self.store)
            except Exception as exc:
                stop_event.set()
                heartbeat_thread.join(timeout=2.0)
                log.error(
                    "KnowledgeSource %s failed on work %s: %s",
                    ks.name, item.work_id, exc,
                )
                if item.attempt >= self.max_attempts:
                    self.store.complete_work(
                        item.work_id, WorkState.TERMINAL
                    )
                else:
                    self.store.complete_work(
                        item.work_id, WorkState.RETRYABLE
                    )
                    self.store.defer_retryable_work(
                        item.work_id,
                        time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ",
                            time.gmtime(time.time() + min(2 ** item.attempt, 60)),
                        ),
                    )
                return True

            stop_event.set()
            heartbeat_thread.join(timeout=2.0)

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
