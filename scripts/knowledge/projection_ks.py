"""ProjectionKS: emits compatibility state.jsonl from Blackboard observations.

Knowledge Source that reads all observations, applies DecisionPolicy
to derive current verdict per pensioner, and emits state.jsonl as a
byte-compatible projection for view.html and existing tooling.

This replaces the legacy append_state path — the projection becomes
the single source of current truth.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from scripts.blackboard.decision_policy import DecisionContext, classify
from scripts.blackboard.schema import Kind, Observation, WorkItem
from scripts.blackboard.store import BlackboardStore

log = logging.getLogger("projection_ks")


class ProjectionKS:
    """Builds state.jsonl projection from Blackboard observations.

    Reads all observations, groups by pensioner_id, applies the
    shared decision policy, and writes one JSONL row per pensioner.
    """

    name: str = "ProjectionKS"

    def __init__(self, output_path: Path | None = None) -> None:
        self.output_path = output_path

    def eligible(self, item: WorkItem) -> bool:
        return item.knowledge_source == "ProjectionKS"

    def invoke(
        self, item: WorkItem, store: BlackboardStore
    ) -> list[Observation]:
        """Build and write the projection."""
        observations = store.read_observations_since(None)

        # Group by pensioner
        by_pensioner: dict[int, dict[str, list[Observation]]] = {}
        for obs in observations:
            pid = obs.pensioner_id
            if pid not in by_pensioner:
                by_pensioner[pid] = {"imports": [], "candidates": [], "scores": []}
            if obs.kind == Kind.PensionerImported:
                by_pensioner[pid]["imports"].append(obs)
            elif obs.kind == Kind.FaGCandidateFetch:
                by_pensioner[pid]["candidates"].append(obs)
            elif obs.kind == Kind.ScoreObserved:
                by_pensioner[pid]["scores"].append(obs)

        rows: list[dict[str, Any]] = []
        for pid, groups in sorted(by_pensioner.items()):
            row = self._build_row(pid, groups)
            rows.append(row)

        # Write projection
        if self.output_path:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.output_path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            log.info("ProjectionKS wrote %d rows to %s.", len(rows), self.output_path)

        obs = Observation(
            observation_id=f"obs-projection-{uuid.uuid4().hex[:12]}",
            pensioner_id=0,  # run-level
            kind=Kind.DecisionObserved,
            source="ProjectionKS",
            source_version="1",
            run_id=item.pass_id,
            pass_id="1",
            caused_by=item.work_id,
            payload={"row_count": len(rows)},
        )
        store.append_observation(obs)
        return [obs]

    def estimated_cost(self, item: WorkItem) -> int:
        return 1

    def _build_row(
        self, pid: int, groups: dict[str, list[Observation]]
    ) -> dict[str, Any]:
        """Build one state.jsonl row from grouped observations."""
        imports = groups.get("imports", [])
        candidates = groups.get("candidates", [])
        scores = groups.get("scores", [])

        # Base data from import
        base: dict[str, Any] = {
            "pensioner_id": pid,
            "pensioner_name": "",
            "fag_records": [],
            "status": "no_results",
            "best_score": 0.0,
        }
        if imports:
            base.update(imports[0].payload)
            base["pensioner_id"] = pid

        # Candidate data
        fag_records = [c.payload for c in candidates]
        base["fag_records"] = fag_records

        # Decision from scores (or reclassify)
        if scores:
            decision = scores[0].payload
            base["status"] = decision.get("status", "no_results")
            base["best_score"] = decision.get("top_score", 0.0)
        elif fag_records:
            ctx = DecisionContext(candidates=fag_records)
            decision = classify(ctx)
            base["status"] = decision.status
            base["best_score"] = decision.top_score

        return base
