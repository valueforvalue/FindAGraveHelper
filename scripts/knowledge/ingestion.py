"""IngestionKS: sample Knowledge Source — loads pensioner data.

Demonstrates the KnowledgeSource seam: reads ok_pensioners.json,
posts one PensionerImported observation per pensioner.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from scripts.blackboard.schema import Kind, Observation, WorkItem, WorkState
from scripts.blackboard.store import BlackboardStore

log = logging.getLogger("ingestion_ks")

# Default input path relative to repo root
DEFAULT_INPUT = Path(__file__).parent.parent.parent / "docs" / "research" / "digitalprairie" / "ok_pensioners.json"


class IngestionKS:
    """Loads pensioner data and posts PensionerImported observations."""

    name: str = "IngestionKS"

    def __init__(self, input_path: Path | None = None) -> None:
        self.input_path = input_path or DEFAULT_INPUT

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "IngestionKS"

    def invoke(
        self, item: WorkItem, store: BlackboardStore
    ) -> list[Observation]:
        """Load pensioner data and emit observations."""
        if not self.input_path.exists():
            log.warning("Input file not found: %s", self.input_path)
            return []

        data = json.loads(self.input_path.read_text(encoding="utf-8"))
        observations: list[Observation] = []

        for entry in data:
            pid = entry.get("application_number") or entry.get("pensioner_id") or 0
            obs = Observation(
                observation_id=f"obs-ingest-{uuid.uuid4().hex[:12]}",
                pensioner_id=int(pid) if pid else 0,
                kind=Kind.PensionerImported,
                source="ok_pensioners.json",
                source_version="1",
                run_id=item.pass_id,
                pass_id="1",
                caused_by=item.work_id,
                payload=dict(entry),
            )
            store.append_observation(obs)
            observations.append(obs)

        log.info("IngestionKS imported %d pensioners.", len(observations))
        return observations

    def estimated_cost(self, item: WorkItem) -> int:
        return 1  # no network requests
