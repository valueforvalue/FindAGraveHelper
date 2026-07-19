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
schema_version: int = 1


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
