"""scripts.fag.state_io: state.jsonl read/write helpers for the FaG runner.

Extracted from scripts.fag.search.py (T008). These functions manage
the on-disk state of the batch run (which pensioner ids are done,
which were skipped, appending new results).
"""
import json
import logging
from pathlib import Path

log = logging.getLogger("fag.state_io")


def load_processed_ids(state_path: Path) -> set[int]:
    if not state_path.exists():
        return set()
    seen = set()
    with state_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                pid = rec.get("pensioner_id")
                if pid is not None:
                    seen.add(pid)
            except json.JSONDecodeError:
                pass
    return seen


def load_skipped_ids(skipped_path: Path) -> set[int]:
    if not skipped_path.exists():
        return set()
    seen = set()
    with skipped_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                pid = rec.get("pensioner_id")
                if pid is not None:
                    seen.add(pid)
            except json.JSONDecodeError:
                pass
    return seen


def append_state(state_path: Path, record: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with state_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def write_skipped(path: Path, skipped: list[dict]) -> None:
    """Write skipped pensioners to a JSONL sidecar file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in skipped:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ============================================================
# Input loading
# ============================================================
