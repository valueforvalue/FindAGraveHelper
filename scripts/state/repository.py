"""StateRepository protocol + JsonlStateRepository implementation.

Issue #22. Owns the state.jsonl wire format invariants:

  - L3 (CONTEXT.md): every per-pensioner record flushes + fsyncs
    BEFORE the next pensioner starts.
  - L4 (CONTEXT.md): stable JSON key order in state.jsonl.
  - L5 (CONTEXT.md): one JSON object per line (newline-delimited),
    NOT a JSON array.

Business logic in pipeline/ and matching/ should depend on this
Protocol, not on json.dumps + Path.open() directly.

Public API:
  - StateRepository (Protocol)
  - JsonlStateRepository (implementation)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Iterable, Iterator, Protocol

from scripts.state.state_check import StateCheckResult, check_state_file


class InMemoryStateRepository:
    """In-memory StateRepository for tests + dry-run.

    Same Protocol surface as JsonlStateRepository but no disk I/O.
    Use in tests where you want to assert on what was appended
    without touching the filesystem, or in `--dry-run` mode where
    the operator wants a diff without writing a file.

    Note: `check()` returns a StateCheckResult built from the in-memory
    records. For tests that want to exercise the JSONL path, use
    JsonlStateRepository with `tmp_path`.
    """

    def __init__(self, initial: Iterable[dict] | None = None):
        self._records: list[dict] = list(initial) if initial else []

    @property
    def records(self) -> list[dict]:
        """Read-only view of all records (for assertions)."""
        return list(self._records)

    def append(self, record: dict) -> None:
        self._records.append(dict(record))

    def iter_all(self) -> Iterator[dict]:
        return iter(self._records)

    def get(self, pensioner_id: int) -> dict | None:
        for rec in self._records:
            if rec.get("pensioner_id") == pensioner_id:
                return rec
        return None

    def update(
        self,
        pensioner_id: int,
        mutate: Callable[[dict], dict],
    ) -> bool:
        for i, rec in enumerate(self._records):
            if rec.get("pensioner_id") == pensioner_id:
                self._records[i] = mutate(dict(rec))
                return True
        return False

    def replace_all(
        self,
        records: Iterable[dict],
        *,
        atomic: bool = True,
    ) -> None:
        # atomic is a no-op for in-memory; documented for Protocol
        # compatibility with JsonlStateRepository.
        del atomic  # unused
        self._records = [dict(r) for r in records]

    def check(self, expected_ids: set[int]) -> StateCheckResult:
        """Build a StateCheckResult from in-memory records."""
        result = StateCheckResult()
        result.total_records = len(self._records)
        seen: dict[int, int] = {}
        for rec in self._records:
            pid = rec.get("pensioner_id")
            if pid is None:
                continue
            if pid in seen:
                result.duplicate_ids.add(pid)
            seen[pid] = seen.get(pid, 0) + 1
            result.pensioner_ids_present.add(pid)
        result.missing_ids = expected_ids - result.pensioner_ids_present
        return result


class StateRepository(Protocol):
    """The boundary between business logic and the state.jsonl wire format.

    Implementations own:
      - JSON serialisation (key order, unicode handling)
      - Flush + fsync discipline (L3)
      - Newline-delimited format (L5)
      - Atomic write semantics for in-place rewrites

    Business logic calls these methods. It does NOT call
    json.dumps / Path.open() directly.
    """

    def append(self, record: dict) -> None:
        """Append one record. L3: flush + fsync before return."""
        ...

    def iter_all(self) -> Iterator[dict]:
        """Yield every record, in file order. Skip blank lines."""
        ...

    def get(self, pensioner_id: int) -> dict | None:
        """First record matching pensioner_id, or None."""
        ...

    def update(
        self,
        pensioner_id: int,
        mutate: Callable[[dict], dict],
    ) -> bool:
        """In-place mutation of the matching record.

        Atomic via .tmp + rename. Returns True if found, False otherwise.
        """
        ...

    def replace_all(
        self,
        records: Iterable[dict],
        *,
        atomic: bool = True,
    ) -> None:
        """Replace every record in the file. Atomic by default."""
        ...

    def check(self, expected_ids: set[int]) -> StateCheckResult:
        """Integrity scan. Wraps state_check.check_state_file()."""
        ...


class JsonlStateRepository:
    """JSONL-backed StateRepository. The default implementation.

    The path passed in is the file that holds the per-pensioner
    records, one JSON object per line (L5).
    """

    def __init__(self, path: Path):
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    # ============================================================
    # append
    # ============================================================

    def append(self, record: dict) -> None:
        """Append one record. Flush + fsync before return (L3)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ============================================================
    # iter_all
    # ============================================================

    def iter_all(self) -> Iterator[dict]:
        """Yield every record, in file order. Skip blank lines."""
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Mirror the behaviour of scripts.state.state_check:
                    # tolerate corrupt lines so one bad row doesn't
                    # brick the whole reader.
                    continue

    # ============================================================
    # get
    # ============================================================

    def get(self, pensioner_id: int) -> dict | None:
        """First record matching pensioner_id, or None."""
        for rec in self.iter_all():
            if rec.get("pensioner_id") == pensioner_id:
                return rec
        return None

    # ============================================================
    # update
    # ============================================================

    def update(
        self,
        pensioner_id: int,
        mutate: Callable[[dict], dict],
    ) -> bool:
        """In-place mutation of the matching record.

        Reads all, mutates the first match, rewrites the whole file
        atomically via .tmp + rename. Returns True if found.
        """
        records = list(self.iter_all())
        found = False
        for i, rec in enumerate(records):
            if rec.get("pensioner_id") == pensioner_id:
                records[i] = mutate(dict(rec))  # copy to avoid aliasing
                found = True
                break
        if not found:
            return False
        self._atomic_write(records)
        return True

    # ============================================================
    # replace_all
    # ============================================================

    def replace_all(
        self,
        records: Iterable[dict],
        *,
        atomic: bool = True,
    ) -> None:
        """Replace every record in the file. Atomic by default."""
        records_list = list(records)
        if atomic:
            self._atomic_write(records_list)
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as f:
                for rec in records_list:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ============================================================
    # check
    # ============================================================

    def check(self, expected_ids: set[int]) -> StateCheckResult:
        """Integrity scan. Wraps state_check.check_state_file()."""
        return check_state_file(self._path, expected_ids)

    # ============================================================
    # Internal helpers
    # ============================================================

    def _atomic_write(self, records: list[dict]) -> None:
        """Write records via .tmp + rename. Survives mid-write crash."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        # Atomic rename — POSIX guarantees readers see either old or new.
        # On Windows, os.replace() handles the cross-filesystem case.
        os.replace(tmp_path, self._path)