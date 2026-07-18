"""state-replay for the unified pipeline (issue #21).

Read an OLD state.jsonl and apply the non-FaG pipeline stages
(matching, scoring, BOTH MATCH detection) to produce a NEW
state.jsonl. Useful for A/B testing strategy changes against
historical state without re-running FaG.

Public API:
  - replay_state(old_state_path, new_state_path, low_score_threshold) -> int
  - list_replay_changes(old_state_path, new_state_path) -> dict
"""
from __future__ import annotations

<<<<<<< HEAD
=======
import json
import os
>>>>>>> origin/feat/reversibility-flags
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from scripts.state.repository import JsonlStateRepository
from scripts.pipeline.dry_run import predict_outcome_from_state


def replay_state(
    old_state_path: Path,
    new_state_path: Path,
    low_score_threshold: float,
) -> int:
    """Read old_state, apply non-FaG pipeline, write new_state.

    Returns the number of records replayed. Returns 0 if old_state
    doesn't exist (nothing to replay).

<<<<<<< HEAD
    Atomic via JsonlStateRepository.replace_all (issue #28).
=======
    Atomic via .tmp + os.replace on the new_state_path.
>>>>>>> origin/feat/reversibility-flags
    """
    old_state_path = Path(old_state_path)
    new_state_path = Path(new_state_path)

    if not old_state_path.exists():
        return 0

    replayed_at = datetime.now(timezone.utc).isoformat()
    old_records = list(JsonlStateRepository(old_state_path).iter_all())
    new_records = []
    for rec in old_records:
        predicted = predict_outcome_from_state(rec, low_score_threshold)
        predicted["replayed_at"] = replayed_at
        predicted["replayed_from"] = str(old_state_path)
        # Preserve fag_records unchanged — those are the historical
        # artifact being carried forward.
        new_records.append(predicted)

<<<<<<< HEAD
    # Issue #28: route JSONL write through JsonlStateRepository.
    # The Repository owns the atomic-write discipline + L5
    # newline-delimited format. Previously duplicated here.
    JsonlStateRepository(new_state_path).replace_all(new_records)
=======
    # Atomic write
    new_state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = new_state_path.with_suffix(new_state_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for rec in new_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, new_state_path)
>>>>>>> origin/feat/reversibility-flags
    return len(new_records)


def list_replay_changes(
    old_state_path: Path,
    new_state_path: Path,
) -> dict:
    """Compare two state files; return counts of status changes.

    Useful for verifying a replay had the expected effect.
    Returns {total, status_changed, unchanged}.
    """
    if not old_state_path.exists() or not new_state_path.exists():
        return {"total": 0, "status_changed": 0, "unchanged": 0}

    old_records = {
        r.get("pensioner_id"): r
        for r in JsonlStateRepository(old_state_path).iter_all()
    }
    new_records = {
        r.get("pensioner_id"): r
        for r in JsonlStateRepository(new_state_path).iter_all()
    }
    all_pids = sorted(set(old_records.keys()) | set(new_records.keys()))
    status_changed = 0
    unchanged = 0
    for pid in all_pids:
        old_status = old_records.get(pid, {}).get("status")
        new_status = new_records.get(pid, {}).get("status")
        if old_status != new_status:
            status_changed += 1
        else:
            unchanged += 1
    return {
        "total": len(all_pids),
        "status_changed": status_changed,
        "unchanged": unchanged,
    }