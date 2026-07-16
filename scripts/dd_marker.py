"""Post-run DD (DixieData) marker.

For each pensioner in state.jsonl, check whether the local
DixieData database already has a record for them. Surface
the answer as `dd_in_local`, `dd_memorial_id`, etc.

DixieData is a human-verified local database of CW veterans.
We treat anything that's IN DixieData as already-known; new
finds from this run are things NOT in DD.

Matching strategy (in priority order):
  1. Application number (e.g. "A4") — exact match
  2. (last_name, first_name) normalized to lowercase
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DdIndex:
    """Index of DixieData records, keyed two ways."""
    by_app_number: dict[str, dict] = field(default_factory=dict)
    by_name: dict[tuple[str, str], dict] = field(default_factory=dict)

    def __len__(self):
        return len(self.by_app_number)


def _normalize_name_for_match(s: str) -> str:
    """Normalize a name for fuzzy matching.

    Lowercase + strip non-alphanumeric. Handles 'R.W.' -> 'rw'.
    """
    return re.sub(r"[^a-z]", "", (s or "").lower())


def load_dd_index(csv_path: Path) -> DdIndex:
    """Load a DixieData export CSV into an index.

    Accepts common column-name variants:
      - application_number / app_number / app
      - memorial_id / memorial / flag_id
      - slug / memorial_slug
      - first_name / firstname
      - last_name / lastname / surname
    """
    if not csv_path.exists():
        return DdIndex()

    by_app: dict[str, dict] = {}
    by_name: dict[tuple[str, str], dict] = {}

    # Build header lookup that's case-insensitive
    app_keys = {"application_number", "app_number", "app", "appl"}
    id_keys = {"memorial_id", "memorial", "flag_id"}
    slug_keys = {"slug", "memorial_slug"}
    first_keys = {"first_name", "firstname", "fname"}
    last_keys = {"last_name", "lastname", "surname", "lname"}

    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Build a record with the relevant fields regardless of app
            rec = {
                "application_number": _get_first(row, app_keys),
                "memorial_id": _get_first(row, id_keys),
                "slug": _get_first(row, slug_keys),
                "first_name": _get_first(row, first_keys),
                "last_name": _get_first(row, last_keys),
            }
            app = rec["application_number"]
            if app:
                by_app[app] = rec
            # Always try to add to name index
            ln = _normalize_name_for_match(rec["last_name"])
            fn = _normalize_name_for_match(rec["first_name"])
            if ln and fn:
                by_name[(ln, fn)] = rec
    return DdIndex(by_app_number=by_app, by_name=by_name)


def _get_first(row: dict, keys: tuple[str, ...]) -> str:
    """First non-empty value for any of the given keys."""
    for k in keys:
        if k in row and row[k]:
            return str(row[k]).strip()
    return ""


def matched_by_app_number(rec: dict, dd_index: DdIndex) -> bool:
    """True if rec.pensioner_app_number matches a DD record."""
    app = (rec.get("pensioner_app_number") or "").strip()
    return bool(app) and app in dd_index.by_app_number


def matched_by_name(rec: dict, dd_index: DdIndex) -> bool:
    """True if rec's last + first name matches a DD record (normalized)."""
    ln = _normalize_name_for_match(rec.get("pensioner_last", ""))
    fn = _normalize_name_for_match(rec.get("pensioner_first", ""))
    if not ln or not fn:
        return False
    return (ln, fn) in dd_index.by_name


def mark_record(rec: dict, dd_index: DdIndex) -> dict:
    """Add DD-marking fields to a record. Returns the record (mutated)."""
    if matched_by_app_number(rec, dd_index):
        dd = dd_index.by_app_number[rec["pensioner_app_number"].strip()]
        rec["dd_in_local"] = True
        rec["dd_memorial_id"] = dd.get("memorial_id") or None
        rec["dd_slug"] = dd.get("slug") or None
        rec["dd_match_method"] = "app_number"
        return rec
    if matched_by_name(rec, dd_index):
        ln = _normalize_name_for_match(rec.get("pensioner_last", ""))
        fn = _normalize_name_for_match(rec.get("pensioner_first", ""))
        dd = dd_index.by_name.get((ln, fn), {})
        rec["dd_in_local"] = True
        rec["dd_memorial_id"] = dd.get("memorial_id") or None
        rec["dd_slug"] = dd.get("slug") or None
        rec["dd_match_method"] = "name"
        return rec
    rec["dd_in_local"] = False
    rec["dd_memorial_id"] = None
    rec["dd_slug"] = None
    rec["dd_match_method"] = None
    return rec


def mark_state_file(
    state_path: Path,
    dd_csv_path: Path,
    out_path: Path,
) -> tuple[int, int]:
    """Mark every record in state_path using DD CSV.

    Returns (n_marked, n_in_dd).
    """
    dd_index = load_dd_index(dd_csv_path)
    n_marked = 0
    n_in_dd = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open(encoding="utf-8") as fin, \
         out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            mark_record(rec, dd_index)
            if rec.get("dd_in_local"):
                n_in_dd += 1
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_marked += 1
    return n_marked, n_in_dd