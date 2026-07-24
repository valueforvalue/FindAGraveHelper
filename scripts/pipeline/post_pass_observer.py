"""PostPassObserver: observation-only alternatives for CGR/DD/Spouse passes.

Phase 7 Slice 7.2 — CGR/DD/spouse post-passes append observations
only; projection owns mutable state. Canonical rows become read-only
under Blackboard.

This module provides drop-in wrappers that emit observations to the
Blackboard store instead of mutating results.jsonl in place.

Slice 1 (post-pass extraction): observation IDs are deterministic per
L11. See `scripts/post_pass/_ids.py` for the derivation.
"""
from __future__ import annotations

import logging
from typing import Any

from scripts.blackboard.schema import Kind, Observation
from scripts.post_pass._ids import deterministic_observation_id

log = logging.getLogger("post_pass_observer")


class PostPassObserver:
    """Emits observations for post-processing passes.

    Replaces in-place mutation of results.jsonl with append-only
    observations. The ProjectionBuilder reads these observations
    and derives badges/status.
    """

    def __init__(self, run_id: str = "post") -> None:
        self.run_id = run_id
        self.observations: list[Observation] = []

    def observe_cgr_corroboration(
        self,
        pensioner_id: int,
        cgr_match: dict[str, Any] | None = None,
        match_found: bool = False,
    ) -> Observation:
        """Record CGR corroboration evidence without mutating state."""
        obs = Observation(
            observation_id=deterministic_observation_id(
                kind=Kind.CGRCorroboration.value,
                pensioner_id=pensioner_id,
                source="cgr_fag_dedup",
                source_version="1",
                run_id=self.run_id,
                pass_id="post",
            ),
            pensioner_id=pensioner_id,
            kind=Kind.CGRCorroboration,
            source="cgr_fag_dedup",
            source_version="1",
            run_id=self.run_id,
            pass_id="post",
            payload={
                "match_found": match_found,
                "match_details": cgr_match or {},
            },
        )
        self.observations.append(obs)
        return obs

    def observe_dixiedata_match(
        self,
        pensioner_id: int,
        dd_match: dict[str, Any] | None = None,
        match_found: bool = False,
    ) -> Observation:
        """Record DixieData match evidence without mutating state."""
        obs = Observation(
            observation_id=deterministic_observation_id(
                kind=Kind.DixieDataMatch.value,
                pensioner_id=pensioner_id,
                source="dixiedata_match",
                source_version="1",
                run_id=self.run_id,
                pass_id="post",
            ),
            pensioner_id=pensioner_id,
            kind=Kind.DixieDataMatch,
            source="dixiedata_match",
            source_version="1",
            run_id=self.run_id,
            pass_id="post",
            payload={
                "match_found": match_found,
                "match_details": dd_match or {},
            },
        )
        self.observations.append(obs)
        return obs

    def observe_spouse_match(
        self,
        pensioner_id: int,
        spouse_match: dict[str, Any] | None = None,
        match_confirmed: bool = False,
    ) -> Observation:
        """Record spouse match evidence without mutating state."""
        obs = Observation(
            observation_id=deterministic_observation_id(
                kind=Kind.SpouseMatch.value,
                pensioner_id=pensioner_id,
                source="spouse_compare",
                source_version="1",
                run_id=self.run_id,
                pass_id="post",
            ),
            pensioner_id=pensioner_id,
            kind=Kind.SpouseMatch,
            source="spouse_compare",
            source_version="1",
            run_id=self.run_id,
            pass_id="post",
            payload={
                "match_confirmed": match_confirmed,
                "match_details": spouse_match or {},
            },
        )
        self.observations.append(obs)
        return obs

    def write_to_store(self, store: Any) -> None:
        """Write all accumulated observations to a BlackboardStore."""
        for obs in self.observations:
            store.append_observation(obs)
        log.info(
            "PostPassObserver: wrote %d observations.", len(self.observations)
        )
        self.observations.clear()
