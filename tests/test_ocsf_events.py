"""Tests for the OCSF event translation (#100).

Wraps the pipeline's native audit log (run_audit.jsonl) in
OCSF (Open Cybersecurity Schema Framework) format for SIEM
ingestion. The sidecar file (run_audit.ocsf.jsonl) is
emitted alongside the native file; the native format stays
the source of truth (operators can grep it directly).

Event mapping:
  - work_claimed        → 1006 Scheduled Job Activity (activity 1=Create)
  - work_completed      → 1006 Scheduled Job Activity (activity 3=Complete)
  - strategy_ran        → 1006 Scheduled Job Activity (activity 2=Update, w/ candidate count)
  - strategy_skipped    → 1006 Scheduled Job Activity (activity 2=Update, no candidates)
  - strategy_error      → 1006 Scheduled Job Activity (activity 2=Update, error)
  - pensioner_start     → 1006 Scheduled Job Activity (activity 1=Create)
  - pensioner_end       → 1006 Scheduled Job Activity (activity 3=Complete)
  - observation_appended → 1006 Scheduled Job Activity (activity 2=Update)
  - cooldown_set        → 7003 Process Remediation Activity (response to detection)
  - bot_wall_observed   → 2004 Detection Finding
  - memory_pressure     → 2004 Detection Finding
  - run_summary         → 1006 Scheduled Job Activity (activity 2=Update)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.events.ocsf import (
    OCSF_MAPPING,
    event_to_ocsf,
    sidecar_path_for,
    translate_audit_file,
)


# ============================================================
# Mapping table
# ============================================================


def test_mapping_covers_all_native_event_types():
    """Every native event type has an OCSF class + activity mapping."""
    expected_events = {
        "work_claimed",
        "work_completed",
        "strategy_ran",
        "strategy_skipped",
        "strategy_error",
        "pensioner_start",
        "pensioner_end",
        "observation_appended",
        "cooldown_set",
        "bot_wall_observed",
        "run_summary",
    }
    assert set(OCSF_MAPPING.keys()) == expected_events


def test_mapping_class_uids_are_valid_ocsf_classes():
    """Each mapping entry carries a real OCSF class_uid (integer)
    and a class_name string."""
    valid_uids = {
        1006: "Scheduled Job Activity",
        2004: "Detection Finding",
        7003: "Process Remediation Activity",
    }
    for event, (uid, activity_id) in OCSF_MAPPING.items():
        assert isinstance(uid, int), f"{event}: uid must be int, got {type(uid)}"
        assert uid in valid_uids, f"{event}: uid {uid} not in valid OCSF set"
        assert isinstance(activity_id, int), (
            f"{event}: activity_id must be int, got {type(activity_id)}"
        )


# ============================================================
# event_to_ocsf
# ============================================================


def test_event_to_ocsf_strategy_ran():
    """strategy_ran → Scheduled Job Activity with candidate count."""
    native = {
        "ts": 1784915693.4,
        "event": "strategy_ran",
        "pensioner_id": "327",
        "strategy": "B1-exact",
        "candidates": 5,
        "state": "OK",
        "classification": "",
    }
    ocsf = event_to_ocsf(native)
    assert ocsf is not None
    assert ocsf["class_uid"] == 1006
    assert ocsf["class_name"] == "Scheduled Job Activity"
    # activity_id: 2=Update for in-progress state changes.
    assert ocsf["activity_id"] == 2
    # OCSF time is ms since epoch (int). 1784915693.4 s → 1784915693400 ms.
    assert ocsf["time"] == 1784915693400
    # The OCSF envelope must have a metadata block + a job block
    # carrying the strategy + pensioner_id.
    assert ocsf["metadata"]["product"]["name"] == "FindAGraveHelper"
    assert ocsf["job"]["name"] == "FaGScraperKS:strategy:B1-exact"
    assert ocsf["job"]["pensioner_id"] == 327
    # The candidate count is preserved (consumers care about it).
    assert ocsf["job"]["candidates"] == 5
    assert ocsf["job"]["state"] == "OK"


def test_event_to_ocsf_work_claimed_create():
    """work_claimed → Scheduled Job Activity (activity_id=1=Create)."""
    native = {
        "ts": 1.0,
        "event": "work_claimed",
        "work_id": "w1",
        "pensioner_id": 42,
        "knowledge_source": "FaGScraperKS",
        "attempt": 1,
    }
    ocsf = event_to_ocsf(native)
    assert ocsf is not None
    assert ocsf["class_uid"] == 1006
    assert ocsf["activity_id"] == 1  # Create
    assert ocsf["job"]["name"] == "w1"
    assert ocsf["job"]["pensioner_id"] == 42


def test_event_to_ocsf_work_completed_complete():
    """work_completed → Scheduled Job Activity (activity_id=3=Complete)."""
    native = {
        "ts": 1.0,
        "event": "work_completed",
        "work_id": "w1",
        "pensioner_id": 42,
        "knowledge_source": "FaGScraperKS",
        "old_state": "leased",
        "new_state": "succeeded",
        "observation_count": 1,
    }
    ocsf = event_to_ocsf(native)
    assert ocsf is not None
    assert ocsf["activity_id"] == 3  # Complete
    assert ocsf["job"]["status"] == "succeeded"


def test_event_to_ocsf_pensioner_start_create():
    """pensioner_start → Scheduled Job Activity (Create)."""
    native = {
        "ts": 1.0,
        "event": "pensioner_start",
        "pensioner_id": "327",
        "name": "Gamble, J.",
    }
    ocsf = event_to_ocsf(native)
    assert ocsf["activity_id"] == 1
    assert ocsf["job"]["name"].startswith("pensioner:327")
    assert ocsf["job"]["pensioner_id"] == 327


def test_event_to_ocsf_pensioner_end_complete():
    """pensioner_end → Scheduled Job Activity (Complete) with status."""
    native = {
        "ts": 1.0,
        "event": "pensioner_end",
        "pensioner_id": "327",
        "status": "auto_accept",
        "total_candidates": 5,
        "best_score": 0.92,
        "elapsed_s": 12.3,
    }
    ocsf = event_to_ocsf(native)
    assert ocsf["activity_id"] == 3
    assert ocsf["job"]["status"] == "auto_accept"
    assert ocsf["job"]["candidates"] == 5


def test_event_to_ocsf_bot_wall_detection_finding():
    """bot_wall_observed → Detection Finding (class 2004)."""
    native = {
        "ts": 1.0,
        "event": "bot_wall_observed",
        "pensioner_id": "327",
        "url": "https://www.findagrave.com/memorial/12345",
    }
    ocsf = event_to_ocsf(native)
    assert ocsf["class_uid"] == 2004
    assert ocsf["class_name"] == "Detection Finding"


def test_event_to_ocsf_cooldown_remediation():
    """cooldown_set → Process Remediation Activity (class 7003)."""
    native = {
        "ts": 1.0,
        "event": "cooldown_set",
        "provider": "findagrave.com",
        "not_before": "2026-07-24T18:00:00Z",
    }
    ocsf = event_to_ocsf(native)
    assert ocsf["class_uid"] == 7003
    assert ocsf["class_name"] == "Process Remediation Activity"


def test_event_to_ocsf_unknown_event_returns_none():
    """Unknown event types (e.g. future additions) translate to None,
    not a malformed OCSF record."""
    assert event_to_ocsf({"ts": 1.0, "event": "future_event_type"}) is None


# ============================================================
# translate_audit_file
# ============================================================


def test_translate_audit_file_emits_ocsf_sidecar(tmp_path: Path):
    """translate_audit_file reads run_audit.jsonl and writes
    run_audit.ocsf.jsonl next to it. One native line in = one
    OCSF line out (when the event has a mapping)."""
    native_path = tmp_path / "run_audit.jsonl"
    events = [
        {
            "ts": 1784915693.4, "event": "strategy_ran",
            "pensioner_id": "327", "strategy": "B1-exact",
            "candidates": 5, "state": "OK",
        },
        {
            "ts": 1784915694.0, "event": "work_claimed",
            "work_id": "w1", "pensioner_id": "327",
            "knowledge_source": "FaGScraperKS", "attempt": 1,
        },
    ]
    native_path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )

    out = translate_audit_file(native_path)

    assert out.exists()
    assert out.name == "run_audit.ocsf.jsonl"
    lines = [
        json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    assert len(lines) == 2
    assert lines[0]["class_uid"] == 1006  # strategy_ran → Scheduled Job
    assert lines[0]["job"]["candidates"] == 5
    assert lines[1]["activity_id"] == 1   # work_claimed → Create


def test_translate_audit_file_skips_unmapped_events(tmp_path: Path):
    """Unknown event types are silently skipped (the sidecar
    contains only mapped events)."""
    native_path = tmp_path / "run_audit.jsonl"
    events = [
        {"ts": 1.0, "event": "strategy_ran", "pensioner_id": "1",
         "strategy": "B1-exact", "candidates": 3},
        {"ts": 1.0, "event": "future_event_xyz"},
        {"ts": 1.0, "event": "pensioner_end", "pensioner_id": "1",
         "status": "auto_accept", "total_candidates": 3},
    ]
    native_path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )

    out = translate_audit_file(native_path)
    lines = [
        json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    # Only 2 of 3 native events are mapped.
    assert len(lines) == 2


def test_sidecar_path_for(tmp_path: Path):
    """sidecar_path_for maps run_audit.jsonl → run_audit.ocsf.jsonl."""
    assert sidecar_path_for(tmp_path / "run_audit.jsonl") == (
        tmp_path / "run_audit.ocsf.jsonl"
    )


# ============================================================
# Real G10 verification
# ============================================================


G10_AUDIT_PATH = Path(
    "data/results/run_2026_07_24_g10_stealth_swap_verification/run_audit.jsonl"
)


@pytest.mark.skipif(
    not G10_AUDIT_PATH.exists(),
    reason="G10 verification run dir not present",
)
def test_g10_translation_produces_ocsf_sidecar(tmp_path: Path):
    """End-to-end: translate the G10 audit log to OCSF and
    verify the sidecar structure. Doesn't pin exact counts
    (the G10 run is real FaG data) but does pin that the
    sidecar exists, has valid OCSF envelopes, and at least
    one of each major class is present."""
    import shutil

    # Copy the G10 audit to a tmp path under tmp_path/audit/.
    src_dir = tmp_path / "g10"
    src_dir.mkdir(parents=True, exist_ok=True)
    native = src_dir / "run_audit.jsonl"
    native.write_text(
        G10_AUDIT_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )

    out = translate_audit_file(native)
    assert out.exists()

    lines = [
        json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    assert len(lines) > 0
    # Every line is a valid OCSF envelope.
    for l in lines:
        assert "class_uid" in l
        assert "class_name" in l
        assert "time" in l
        assert "metadata" in l
        assert l["metadata"]["product"]["name"] == "FindAGraveHelper"

    # Pin that we saw at least one of the three major OCSF classes.
    uids = {l["class_uid"] for l in lines}
    assert 1006 in uids  # Scheduled Job Activity (work + strategies + pensioner + run_summary)
    # The G10 run didn't trigger bot_wall_observed (no 1015 backoff
    # — issue #94 swap verification), so 2004 may or may not be
    # present. Don't pin.