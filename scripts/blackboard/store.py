"""BlackboardStore: durable local-first persistence layer.

Protocol + two implementations:
  - SqliteBlackboardStore (default) — SQLite WAL, kill-safe, indexed
  - JsonlBlackboardStore (fallback) — append-only JSONL for CI/tests

SQLite durability pinning:
  - journal_mode=WAL — concurrent readers, faster writes
  - synchronous=NORMAL — WAL checkpoint durability without fsync-per-write
  - isolation_level=None (autocommit) with explicit BEGIN IMMEDIATE
    per append transaction
  - fsync via conn.commit() — WAL mode flushes WAL file; synchronous=NORMAL
    ensures the WAL write is durable before commit returns. A kill -9 after
    commit() survives; an in-flight transaction may lose the last row.

Public API:
  - BlackboardStore (Protocol)
  - SqliteBlackboardStore (implementation)
  - JsonlBlackboardStore (fallback implementation)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Protocol

from scripts.blackboard.schema import (
    Observation,
    QueryPlan,
    WorkItem,
    WorkState,
)


# ============================================================
# BlackboardObserver
# ============================================================


class BlackboardObserver(Protocol):
    """Observer that receives notifications from the Blackboard store.

    Register with SqliteBlackboardStore.register_observer().
    Every callback is a fire-and-forget notification; the store
    does not wait for the observer. Observers are called only
    after the store operation succeeds (post-commit).
    """

    def on_observation_appended(self, obs: Observation) -> None:
        """Called after an observation is durably written."""
        ...

    def on_work_claimed(
        self, item: WorkItem, knowledge_source: str
    ) -> None:
        """Called after a work item is claimed (leased)."""
        ...

    def on_work_completed(
        self,
        work_id: str,
        pensioner_id: int,
        knowledge_source: str,
        old_state: str,
        new_state: WorkState,
        observation_ids: list[str] | None,
    ) -> None:
        """Called after a work item transitions to a terminal state."""
        ...

    def on_cooldown_set(
        self, provider: str, not_before: str
    ) -> None:
        """Called after a provider cooldown is set."""
        ...


# ============================================================
# BlackboardStore Protocol
# ============================================================


class BlackboardStore(Protocol):
    """Durable local-first store for observations, work items, and plans."""

    def append_observation(self, obs: Observation) -> None:
        """Durably write one observation."""
        ...

    def enqueue_work(self, item: WorkItem) -> None:
        """Enqueue a work item for future claim."""
        ...

    def claim_work(
        self,
        knowledge_source: str,
        lease_seconds: int = 30,
    ) -> WorkItem | None:
        """Claim next ready work item. Returns None if none available."""
        ...

    def complete_work(
        self,
        work_id: str,
        status: WorkState,
        observation_ids: list[str] | None = None,
    ) -> None:
        """Mark work item complete and optionally link observations."""
        ...

    def defer_retryable_work(self, work_id: str, not_before: str) -> None:
        """Move retryable work to ready with an earliest retry time."""
        ...

    def set_provider_not_before(self, provider: str, until: str) -> None:
        """Set provider-wide cooldown deadline (ISO 8601)."""
        ...

    def read_observations_since(
        self, cursor: str | None
    ) -> list[Observation]:
        """Read observations recorded after the given cursor (ISO 8601)."""
        ...

    def read_observations_for_pensioner(
        self, pensioner_id: int
    ) -> list[Observation]:
        """Read observations for one pensioner in durable order."""
        ...

    def has_pending_work(self, pensioner_id: int) -> bool:
        """Return True when pensioner has ready/leased/retryable work."""
        ...

    def enqueue_plan(self, plan: QueryPlan) -> None:
        """Store a query plan for later execution."""
        ...

    def close(self) -> None:
        """Close the store cleanly."""
        ...


# ============================================================
# SQLite Implementation
# ============================================================


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    pensioner_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    source_version TEXT NOT NULL,
    run_id TEXT NOT NULL,
    pass_id TEXT NOT NULL,
    caused_by TEXT,
    recorded_at TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS work_items (
    work_id TEXT PRIMARY KEY,
    pensioner_id INTEGER NOT NULL,
    knowledge_source TEXT NOT NULL,
    plan_id TEXT,
    pass_id TEXT NOT NULL DEFAULT '1',
    input_revision INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'ready',
    attempt INTEGER NOT NULL DEFAULT 0,
    not_before TEXT,
    leased_by TEXT,
    lease_deadline_at TEXT,
    completed_at TEXT,
    attempts TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS work_observations (
    work_id TEXT NOT NULL REFERENCES work_items(work_id),
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    PRIMARY KEY (work_id, observation_id)
);

CREATE TABLE IF NOT EXISTS provider_cooldowns (
    provider TEXT PRIMARY KEY,
    not_before TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_plans (
    plan_id TEXT PRIMARY KEY,
    pensioner_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    scope TEXT NOT NULL DEFAULT 'OK',
    reason TEXT NOT NULL DEFAULT '',
    estimated_requests INTEGER NOT NULL DEFAULT 1,
    policy_version TEXT NOT NULL DEFAULT '1'
);

CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obs_pensioner ON observations(pensioner_id);
CREATE INDEX IF NOT EXISTS idx_obs_recorded ON observations(recorded_at);
CREATE INDEX IF NOT EXISTS idx_work_state ON work_items(state, not_before);
CREATE INDEX IF NOT EXISTS idx_work_ks ON work_items(knowledge_source);
CREATE INDEX IF NOT EXISTS idx_plans_pensioner ON query_plans(pensioner_id);
"""


class SqliteBlackboardStore:
    """SQLite WAL-backed BlackboardStore implementation."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._con: sqlite3.Connection | None = None
        self._observers: list[BlackboardObserver] = []

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------

    def open(self) -> None:
        """Open (or create) the SQLite database with WAL pragmas."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False allows the heartbeat thread
        # (issue #97) to call store.heartbeat() concurrently. Writes
        # are serialized via self._write_lock so the SQLite WAL mode
        # still gets correct per-row sequencing.
        self._con = sqlite3.connect(
            str(self._path),
            isolation_level=None,
            check_same_thread=False,
        )
        self._write_lock = threading.Lock()
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.executescript(_SCHEMA_SQL)
        self._migrate_work_items_schema()

    def close(self) -> None:
        """Close the database cleanly."""
        if self._con is not None:
            self._con.close()
            self._con = None

    # ----------------------------------------------------------
    # Schema migration (issue #97 heartbeat leases)
    # ----------------------------------------------------------

    def _migrate_work_items_schema(self) -> None:
        """Add `lease_deadline_at` column to existing work_items
        tables that predate issue #97. Idempotent: skips if the
        column already exists.

        SQLite has no `ADD COLUMN IF NOT EXISTS`, so check
        pragma_table_info first. The column is nullable with no
        default, matching the WorkItem.lease_deadline_at field
        (None until a claim sets it).
        """
        rows = self.con.execute(
            "PRAGMA table_info(work_items)"
        ).fetchall()
        column_names = {row[1] for row in rows}
        if "lease_deadline_at" not in column_names:
            self.con.execute(
                "ALTER TABLE work_items ADD COLUMN lease_deadline_at TEXT"
            )

    # ----------------------------------------------------------
    # Observers
    # ----------------------------------------------------------

    def register_observer(self, observer: BlackboardObserver) -> None:
        """Register an observer to receive store notifications."""
        self._observers.append(observer)

    def unregister_observer(self, observer: BlackboardObserver) -> None:
        """Remove a previously registered observer."""
        try:
            self._observers.remove(observer)
        except ValueError:
            pass

    # ----------------------------------------------------------

    @property
    def con(self) -> sqlite3.Connection:
        if self._con is None:
            raise RuntimeError("SqliteBlackboardStore not opened")
        return self._con

    # ----------------------------------------------------------
    # Observations
    # ----------------------------------------------------------

    def append_observation(self, obs: Observation) -> None:
        """Durably write one observation; duplicate IDs are idempotent."""
        now = obs.recorded_at or _now_iso()
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute(
                """INSERT OR IGNORE INTO observations
                   (observation_id, pensioner_id, kind, source,
                    source_version, run_id, pass_id, caused_by,
                    recorded_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    obs.observation_id,
                    obs.pensioner_id,
                    obs.kind.value,
                    obs.source,
                    obs.source_version,
                    obs.run_id,
                    obs.pass_id,
                    obs.caused_by,
                    now,
                    json.dumps(obs.payload, ensure_ascii=False),
                ),
            )
            self.con.commit()
            # Notify observers post-commit.
            for observer in self._observers:
                try:
                    observer.on_observation_appended(obs)
                except Exception:
                    pass  # observer failures never block the store
        except Exception:
            self.con.rollback()
            raise

    def read_observations_since(
        self, cursor: str | None
    ) -> list[Observation]:
        """Return observations recorded after cursor (ISO 8601)."""
        if cursor is None:
            rows = self.con.execute(
                "SELECT * FROM observations ORDER BY recorded_at"
            ).fetchall()
        else:
            rows = self.con.execute(
                "SELECT * FROM observations WHERE recorded_at > ? ORDER BY recorded_at",
                (cursor,),
            ).fetchall()
        return [_row_to_observation(r) for r in rows]

    # ----------------------------------------------------------
    # Work items
    # ----------------------------------------------------------

    def enqueue_work(self, item: WorkItem) -> None:
        """Insert a work item if not already present."""
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute(
                """INSERT OR IGNORE INTO work_items
                   (work_id, pensioner_id, knowledge_source, plan_id,
                    pass_id, input_revision, state, attempt, not_before,
                    leased_by, completed_at, attempts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.work_id,
                    item.pensioner_id,
                    item.knowledge_source,
                    item.plan_id,
                    item.pass_id,
                    item.input_revision,
                    item.state.value,
                    item.attempt,
                    item.not_before,
                    item.leased_by,
                    item.completed_at,
                    json.dumps(item.attempts, ensure_ascii=False),
                ),
            )
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    def claim_work(
        self,
        knowledge_source: str,
        lease_seconds: int = 30,
    ) -> WorkItem | None:
        """Claim next ready work item, honoring not_before and stale leases.

        Issue #97: the claim writes `lease_deadline_at = now + lease_seconds`.
        The reclaim branch below reads this column (not attempts[-1].leased_at)
        so a long-running `invoke()` survives past its initial budget via
        heartbeats.
        """
        now = _now_iso()
        # Legacy fallback: when lease_deadline_at is NULL (older rows
        # migrated before this field existed), fall back to the old
        # heuristic of `attempts[-1].leased_at + 2 * lease_seconds`.
        # New claims always populate the column.
        self.con.execute(
            """UPDATE work_items
               SET state = 'ready', leased_by = NULL, attempt = attempt
               WHERE state = 'leased'
                 AND knowledge_source = ?
                 AND completed_at IS NULL
                 AND leased_by IS NOT NULL
                 AND (
                     (lease_deadline_at IS NOT NULL AND lease_deadline_at < ?)
                     OR (
                         lease_deadline_at IS NULL
                         AND (
                             SELECT MAX(json_extract(value, '$.leased_at'))
                             FROM json_each(attempts)
                         ) < ?
                     )
                 )""",
            (knowledge_source, now, _iso_delta(-lease_seconds * 2)),
        )

        # Claim next ready item
        row = self.con.execute(
            """SELECT * FROM work_items
               WHERE knowledge_source = ?
                 AND state = 'ready'
                 AND (not_before IS NULL OR not_before <= ?)
               ORDER BY work_id
               LIMIT 1""",
            (knowledge_source, now),
        ).fetchone()

        if row is None:
            return None

        item = _row_to_workitem(row)
        lease_at = now
        lease_deadline_at = _iso_delta(lease_seconds)
        new_attempts = list(item.attempts)
        new_attempts.append({
            "attempt": item.attempt + 1,
            "leased_at": lease_at,
            "leased_by": f"proc-{os.getpid()}",
        })

        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute(
                """UPDATE work_items
                   SET state = 'leased', attempt = ?,
                       leased_by = ?, lease_deadline_at = ?,
                       attempts = ?
                   WHERE work_id = ? AND state = 'ready'""",
                (
                    item.attempt + 1,
                    f"proc-{os.getpid()}",
                    lease_deadline_at,
                    json.dumps(new_attempts, ensure_ascii=False),
                    item.work_id,
                ),
            )
            self.con.commit()
        except Exception:
            self.con.rollback()
            return None

        item.state = WorkState.LEASED
        item.attempt += 1
        item.leased_by = f"proc-{os.getpid()}"
        item.lease_deadline_at = lease_deadline_at
        item.attempts = new_attempts

        # Notify observers.
        for observer in self._observers:
            try:
                observer.on_work_claimed(item, knowledge_source)
            except Exception:
                pass

        return item

    def heartbeat(self, work_id: str, lease_seconds: int = 30) -> None:
        """Extend a leased work item's `lease_deadline_at` by `lease_seconds`.

        Issue #97 heartbeat leases: the Scheduler calls this on a
        background thread while a KnowledgeSource's `invoke()` runs.
        A crashed KS that stops heartbeating will be reclaimed at
        the deadline; a healthy KS that heartbeats survives past
        its initial budget.

        Thread-safe: the heartbeat thread runs on a thread other
        than the one that opened the connection. The write is
        serialized via `self._write_lock` so SQLite WAL mode gets
        correct per-row sequencing (issue #97 follow-up: the
        earlier `check_same_thread=False` was needed but writes
        still need to be ordered).

        Raises KeyError if `work_id` doesn't exist — strict path
        so callers notice typos rather than silently dropping
        heartbeats.

        No-op if the work item is no longer leased (e.g. it was
        completed or reclaimed between heartbeat ticks).
        """
        deadline = _iso_delta(lease_seconds)
        with self._write_lock:
            cursor = self.con.execute(
                """UPDATE work_items
                   SET lease_deadline_at = ?
                   WHERE work_id = ?
                     AND state = 'leased'
                     AND leased_by IS NOT NULL""",
                (deadline, work_id),
            )
            if cursor.rowcount == 0:
                # Either the work_id doesn't exist OR the item
                # isn't currently leased. Distinguish via a SELECT.
                row = self.con.execute(
                    "SELECT 1 FROM work_items WHERE work_id = ?",
                    (work_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(
                        f"No work item with work_id={work_id!r}"
                )
            # Item exists but isn't leased: silent no-op. Common
            # when a heartbeat races with complete_work / reclaim.

    def complete_work(
        self,
        work_id: str,
        status: WorkState,
        observation_ids: list[str] | None = None,
    ) -> None:
        """Mark work item complete; optionally link observations."""
        # Snapshot old state before update for observer notification.
        old_row = self.con.execute(
            "SELECT state, pensioner_id, knowledge_source FROM work_items WHERE work_id = ?",
            (work_id,),
        ).fetchone()
        old_state = old_row[0] if old_row else "ready"
        pensioner_id = old_row[1] if old_row else 0
        knowledge_source = old_row[2] if old_row else ""

        now = _now_iso()
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute(
                """UPDATE work_items
                   SET state = ?, completed_at = ?
                   WHERE work_id = ?""",
                (status.value, now, work_id),
            )
            if observation_ids:
                for oid in observation_ids:
                    self.con.execute(
                        """INSERT OR IGNORE INTO work_observations
                           (work_id, observation_id) VALUES (?, ?)""",
                        (work_id, oid),
                    )
            self.con.commit()
            # Notify observers.
            for observer in self._observers:
                try:
                    observer.on_work_completed(
                        work_id=work_id,
                        pensioner_id=pensioner_id,
                        knowledge_source=knowledge_source,
                        old_state=old_state,
                        new_state=status,
                        observation_ids=observation_ids,
                    )
                except Exception:
                    pass
        except Exception:
            self.con.rollback()
            raise

    def defer_retryable_work(self, work_id: str, not_before: str) -> None:
        """Move retryable work to ready with an earliest retry time."""
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute(
                """UPDATE work_items
                   SET state = 'ready', leased_by = NULL,
                       completed_at = NULL, not_before = ?
                   WHERE work_id = ? AND state = 'retryable'""",
                (not_before, work_id),
            )
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    # ----------------------------------------------------------
    # Provider cooldowns
    # ----------------------------------------------------------

    def set_provider_not_before(self, provider: str, until: str) -> None:
        """Set (or replace) provider-wide cooldown deadline."""
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute(
                """INSERT OR REPLACE INTO provider_cooldowns
                   (provider, not_before) VALUES (?, ?)""",
                (provider, until),
            )
            self.con.commit()
            # Notify observers.
            for observer in self._observers:
                try:
                    observer.on_cooldown_set(provider, until)
                except Exception:
                    pass
        except Exception:
            self.con.rollback()
            raise

    def get_provider_not_before(self, provider: str) -> str | None:
        """Return the not_before deadline for a provider, or None."""
        row = self.con.execute(
            "SELECT not_before FROM provider_cooldowns WHERE provider = ?",
            (provider,),
        ).fetchone()
        return row[0] if row else None

    # ----------------------------------------------------------
    # Query plans
    # ----------------------------------------------------------

    def read_observations_for_pensioner(
        self, pensioner_id: int
    ) -> list[Observation]:
        """Return one pensioner's observations in stable insertion order."""
        rows = self.con.execute(
            """SELECT * FROM observations
               WHERE pensioner_id = ?
               ORDER BY recorded_at, rowid""",
            (pensioner_id,),
        ).fetchall()
        return [_row_to_observation(row) for row in rows]

    def has_pending_work(self, pensioner_id: int) -> bool:
        """Return True when work remains nonterminal for pensioner."""
        row = self.con.execute(
            """SELECT 1 FROM work_items
               WHERE pensioner_id = ?
                 AND state IN ('ready', 'leased', 'retryable')
               LIMIT 1""",
            (pensioner_id,),
        ).fetchone()
        return row is not None

    def enqueue_plan(self, plan: QueryPlan) -> None:
        """Store a query plan."""
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute(
                """INSERT OR IGNORE INTO query_plans
                   (plan_id, pensioner_id, strategy, params, scope,
                    reason, estimated_requests, policy_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.plan_id,
                    plan.pensioner_id,
                    plan.strategy,
                    json.dumps(plan.params, ensure_ascii=False),
                    plan.scope.value,
                    plan.reason,
                    plan.estimated_requests,
                    plan.policy_version,
                ),
            )
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise


# ============================================================
# JSONL fallback implementation
# ============================================================


class JsonlBlackboardStore:
    """Append-only JSONL store for CI/test environments.

    Not suitable for production (no indexed lookup, no leasing).
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append_observation(self, obs: Observation) -> None:
        line = json.dumps(obs.to_dict(), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def enqueue_work(self, item: WorkItem) -> None:
        pass  # no-op in JSONL fallback

    def claim_work(
        self, knowledge_source: str, lease_seconds: int = 30
    ) -> WorkItem | None:
        return None  # not supported

    def complete_work(
        self,
        work_id: str,
        status: WorkState,
        observation_ids: list[str] | None = None,
    ) -> None:
        pass

    def defer_retryable_work(self, work_id: str, not_before: str) -> None:
        pass

    def set_provider_not_before(self, provider: str, until: str) -> None:
        pass

    def read_observations_since(
        self, cursor: str | None
    ) -> list[Observation]:
        return []

    def read_observations_for_pensioner(
        self, pensioner_id: int
    ) -> list[Observation]:
        return []

    def has_pending_work(self, pensioner_id: int) -> bool:
        return False

    def enqueue_plan(self, plan: QueryPlan) -> None:
        pass

    def close(self) -> None:
        pass

    def register_observer(self, observer: BlackboardObserver) -> None:
        pass  # no-op in JSONL fallback

    def unregister_observer(self, observer: BlackboardObserver) -> None:
        pass  # no-op in JSONL fallback


# ============================================================
# Helpers
# ============================================================


def _now_iso() -> str:
    """Current UTC time as ISO 8601."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_delta(seconds: int) -> str:
    """ISO 8601 timestamp offset by seconds from now."""
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds)
    )


def _row_to_observation(row: tuple) -> Observation:
    """Convert a SQLite row to an Observation."""
    return Observation(
        observation_id=row[0],
        pensioner_id=row[1],
        kind=row[2],  # Kind enum handles str
        source=row[3],
        source_version=row[4],
        run_id=row[5],
        pass_id=row[6],
        caused_by=row[7],
        recorded_at=row[8],
        payload=json.loads(row[9]) if row[9] else {},
    )


def _row_to_workitem(row: tuple) -> WorkItem:
    """Convert a SQLite row to a WorkItem.

    Index map (matches CREATE TABLE order in _SCHEMA_SQL after
    issue #97 added lease_deadline_at):
        0 work_id, 1 pensioner_id, 2 knowledge_source, 3 plan_id,
        4 pass_id, 5 input_revision, 6 state, 7 attempt,
        8 not_before, 9 leased_by, 10 lease_deadline_at,
        11 completed_at, 12 attempts.
    """
    return WorkItem(
        work_id=row[0],
        pensioner_id=row[1],
        knowledge_source=row[2],
        plan_id=row[3],
        pass_id=row[4],
        input_revision=row[5],
        state=WorkState(row[6]) if row[6] else WorkState.READY,
        attempt=row[7],
        not_before=row[8],
        leased_by=row[9],
        lease_deadline_at=row[10],
        completed_at=row[11],
        attempts=json.loads(row[12]) if row[12] else [],
    )
