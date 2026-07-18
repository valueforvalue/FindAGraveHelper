"""Dry-run mode for the unified pipeline (issue #21).

The dry-run branch exercises the non-FaG parts of the pipeline
(matching, scoring, CGR cross-reference, BOTH MATCH detection)
against an existing state.jsonl, without ever making a FaG
network request. The output is a JSONL diff file showing which
records would change if the pipeline ran for real.

This module owns:
  - The diff schema (one record per pensioner with would_change flag)
  - The atomic-write discipline for the diff file
  - The "what counts as a change" rule (excludes runtime fields
    like timestamp that always differ between runs)

Public API:
  - diff_record(current, predicted) -> dict
  - predict_outcome_from_state(record, low_score_threshold) -> dict
  - write_dry_run_diff(out_path, current_state_path, predictions) -> int
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from scripts.state.repository import JsonlStateRepository


# Fields whose change between current and predicted does NOT count
# as a real semantic change. These are runtime metadata that
# naturally differs between runs (timestamps, run IDs, etc.).
IGNORED_DIFF_FIELDS = frozenset({"timestamp"})


def diff_record(current: dict, predicted: dict) -> dict:
    """Compute a diff between current state and predicted state.

    Returns a dict with:
      - pensioner_id
      - current_outcome (status field, or None if no current record)
      - predicted_outcome (status field)
      - current_score (best_score, or None)
      - predicted_score (best_score)
      - fag_status_current, fag_status_predicted
      - fields_changed: list of field names that differ
      - would_change: True if fields_changed is non-empty (after
        excluding IGNORED_DIFF_FIELDS)
    """
    fields_changed = []
    all_keys = set(current.keys()) | set(predicted.keys())
    for key in sorted(all_keys):
        if key in IGNORED_DIFF_FIELDS:
            continue
        cv = current.get(key)
        pv = predicted.get(key)
        if cv != pv:
            fields_changed.append(key)
    return {
        "pensioner_id": predicted.get("pensioner_id") or current.get("pensioner_id"),
        "current_outcome": current.get("status"),
        "predicted_outcome": predicted.get("status"),
        "current_score": current.get("best_score"),
        "predicted_score": predicted.get("best_score"),
        "fag_status_current": current.get("fag_status"),
        "fag_status_predicted": predicted.get("fag_status"),
        "fields_changed": fields_changed,
        "would_change": bool(fields_changed),
    }


def predict_outcome_from_state(record: dict, low_score_threshold: float) -> dict:
    """Derive a predicted PensionerRecord from an existing state record.

    Used by --dry-run: the operator already has state.jsonl with
    fag_records populated. We re-derive the outcome (status, best_score)
    from those records WITHOUT issuing any new FaG requests.

    The returned dict is a "predicted" copy of the input, with
    status + best_score recomputed from fag_records. If fag_status
    is 'no_results' or fag_records is empty, the prediction carries
    that through unchanged.

    Issue #28 follow-up: the threshold values + status strings
    are imported from scoring_constants so dry-run cannot drift
    from production.
    """
    from scripts.pipeline.scoring_constants import (
        AUTO_ACCEPT_THRESHOLD,
        STATUS_NO_RESULTS,
        derive_status_from_score_only,
    )
    predicted = dict(record)  # shallow copy
    fag_records = record.get("fag_records", []) or []
    best_score = 0.0
    best_candidate = None
    for c in fag_records:
        s = c.get("score", 0.0) or 0.0
        if s > best_score:
            best_score = s
            best_candidate = c
    predicted["best_score"] = best_score
    predicted["best_candidate"] = best_candidate

    # No fag_records -> no FaG was run; force 'no_results'.
    # Otherwise: re-derive the status from best_score alone, so
    # the dry-run + state-replay paths classify records as if
    # the current threshold were applied fresh (ignoring whatever
    # fag_status was previously set). This is the A/B-test
    # behavior operators want.
    if not fag_records:
        predicted["status"] = STATUS_NO_RESULTS
    else:
        predicted["status"] = derive_status_from_score_only(
            best_score=best_score,
            low_score_threshold=low_score_threshold,
            auto_accept_threshold=AUTO_ACCEPT_THRESHOLD,
        )
    return predicted


def write_dry_run_diff(
    out_path: Path,
    current_state_path: Path,
    predictions: Iterable[dict],
) -> int:
    """Write a JSONL diff file comparing current state to predictions.

    Returns the number of records whose predicted outcome differs
    from the current outcome.

    Atomic via .tmp + os.replace.
    """
    current_path = Path(current_state_path)
    out_path = Path(out_path)

    # Index current records by pensioner_id
    current_index: dict[int, dict] = {}
    for rec in JsonlStateRepository(current_path).iter_all():
        pid = rec.get("pensioner_id")
        if pid is not None:
            current_index[pid] = rec

    # Index predictions by pensioner_id
    pred_index: dict[int, dict] = {}
    for rec in predictions:
        pid = rec.get("pensioner_id")
        if pid is not None:
            pred_index[pid] = rec

    # Diff: every pensioner in current state, every pensioner in predictions
    all_pids = sorted(set(current_index.keys()) | set(pred_index.keys()))
    diffs = []
    n_changed = 0
    for pid in all_pids:
        current = current_index.get(pid, {})
        predicted = pred_index.get(pid)
        if predicted is None:
            # No prediction available — flag as change with note
            diff = diff_record(current, current)
            diff["predicted_outcome"] = None
            diff["predicted_score"] = None
            diff["fag_status_predicted"] = None
            diff["notes"] = "no prediction available (would need new FaG query)"
            diff["would_change"] = True
            diffs.append(diff)
            n_changed += 1
            continue
        diff = diff_record(current, predicted)
        diffs.append(diff)
        if diff["would_change"]:
            n_changed += 1

    # Atomic write
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for diff in diffs:
            f.write(json.dumps(diff, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, out_path)
    return n_changed