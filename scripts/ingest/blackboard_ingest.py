"""Ingestion Blackboard integration — Phase 6 Slice 6.4.

Wraps existing ingest modules to post PensionerImported observations
to the Blackboard store instead of (or in addition to) file output.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from scripts.blackboard.schema import Kind, Observation
from scripts.blackboard.store import BlackboardStore

log = logging.getLogger("ingest_blackboard")


def ingest_to_blackboard(
    store: BlackboardStore,
    input_path: Path,
    run_id: str = "ingest",
    max_records: int | None = None,
) -> int:
    """Read pensioner data from file and post observations to store.

    Args:
        store: an opened BlackboardStore.
        input_path: JSON or JSONL file with pensioner records.
        run_id: run identifier.
        max_records: stop after N records (None = all).

    Returns:
        Number of records imported.
    """
    import json

    if not input_path.exists():
        log.warning("Input file not found: %s", input_path)
        return 0

    raw = input_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # JSONL — one JSON per line
        data = []
        for line in raw.strip().split("\n"):
            if line.strip():
                data.append(json.loads(line))

    if isinstance(data, dict):
        data = [data]

    count = 0
    for entry in data:
        if max_records is not None and count >= max_records:
            break

        pid = entry.get("application_number") or entry.get("pensioner_id") or count
        obs = Observation(
            observation_id=f"obs-ingest-bb-{uuid.uuid4().hex[:12]}",
            pensioner_id=int(pid) if pid else count,
            kind=Kind.PensionerImported,
            source=input_path.name,
            source_version="1",
            run_id=run_id,
            pass_id="ingest",
            payload=dict(entry),
        )
        store.append_observation(obs)
        count += 1

    log.info("Ingested %d records from %s to Blackboard.", count, input_path)
    return count
