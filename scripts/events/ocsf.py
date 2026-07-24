"""OCSF event translation (issue #100).

Wraps the pipeline's native audit log (`run_audit.jsonl`) in
[OCSF](https://schema.ocsf.io/) (Open Cybersecurity Schema
Framework) format for SIEM ingestion. The sidecar file
(`run_audit.ocsf.jsonl`) is emitted alongside the native
file; the native format stays the source of truth (operators
can grep it directly).

Event mapping (see `docs/research/ocsf-mapping.md` for the
detailed rationale):

  Native event           OCSF class        activity_id  Note
  ──────────────────     ──────────────     ───────────  ────
  work_claimed           1006 SJA           1 (Create)   Blackboard claim
  work_completed         1006 SJA           3 (Complete) Blackboard finish
  strategy_ran           1006 SJA           2 (Update)   Per-strategy audit
  strategy_skipped       1006 SJA           2 (Update)   Per-strategy audit
  strategy_error         1006 SJA           2 (Update)   Per-strategy audit
  pensioner_start        1006 SJA           1 (Create)   Per-pensioner
  pensioner_end          1006 SJA           3 (Complete) Per-pensioner
  observation_appended   1006 SJA           2 (Update)   Blackboard event
  run_summary            1006 SJA           2 (Update)   Run completion
  cooldown_set           7003 PRA           2 (Update)   Throttle response
  bot_wall_observed       2004 Detection     1 (Create)   CF challenge detection

OCSF 1.8.0 reference: https://schema.ocsf.io/1.8.0/classes/
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("ocsf")

#: OCSF 1.8.0 class_uid + activity_id per native event type.
#: activity_id is the OCSF ActivityId enum:
#:   1=Create, 2=Update, 3=Complete, 4=Delete.
OCSF_MAPPING: dict[str, tuple[int, int]] = {
    # Scheduled Job Activity (1006)
    "work_claimed":         (1006, 1),
    "pensioner_start":      (1006, 1),
    "work_completed":       (1006, 3),
    "pensioner_end":        (1006, 3),
    "strategy_ran":         (1006, 2),
    "strategy_skipped":     (1006, 2),
    "strategy_error":       (1006, 2),
    "observation_appended": (1006, 2),
    "run_summary":          (1006, 2),
    # Process Remediation Activity (7003)
    "cooldown_set":         (7003, 2),
    # Detection Finding (2004)
    "bot_wall_observed":    (2004, 1),
}

#: OCSF class_uid → class_name. Only the classes we use.
_OCSF_CLASS_NAME: dict[int, str] = {
    1006: "Scheduled Job Activity",
    2004: "Detection Finding",
    7003: "Process Remediation Activity",
}


def event_to_ocsf(native: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one native event dict to an OCSF envelope.

    Returns None when the event type has no OCSF mapping
    (e.g. a future event type added before the mapping table
    is updated). Callers should skip None.
    """
    event_type = native.get("event", "")
    mapping = OCSF_MAPPING.get(event_type)
    if mapping is None:
        return None
    class_uid, activity_id = mapping

    # OCSF time is ms since epoch (int). Native ts is seconds.
    ts = native.get("ts")
    time_ms = int(ts * 1000) if ts is not None else int(time.time() * 1000)

    # Common OCSF envelope: metadata + time + class.
    ocsf: dict[str, Any] = {
        "class_uid": class_uid,
        "class_name": _OCSF_CLASS_NAME[class_uid],
        "activity_id": activity_id,
        "time": time_ms,
        "metadata": {
            "product": {
                "name": "FindAGraveHelper",
                "version": "1.0.0",
            },
            "version": "1.8.0",
        },
    }

    # Per-class payload construction.
    pensioner_id = _int_or_none(native.get("pensioner_id"))

    if class_uid == 1006:
        # Scheduled Job Activity: every native event becomes a job
        # entry. The job.name is the work_id, strategy, or
        # pensioner_id depending on the event.
        if event_type == "work_claimed":
            ocsf["job"] = {
                "name": str(native.get("work_id", "")),
                "pensioner_id": pensioner_id,
                "knowledge_source": native.get("knowledge_source", ""),
                "attempt": int(native.get("attempt", 0) or 0),
            }
        elif event_type == "work_completed":
            ocsf["job"] = {
                "name": str(native.get("work_id", "")),
                "pensioner_id": pensioner_id,
                "knowledge_source": native.get("knowledge_source", ""),
                "old_state": native.get("old_state", ""),
                "status": str(native.get("new_state", "")),
                "observation_count": int(native.get("observation_count", 0) or 0),
            }
        elif event_type in ("strategy_ran", "strategy_skipped", "strategy_error"):
            ocsf["job"] = {
                "name": f"FaGScraperKS:strategy:{native.get('strategy', 'unknown')}",
                "pensioner_id": pensioner_id,
                "strategy": native.get("strategy", ""),
                "candidates": int(native.get("candidates", 0) or 0),
                "state": native.get("state", ""),
                "error": native.get("error", ""),
                "reason": native.get("reason", ""),
            }
        elif event_type == "pensioner_start":
            ocsf["job"] = {
                "name": f"pensioner:{native.get('pensioner_id', '')}",
                "pensioner_id": pensioner_id,
                "person_name": native.get("name", ""),
            }
        elif event_type == "pensioner_end":
            ocsf["job"] = {
                "name": f"pensioner:{native.get('pensioner_id', '')}",
                "pensioner_id": pensioner_id,
                "status": native.get("status", ""),
                "candidates": int(native.get("total_candidates", 0) or 0),
                "best_score": float(native.get("best_score", 0.0) or 0.0),
                "elapsed_s": float(native.get("elapsed_s", 0.0) or 0.0),
            }
        elif event_type == "observation_appended":
            ocsf["job"] = {
                "name": str(native.get("observation_id", "")),
                "pensioner_id": pensioner_id,
                "kind": native.get("kind", ""),
                "source": native.get("source", ""),
            }
        elif event_type == "run_summary":
            ocsf["job"] = {
                "name": "run_summary",
                "total_pensioners": int(
                    native.get("total_pensioners", 0) or 0
                ),
                "total_requests": int(
                    native.get("total_requests", 0) or 0
                ),
                "cloudflare_events": int(
                    native.get("cloudflare_events", 0) or 0
                ),
                "elapsed_s": float(native.get("elapsed_s", 0.0) or 0.0),
            }

    elif class_uid == 7003:
        # Process Remediation Activity: cooldown_set is a
        # remediation action on the throttle seam.
        ocsf["remediation"] = {
            "name": "throttle_cooldown",
            "provider": native.get("provider", ""),
            "not_before": native.get("not_before", ""),
        }

    elif class_uid == 2004:
        # Detection Finding: bot_wall_observed is a CF challenge
        # detection. OCSF 'finding_info' carries the verdict +
        # the URL that triggered it.
        ocsf["finding_info"] = {
            "name": "cloudflare_bot_wall",
            "pensioner_id": pensioner_id,
            "url": native.get("url", ""),
        }

    return ocsf


def _int_or_none(v: Any) -> int | None:
    """Convert to int when possible, else None."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def sidecar_path_for(native_audit_path: Path) -> Path:
    """Compute the OCSF sidecar path for a given native audit file.

    `run_audit.jsonl` → `run_audit.ocsf.jsonl` (same stem).
    """
    return native_audit_path.with_name(
        native_audit_path.stem + ".ocsf.jsonl"
    )


def translate_audit_file(native_audit_path: Path) -> Path:
    """Read run_audit.jsonl, write run_audit.ocsf.jsonl.

    The native file is NOT modified; the sidecar is a
    one-to-one translation. Unknown event types are silently
    skipped (no crash, no malformed OCSF line).

    Args:
        native_audit_path: Path to run_audit.jsonl.

    Returns:
        Path to the written OCSF sidecar file.
    """
    out_path = sidecar_path_for(native_audit_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    translated_count = 0
    skipped_count = 0
    with native_audit_path.open(encoding="utf-8") as src, out_path.open(
        "w", encoding="utf-8"
    ) as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            try:
                native = json.loads(line)
            except json.JSONDecodeError:
                skipped_count += 1
                continue
            ocsf = event_to_ocsf(native)
            if ocsf is None:
                skipped_count += 1
                continue
            dst.write(json.dumps(ocsf, ensure_ascii=False) + "\n")
            translated_count += 1

    log.info(
        "OCSF translation: %d events translated, %d skipped. → %s",
        translated_count, skipped_count, out_path,
    )
    return out_path


__all__ = [
    "OCSF_MAPPING",
    "event_to_ocsf",
    "sidecar_path_for",
    "translate_audit_file",
]