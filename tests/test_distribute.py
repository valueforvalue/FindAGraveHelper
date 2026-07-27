"""Tests for scripts/distribute.py.

Pins the distribute-pack contract:
  - Each group becomes one .zip at out/<group_name>.zip
  - Each zip contains <runname>/view.html + <runname>/results.jsonl
  - Original run folders are NOT modified
  - Missing required files cause a clear error
  - Skip flags can drop either file type
  - Group name is slug-validated (matches batch_config rules)
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys_path = str(ROOT)


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def runs(tmp_path):
    """Create two fake run folders with view.html + results.jsonl."""
    runs_root = tmp_path / "runs"
    out_dir = tmp_path / "dist"
    runs_root.mkdir()
    for name in ("run-a", "run-b"):
        d = runs_root / name
        d.mkdir()
        (d / "view.html").write_text(f"<html>{name}</html>", encoding="utf-8")
        (d / "results.jsonl").write_text(
            json.dumps({"pensioner_id": 1, "name": name}) + "\n",
            encoding="utf-8",
        )
    return runs_root, out_dir


def _make_dist(**kwargs):
    """Import-and-call wrapper for the CLI."""
    import sys
    sys.path.insert(0, sys_path)
    from scripts import distribute
    return distribute.main(["--root", str(kwargs["runs_root"]),
                            "--out", str(kwargs["out_dir"]),
                            "--group", kwargs["group"],
                            *kwargs.get("extra_args", [])])


# ============================================================
# Basic group → zip
# ============================================================
def test_builds_one_zip_per_group(runs):
    runs_root, out_dir = runs
    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="H=run-a,run-b",
    )
    assert rc == 0
    zips = sorted(out_dir.glob("*.zip"))
    assert [p.name for p in zips] == ["H.zip"]


def test_zip_contains_per_run_subdirs_with_required_files(runs):
    runs_root, out_dir = runs
    _make_dist(runs_root=runs_root, out_dir=out_dir, group="H=run-a,run-b")
    with zipfile.ZipFile(out_dir / "H.zip") as zf:
        names = sorted(zf.namelist())
    assert names == [
        "run-a/results.jsonl",
        "run-a/view.html",
        "run-b/results.jsonl",
        "run-b/view.html",
    ]


def test_zip_content_matches_source(runs):
    runs_root, out_dir = runs
    _make_dist(runs_root=runs_root, out_dir=out_dir, group="H=run-a")
    with zipfile.ZipFile(out_dir / "H.zip") as zf:
        html = zf.read("run-a/view.html").decode("utf-8")
        jsonl = zf.read("run-a/results.jsonl").decode("utf-8").strip()
    assert "<html>run-a</html>" == html
    rec = json.loads(jsonl)
    assert rec["pensioner_id"] == 1
    assert rec["name"] == "run-a"


def test_original_run_folders_unchanged(runs):
    runs_root, out_dir = runs
    before = {p.name: p.read_bytes() for p in runs_root.rglob("*") if p.is_file()}
    _make_dist(runs_root=runs_root, out_dir=out_dir, group="H=run-a,run-b")
    after = {p.name: p.read_bytes() for p in runs_root.rglob("*") if p.is_file()}
    assert before == after, "distribute must not modify source run folders"


def test_multiple_groups_produce_multiple_zips(runs):
    runs_root, out_dir = runs
    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="",
        extra_args=["--group", "H=run-a", "--group", "G=run-b"],
    )
    assert rc == 0
    zips = sorted(p.name for p in out_dir.glob("*.zip"))
    assert zips == ["G.zip", "H.zip"]


def test_group_name_is_slug_validated(runs):
    runs_root, out_dir = runs
    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="bad/name=run-a",  # path separator — invalid
    )
    assert rc != 0
    assert not list(out_dir.glob("*.zip"))


def test_missing_results_jsonl_reports_error(tmp_path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "bad").mkdir()
    (runs_root / "bad" / "view.html").write_text("x", encoding="utf-8")
    # no results.jsonl
    out_dir = tmp_path / "dist"

    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="H=bad",
    )
    assert rc != 0
    assert not list(out_dir.glob("*.zip"))


def test_missing_view_html_reports_error(tmp_path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "bad").mkdir()
    (runs_root / "bad" / "results.jsonl").write_text("x", encoding="utf-8")
    # no view.html
    out_dir = tmp_path / "dist"

    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="H=bad",
    )
    assert rc != 0
    assert not list(out_dir.glob("*.zip"))


def test_unknown_run_name_reports_error(runs):
    runs_root, out_dir = runs
    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="H=run-a,does-not-exist",
    )
    assert rc != 0
    assert not list(out_dir.glob("*.zip"))


def test_skip_view_html_drops_html_from_zip(runs):
    runs_root, out_dir = runs
    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="H=run-a,run-b",
        extra_args=["--skip-view-html"],
    )
    assert rc == 0
    with zipfile.ZipFile(out_dir / "H.zip") as zf:
        names = sorted(zf.namelist())
    assert names == ["run-a/results.jsonl", "run-b/results.jsonl"]


def test_skip_results_drops_jsonl_from_zip(runs):
    runs_root, out_dir = runs
    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="H=run-a",
        extra_args=["--skip-results"],
    )
    assert rc == 0
    with zipfile.ZipFile(out_dir / "H.zip") as zf:
        names = sorted(zf.namelist())
    assert names == ["run-a/view.html"]


def test_dry_run_does_not_create_zip(runs):
    runs_root, out_dir = runs
    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="H=run-a,run-b",
        extra_args=["--dry-run"],
    )
    assert rc == 0
    assert not list(out_dir.glob("*.zip"))


def test_groups_file_alternative_to_repeated_flag(runs, tmp_path):
    """--groups-file path/to/config.txt with one group per line."""
    runs_root, out_dir = runs
    gf = tmp_path / "groups.txt"
    gf.write_text(
        "H=run-a,run-b\n"
        "G=run-a\n",
        encoding="utf-8",
    )
    rc = _make_dist(
        runs_root=runs_root, out_dir=out_dir,
        group="",  # ignored
        extra_args=["--groups-file", str(gf)],
    )
    assert rc == 0
    zips = sorted(p.name for p in out_dir.glob("*.zip"))
    assert zips == ["G.zip", "H.zip"]


def test_zip_top_level_lists_runs_only(runs):
    """v2.html expects results.jsonl next to it. Verify the layout."""
    runs_root, out_dir = runs
    _make_dist(runs_root=runs_root, out_dir=out_dir, group="H=run-a,run-b")
    with zipfile.ZipFile(out_dir / "H.zip") as zf:
        # Both files must live in the same subdir so the relative
        # fetch('results.jsonl') from view.html works after extraction.
        for name in zf.namelist():
            assert name.startswith("run-a/") or name.startswith("run-b/")