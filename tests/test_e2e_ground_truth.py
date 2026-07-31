"""End-to-end test: bundled ground-truth fixture validation.

The bundled ground-truth fixture at
``tests/fixtures/ground_truth.csv`` is built from
``dixiedata.db`` joined to ``ok_pensioners.json`` on
pension_id. This file validates that the fixture is
well-formed + that the join semantics are correct.

The full live-searcher e2e tests (precision/recall/F1 against
the searcher output) live in
``tests/test_e2e_ground_truth_diag.py`` and are gated by
``@pytest.mark.diag`` so they don't run in the default suite
(the searcher takes 2-3 min per 50 records and depends on a
real Playwright browser).
"""
import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

GT_CSV = Path(__file__).parent / "fixtures" / "ground_truth.csv"


def test_gt_fixture_exists():
    """The bundled ground-truth fixture must be present."""
    assert GT_CSV.exists(), (
        f"{GT_CSV} missing. Run scripts/audit/build_ground_truth_fixture.py"
    )


def test_gt_fixture_has_minimum_rows():
    """At least 50 rows so the diag e2e --limit 50 has data."""
    rows = list(csv.DictReader(open(GT_CSV, encoding="utf-8")))
    assert len(rows) >= 50, f"expected >= 50 GT rows, got {len(rows)}"


def test_gt_fixture_schema():
    """The columns must match the searcher's expected input schema
    (id, application_number, pensioner_name, ...) PLUS the
    ground-truth metadata columns (prefixed with _gt_)."""
    rows = list(csv.DictReader(open(GT_CSV, encoding="utf-8")))
    required = {"id", "application_number", "pensioner_name",
                "_gt_memorial_id", "_gt_memorial_url", "_gt_rank"}
    for r in rows[:5]:
        missing = required - set(r.keys())
        assert not missing, f"row missing columns: {missing}"


def test_gt_memorial_ids_are_numeric():
    """FaG memorial IDs are positive integers."""
    rows = list(csv.DictReader(open(GT_CSV, encoding="utf-8")))
    for r in rows[:20]:
        mid = r["_gt_memorial_id"]
        assert mid.isdigit(), f"non-numeric _gt_memorial_id: {mid!r}"
        assert int(mid) > 0


def test_gt_pensioner_ids_join_to_ok_pensioners():
    """Every GT row's id must exist in ok_pensioners.json so the
    searcher can resolve the pensioner record."""
    import json
    pensioners = json.loads(
        (ROOT / "docs" / "research" / "digitalprairie" / "ok_pensioners.json").read_text(
            encoding="utf-8"
        )
    )
    pensioner_ids = {p.get("id") for p in pensioners}
    rows = list(csv.DictReader(open(GT_CSV, encoding="utf-8")))
    missing = [r["id"] for r in rows if int(r["id"]) not in pensioner_ids]
    assert not missing, (
        f"{len(missing)} GT rows have ids not in ok_pensioners.json "
        f"(first 5: {missing[:5]})"
    )


def test_gt_memorial_urls_match_ids():
    """The /memorial/<id>/ pattern in _gt_memorial_url must
    match _gt_memorial_id."""
    import re
    pat = re.compile(r"/memorial/(\d+)/")
    rows = list(csv.DictReader(open(GT_CSV, encoding="utf-8")))
    for r in rows[:20]:
        m = pat.search(r["_gt_memorial_url"])
        assert m, f"no /memorial/<id>/ in {r['_gt_memorial_url']!r}"
        assert m.group(1) == r["_gt_memorial_id"], (
            f"id mismatch: {m.group(1)} != {r['_gt_memorial_id']}"
        )


# ------------------------------------------------------------
# Smoke: exercise the evaluation helpers (no searcher, no
# external data). Mirrors the original test_e2e_smoke variant
# that ran in the default suite before issue #91.
# ------------------------------------------------------------

from scripts.matching.evaluation import (  # noqa: E402
    ConfusionMatrix,
    compute_confusion_matrix,
    best_threshold,
)


SMOKE_FIXTURE_CSV = (
    Path(__file__).parent / "fixtures" / "ground_truth_smoke.csv"
)


def test_smoke_evaluation_helpers_with_fixture():
    """Bundled 3-row fixture exercises compute_confusion_matrix
    and best_threshold. No live FaG required; the operator
    ground-truth CSV is not needed for this case."""
    rows = list(csv.DictReader(open(SMOKE_FIXTURE_CSV, encoding="utf-8")))
    assert len(rows) == 3
    assert all("memorial_id" in r for r in rows)

    
    pairs = [
        (True, 0.95),   
        (False, 0.30),  
        (True, 0.10),   
    ]
    cm = compute_confusion_matrix(pairs, threshold=0.5)
    assert cm.tp == 1
    assert cm.fp == 0
    assert cm.fn == 1
    assert cm.tn == 1

    result = best_threshold(pairs, metric="f1")
    assert 0.0 <= result.threshold <= 1.0
    assert 0.0 <= result.precision <= 1.0
    assert 0.0 <= result.recall <= 1.0
