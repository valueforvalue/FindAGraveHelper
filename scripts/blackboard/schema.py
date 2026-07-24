"""Blackboard schema: typed envelopes for the Local-First Blackboard.

Defines the versioned data contracts used by the store, scheduler,
Knowledge Sources, and projector. All dataclasses are plain — no
third-party validation dependencies.

Public surface:
  - schema_version (int)
  - RunManifest, ManifestBudget
  - Observation, Kind
  - WorkItem, WorkState, WorkAttempt
  - QueryPlan, PlanScope
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

# Bump when the shape of any schema class changes.
# v2: added WorkItem.lease_deadline_at (issue #97 heartbeat leases).
schema_version: int = 2


# ============================================================
# RunManifest
# ============================================================


@dataclass
class ManifestBudget:
    """Resource budget for one run dimension."""

    max_requests: int | None = None
    max_wall_seconds: int | None = None


@dataclass
class RunManifest:
    """Versioned record of a run's configuration and lineage.

    Persisted alongside state.jsonl as a sibling file so each run
    carries its own policy context.
    """

    manifest_id: str  # e.g. "manifest-<uuid>"
    run_id: str  # e.g. "run-<uuid>" or operator-supplied slug
    parent_manifest_id: str | None = None  # e.g. when resuming
    policy_version: str = "1"
    knowledge_source_versions: dict[str, str] = field(default_factory=dict)
    scheduler_budget: ManifestBudget = field(default_factory=ManifestBudget)
    bot_budget: ManifestBudget = field(default_factory=ManifestBudget)
    source_fingerprints: dict[str, str] = field(default_factory=dict)
    created_at: str = ""  # ISO 8601

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict. Keys are stable (insertion order)."""
        d: dict[str, Any] = {}
        d["schema_version"] = schema_version
        d["manifest_id"] = self.manifest_id
        d["run_id"] = self.run_id
        d["parent_manifest_id"] = self.parent_manifest_id
        d["policy_version"] = self.policy_version
        d["knowledge_source_versions"] = dict(self.knowledge_source_versions)
        d["scheduler_budget"] = (
            asdict(self.scheduler_budget)
            if isinstance(self.scheduler_budget, ManifestBudget)
            else self.scheduler_budget
        )
        d["bot_budget"] = (
            asdict(self.bot_budget)
            if isinstance(self.bot_budget, ManifestBudget)
            else self.bot_budget
        )
        d["source_fingerprints"] = dict(self.source_fingerprints)
        d["created_at"] = self.created_at
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunManifest":
        """Deserialize from a plain dict. Unknown keys are ignored."""
        return cls(
            manifest_id=d.get("manifest_id", ""),
            run_id=d.get("run_id", ""),
            parent_manifest_id=d.get("parent_manifest_id"),
            policy_version=d.get("policy_version", "1"),
            knowledge_source_versions=d.get("knowledge_source_versions", {}),
            scheduler_budget=ManifestBudget(**d.get("scheduler_budget", {})),
            bot_budget=ManifestBudget(**d.get("bot_budget", {})),
            source_fingerprints=d.get("source_fingerprints", {}),
            created_at=d.get("created_at", ""),
        )


# ============================================================
# Observation
# ============================================================


class Kind(str, Enum):
    """Observation kind — stable identifiers used across the system."""

    FaGSearchPlan = "FaGSearchPlan"
    FaGCandidateFetch = "FaGCandidateFetch"
    CGRCorroboration = "CGRCorroboration"
    DixieDataMatch = "DixieDataMatch"
    SpouseMatch = "SpouseMatch"
    BotWallObserved = "BotWallObserved"
    MemoryPressureObserved = "MemoryPressureObserved"
    ParseError = "ParseError"
    PensionerImported = "PensionerImported"
    ScoreObserved = "ScoreObserved"
    DecisionObserved = "DecisionObserved"


@dataclass
class Observation:
    """Durable unit of evidence from one Knowledge Source action.

    Every observation carries provenance so replay can reconstruct
    decisions without repeating network work.
    """

    observation_id: str
    pensioner_id: int
    kind: Kind
    source: str  # e.g. "search.py", "cgr_fetcher.py"
    source_version: str  # e.g. "1.0"
    run_id: str
    pass_id: str  # e.g. "1", "refinement-2"
    caused_by: str | None = None  # plan_id or observation_id that triggered this
    recorded_at: str = ""  # ISO 8601
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize with stable key order."""
        return {
            "schema_version": schema_version,
            "observation_id": self.observation_id,
            "pensioner_id": self.pensioner_id,
            "kind": self.kind.value,
            "source": self.source,
            "source_version": self.source_version,
            "run_id": self.run_id,
            "pass_id": self.pass_id,
            "caused_by": self.caused_by,
            "recorded_at": self.recorded_at,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Observation":
        """Deserialize. Kind is resolved from string value."""
        kind_raw = d.get("kind", "")
        kind = Kind(kind_raw) if kind_raw else Kind.FaGCandidateFetch
        return cls(
            observation_id=d.get("observation_id", ""),
            pensioner_id=d.get("pensioner_id", 0),
            kind=kind,
            source=d.get("source", ""),
            source_version=d.get("source_version", ""),
            run_id=d.get("run_id", ""),
            pass_id=d.get("pass_id", ""),
            caused_by=d.get("caused_by"),
            recorded_at=d.get("recorded_at", ""),
            payload=d.get("payload", {}),
        )


# ============================================================
# WorkItem
# ============================================================


class WorkState(str, Enum):
    """Work item lifecycle states."""

    READY = "ready"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    BLOCKED = "blocked"
    TERMINAL = "terminal"


@dataclass
class WorkAttempt:
    """Record of one attempt to execute a WorkItem."""

    attempt: int
    leased_at: str = ""  # ISO 8601
    leased_by: str = ""  # process/worker id
    completed_at: str = ""  # ISO 8601
    error: str | None = None


@dataclass
class WorkItem:
    """Track a unit of work independently of pensioner row presence.

    Each Knowledge Source action creates a WorkItem so the scheduler
    can claim, lease, and complete work units atomically.

    `lease_deadline_at` is the heartbeat-driven deadline (issue
    #97). Set on claim; refreshed by `store.heartbeat(work_id)`
    while `invoke()` runs. The reclaim logic reads this field
    instead of computing from `attempts[-1].leased_at + budget`,
    which lets long-running `invoke()` calls survive past their
    initial budget.
    """

    work_id: str
    pensioner_id: int
    knowledge_source: str  # e.g. "FaGScraper", "RegionalPlanner"
    plan_id: str | None = None
    pass_id: str = "1"
    input_revision: int = 1
    state: WorkState = WorkState.READY
    attempt: int = 0
    not_before: str | None = None  # ISO 8601 — enforces cooldowns
    leased_by: str | None = None
    lease_deadline_at: str | None = None  # ISO 8601 — heartbeat-driven
    completed_at: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": schema_version,
            "work_id": self.work_id,
            "pensioner_id": self.pensioner_id,
            "knowledge_source": self.knowledge_source,
            "plan_id": self.plan_id,
            "pass_id": self.pass_id,
            "input_revision": self.input_revision,
            "state": self.state.value,
            "attempt": self.attempt,
            "not_before": self.not_before,
            "leased_by": self.leased_by,
            "lease_deadline_at": self.lease_deadline_at,
            "completed_at": self.completed_at,
            "attempts": list(self.attempts),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkItem":
        state_raw = d.get("state", "ready")
        state = WorkState(state_raw) if state_raw else WorkState.READY
        return cls(
            work_id=d.get("work_id", ""),
            pensioner_id=d.get("pensioner_id", 0),
            knowledge_source=d.get("knowledge_source", ""),
            plan_id=d.get("plan_id"),
            pass_id=d.get("pass_id", "1"),
            input_revision=d.get("input_revision", 1),
            state=state,
            attempt=d.get("attempt", 0),
            not_before=d.get("not_before"),
            leased_by=d.get("leased_by"),
            lease_deadline_at=d.get("lease_deadline_at"),
            completed_at=d.get("completed_at"),
            attempts=d.get("attempts", []),
        )


# ============================================================
# QueryPlan
# ============================================================


class PlanScope(str, Enum):
    """Search scope for a QueryPlan."""

    US = "US"
    OK = "OK"
    Global = "Global"
    MemorialDetail = "MemorialDetail"
    RegimentOrigin = "RegimentOrigin"
    Texas = "Texas"
    Inferred = "Inferred"
    # Issue #78: surrounding states for OK-located pensioners.
    AR = "AR"
    KS = "KS"
    MO = "MO"
    CO = "CO"
    NM = "NM"


@dataclass
class QueryPlan:
    """Typed plan shape used by all Knowledge Sources.

    A strategy proposes a query; the planner wraps it in a QueryPlan
    with scope, rationale, and cost estimate.
    """

    plan_id: str
    pensioner_id: int
    strategy: str  # e.g. "B1-exact"
    params: dict[str, Any] = field(default_factory=dict)
    scope: PlanScope = PlanScope.OK
    reason: str = ""
    estimated_requests: int = 1
    policy_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": schema_version,
            "plan_id": self.plan_id,
            "pensioner_id": self.pensioner_id,
            "strategy": self.strategy,
            "params": dict(self.params),
            "scope": self.scope.value,
            "reason": self.reason,
            "estimated_requests": self.estimated_requests,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QueryPlan":
        scope_raw = d.get("scope", "OK")
        scope = PlanScope(scope_raw) if scope_raw else PlanScope.OK
        return cls(
            plan_id=d.get("plan_id", ""),
            pensioner_id=d.get("pensioner_id", 0),
            strategy=d.get("strategy", ""),
            params=d.get("params", {}),
            scope=scope,
            reason=d.get("reason", ""),
            estimated_requests=d.get("estimated_requests", 1),
            policy_version=d.get("policy_version", "1"),
        )
