"""Tests for scripts/audit/build_ground_truth_fixture.py."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.audit import build_ground_truth_fixture as bgf


def test_bundled_fixture_exists_and_has_rows():
    """The committed fixture must be present with 50+ rows so
    the e2e test (--limit 50) has data to run against."""
    path = Path(bgf.DEFAULT_OUTPUT)
    assert path.exists(), (
        f"{path} missing. Run scripts/audit/build_ground_truth_fixture.py"
    )
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    assert len(rows) >= 50, f"expected >= 50 ground-truth pairs, got {len(rows)}"


def test_bundled_fixture_schema():
    """Each row must have the columns the e2e test reads."""
    path = Path(bgf.DEFAULT_OUTPUT)
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    required = {"id", "application_number", "pensioner_name",
                "_gt_memorial_id", "_gt_memorial_url", "_gt_rank"}
    for r in rows[:5]:
        missing = required - set(r.keys())
        assert not missing, f"row missing columns: {missing}"


def test_bundled_fixture_memorial_ids_parseable():
    """_gt_memorial_id must be a positive integer (FaG memorial IDs)."""
    path = Path(bgf.DEFAULT_OUTPUT)
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    for r in rows[:20]:
        mid = r["_gt_memorial_id"]
        assert mid.isdigit(), f"non-numeric _gt_memorial_id: {mid!r}"
        assert int(mid) > 0


def test_builder_is_idempotent(tmp_path):
    """Re-running the builder must produce the same number of rows
    (no duplicate-row drift) and the same shape."""
    out = tmp_path / "gt.csv"
    rows1 = bgf.build(bgf.DEFAULT_DB, bgf.DEFAULT_PENSIONERS)
    assert len(rows1) > 0
    bgf.main(["--output", str(out)])
    rows2 = list(csv.DictReader(open(out, encoding="utf-8")))
    assert len(rows2) == len(rows1)
    assert list(rows1[0].keys()) == list(rows2[0].keys())
