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
import hashlib
import json
import os
import re as _re
import time
from datetime import datetime as _datetime, timezone as _timezone
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
    # Issue #22: routed through JsonlStateRepository. L3 (flush + fsync)
    # is now honoured; the previous implementation only flushed.
    from scripts.state.repository import JsonlStateRepository
    JsonlStateRepository(state_path).append(record)


# ============================================================
# Issue #21: state-file snapshot checkpoints for --rollback-to
#
# These are full copies of state.jsonl taken periodically. The
# operator can rollback state.jsonl to any snapshot via the CLI.
# Naming: <state>.checkpoint-<label>.jsonl, e.g.
#   state.jsonl  ->  state.checkpoint-before-v2.jsonl
# ============================================================

import re as _re
from datetime import datetime as _datetime, timezone as _timezone


CHECKPOINT_SUFFIX = ".checkpoint"
CHECKPOINT_PREFIX = CHECKPOINT_SUFFIX  # alias for tests


def _state_to_snapshot_path(state_path: Path, label: str) -> Path:
    """Compute the snapshot path for a given state.jsonl and label.

    Naming: state.checkpoint-<label>.jsonl
    Label must be filesystem-safe (no path separators, no '..').
    """
    if not label or "/" in label or "\\" in label or ".." in label:
        raise ValueError(
            f"unsafe checkpoint label: {label!r} "
            "(must be non-empty, no '/' or '\\' or '..')"
        )
    name = f"{state_path.stem}{CHECKPOINT_SUFFIX}-{label}{state_path.suffix}"
    return state_path.parent / name


def _fsync_file_and_dir(file_path: Path) -> None:
    """fsync the file and its parent directory for durability.

    Uses os.open with O_RDWR for a sync-able fd. Directory fsync
    is skipped on Windows (not supported).
    """
    fd = os.open(str(file_path), os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name != "nt":
        dir_fd = os.open(str(file_path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def write_checkpoint_snapshot(state_path: Path, label: str | None = None) -> Path:
    """Copy state.jsonl to a snapshot file. Atomic + hash-verified.

    Writes to .tmp, computes SHA-256, fsyncs temp + directory,
    os.replace to final name. Creates a sibling <name>.meta.json
    with created_at, record_count, sha256, policy_version.

    If label is None, an auto-label is generated from the current
    record count + ISO timestamp.
    """
    state_path = Path(state_path)
    if not state_path.exists():
        raise FileNotFoundError(f"state file does not exist: {state_path}")

    if label is None:
        from scripts.state.repository import JsonlStateRepository

        n = sum(1 for _ in JsonlStateRepository(state_path).iter_all())
        stamp = _datetime.now(_timezone.utc).strftime("%Y%m%dT%H%M%S")
        label = f"auto-{n}records-{stamp}"

    snap_path = _state_to_snapshot_path(state_path, label)
    tmp_path = snap_path.with_suffix(snap_path.suffix + ".tmp")

    data = state_path.read_bytes()

    # Write to temp, fsync, then atomic replace
    tmp_path.write_bytes(data)
    _fsync_file_and_dir(tmp_path)

    sha256 = hashlib.sha256(data).hexdigest()

    # Write sibling meta file
    meta_path = snap_path.with_suffix(snap_path.suffix + ".meta.json")
    meta_tmp = meta_path.with_suffix(meta_path.suffix + ".tmp")
    record_count = data.count(b"\n")
    meta = {
        "created_at": _datetime.now(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "record_count": record_count,
        "sha256": sha256,
        "policy_version": "1",
        "label": label,
    }
    meta_tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _fsync_file_and_dir(meta_tmp)

    os.replace(tmp_path, snap_path)
    os.replace(meta_tmp, meta_path)
    return snap_path


def list_checkpoints(state_path: Path) -> list[Path]:
    """List all checkpoint snapshot files for the given state file.

    Sorts by mtime (oldest first) so 'latest' = last element.
    """
    state_path = Path(state_path)
    if not state_path.exists():
        return []
    pattern = _re.compile(
        _re.escape(f"{state_path.stem}{CHECKPOINT_SUFFIX}-")
        + r"[^\/\\]+"
        + _re.escape(state_path.suffix)
    )
    snapshots = []
    for p in state_path.parent.iterdir():
        if p.is_file() and pattern.fullmatch(p.name):
            snapshots.append(p)
    snapshots.sort(key=lambda p: p.stat().st_mtime)
    return snapshots


def rollback_to_checkpoint(state_path: Path, label: str) -> None:
    """Restore state_path from a named checkpoint. Atomic.

    Special label 'latest' rolls back to the most recent snapshot.
    Raises FileNotFoundError if the label doesn't exist.
    """
    state_path = Path(state_path)

    if label == "latest":
        snapshots = list_checkpoints(state_path)
        if not snapshots:
            raise FileNotFoundError(
                f"no checkpoints found for {state_path}"
            )
        snap_path = snapshots[-1]
    else:
        snap_path = _state_to_snapshot_path(state_path, label)
        if not snap_path.exists():
            raise FileNotFoundError(
                f"checkpoint {label!r} not found at {snap_path}"
            )

    # Atomic restore: copy snapshot data (preserves snapshot file)
    data = snap_path.read_bytes()
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    _fsync_file_and_dir(tmp_path)
    os.replace(tmp_path, state_path)