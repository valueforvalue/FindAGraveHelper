"""State file integrity check.

Before/after each run, we want to verify:
  - All expected pensioner IDs are present (no missing)
  - No duplicate IDs
  - Each record has the expected fields
  - FaG backlinks are well-formed URLs

This is the foundation of "bulletproof" — we detect data loss,
corruption, or schema drift before it bites us.

Usage:
  from scripts.state.state_check import check_state_file
  result = check_state_file(state_path, expected_ids)
  if not result.is_clean():
      print(result.summary())
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


_FAG_URL_RE = re.compile(
    r"^https?://(?:www\.)?findagrave\.com/memorial/\d+",
    re.I,
)


@dataclass
class StateCheckResult:
    """Result of an integrity scan on a state file."""
    total_records: int = 0
    missing_ids: set[int] = field(default_factory=set)
    duplicate_ids: set[int] = field(default_factory=set)
    issues: list[str] = field(default_factory=list)
    bad_backlinks: list[str] = field(default_factory=list)
    pensioner_ids_present: set[int] = field(default_factory=set)

    def is_clean(self) -> bool:
        """True when there are no missing/duplicates/issues."""
        return not (self.missing_ids or self.duplicate_ids or self.issues)

    def to_dict(self) -> dict:
        return {
            "total_records": self.total_records,
            "missing_ids": sorted(self.missing_ids),
            "duplicate_ids": sorted(self.duplicate_ids),
            "issues": self.issues,
            "bad_backlinks": self.bad_backlinks,
            "is_clean": self.is_clean(),
        }

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"State check: {self.total_records} records",
            f"  Missing IDs: {len(self.missing_ids)}",
            f"  Duplicate IDs: {len(self.duplicate_ids)}",
            f"  Per-record issues: {len(self.issues)}",
            f"  Bad backlinks: {len(self.bad_backlinks)}",
            f"  Clean: {self.is_clean()}",
        ]
        if self.missing_ids and len(self.missing_ids) <= 30:
            lines.append(f"  Missing: {sorted(self.missing_ids)}")
        if self.duplicate_ids:
            lines.append(f"  Duplicates: {sorted(self.duplicate_ids)}")
        if self.issues[:5]:
            lines.append("  First issues:")
            for issue in self.issues[:5]:
                lines.append(f"    {issue}")
        return "\n".join(lines)


def expected_pensioner_ids(pensioners: list[dict]) -> set[int]:
    """Extract pensioner_id set from a list of pensioner dicts."""
    return {p["id"] for p in pensioners if p.get("id") is not None}


def record_issues(rec: dict) -> list[str]:
    """Return a list of issue strings for one record."""
    issues = []
    if "pensioner_id" not in rec:
        issues.append("record is missing pensioner_id")
    pid = rec.get("pensioner_id")
    # CGR records: each cgr_id should be int-castable
    for cgr in rec.get("cgr_records", []) or []:
        cgr_id = cgr.get("cgr_id")
        if cgr_id is None:
            continue
        try:
            int(cgr_id)
        except (TypeError, ValueError):
            issues.append(f"pensioner {pid}: cgr_id={cgr_id!r} is not int-castable")
    # FaG records: each backlink should be a valid URL
    for fag in rec.get("fag_records", []) or []:
        backlink = fag.get("backlink", "")
        if backlink and not _FAG_URL_RE.match(backlink):
            issues.append(
                f"pensioner {pid}: bad faG backlink {backlink!r} for memorial {fag.get('memorial_id', '?')}"
            )
    return issues


def check_state_file(state_path: Path, expected_ids: set[int]) -> StateCheckResult:
    """Scan a state file for integrity issues."""
    result = StateCheckResult()
    if not state_path.exists():
        result.issues.append(f"state file {state_path} does not exist")
        return result
    seen: dict[int, int] = {}
    with state_path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                result.issues.append(f"line {lineno}: JSON decode error: {e}")
                continue
            result.total_records += 1
            pid = rec.get("pensioner_id")
            if pid is None:
                issues = record_issues(rec)
                result.issues.extend(issues)
                continue
            # Track duplicates
            if pid in seen:
                result.duplicate_ids.add(pid)
            seen[pid] = seen.get(pid, 0) + 1
            result.pensioner_ids_present.add(pid)
            # Per-record issues
            issues = record_issues(rec)
            result.issues.extend(issues)
            # Track bad backlinks separately for the report
            for fag in rec.get("fag_records", []) or []:
                backlink = fag.get("backlink", "")
                if backlink and not _FAG_URL_RE.match(backlink):
                    result.bad_backlinks.append(backlink)

    # Missing IDs
    result.missing_ids = expected_ids - result.pensioner_ids_present
    return result


# Import json lazily so this module is cheap to import for CLI inspection
import json