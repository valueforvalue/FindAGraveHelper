"""Checkpoint + failure recording for the search_fag harness.

The main run loop in scripts/search_fag.py can crash mid-run
(Playwright dies, network error, captcha storm). This module
provides two helpers:

  - write_checkpoint / read_checkpoint / is_resumable: a small
    sidecar JSON file with the last_processed_id so a re-run
    can verify resume.
  - record_failure: writes an "error" JSONL line to the state
    file when a single pensioner blows up, so the run continues
    rather than aborting.

These are unit-tested in tests/test_checkpoint.py.
"""
import json
import time
from pathlib import Path
from typing import Optional


def write_checkpoint(
    path: Path,
    last_processed_id: int,
    last_strategy: str,
    pensioner_name: str = "",
    run_id: str = "",
    input_hash: str = "",
    state_file: str = "",
) -> None:
    """Write a JSON checkpoint file.

    Atomic-ish: write to .tmp then rename, so a crashed write
    doesn't leave a half-written checkpoint.
    """
    payload = {
        "last_processed_id": last_processed_id,
        "last_strategy": last_strategy,
        "pensioner_name": pensioner_name,
        "run_id": run_id,
        "input_hash": input_hash,
        "state_file": state_file,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_checkpoint(path: Path) -> Optional[dict]:
    """Read a checkpoint file. Returns None if missing or corrupt."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def is_resumable(path: Path) -> bool:
    """True if a valid checkpoint exists at `path`."""
    return read_checkpoint(path) is not None


def record_failure(
    state_path: Path,
    pensioner_id: int,
    pensioner_name: str,
    error: str,
    extra: Optional[dict] = None,
) -> None:
    """Append an 'error' status line to the state JSONL file.

    Called when a single pensioner blows up but the run should
    continue. The record includes the error message so a human
    can investigate later.
    """
    record = {
        "pensioner_id": pensioner_id,
        "pensioner_name": pensioner_name,
        "status": "error",
        "error": error,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if extra:
        record.update(extra)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with state_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()