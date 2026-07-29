"""Tests for scripts/ingest/distribute_pension_viewer.py.

Pins the by-letter slicer contract:
  - --by-letter emits pension-viewer-bundle.{LETTER}.zip per letter
  - Each letter-zip contains that letter's .html/.json + matching jpgs
  - Each letter-zip also ships shared metadata + index.html/all.json
    so it's standalone (no need to download the index zip to view)
  - pension-viewer-bundle.index.zip contains the full viewer (every
    letter page) + metadata but NO images
  - --letters SUBSET restricts output to just those letters
  - --dry-run never writes anything
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# Load the script under test as a module so we don't need a
# scripts/ingest/__init__.py.
SCRIPT = ROOT / "scripts" / "ingest" / "distribute_pension_viewer.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "distribute_pension_viewer", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["distribute_pension_viewer"] = mod
    spec.loader.exec_module(mod)
    return mod


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def corpus(tmp_path):
    """Build a tiny-but-faithful corpus:

    data/cards/img/{pcid}__{page}.jpg          (one or two files per pcid)
    data/cards/viewer/A.html, A.json, B.html, B.json, _.{html,json}
    data/cards/viewer/index.html
    data/cards/viewer/all.json                 (master pcid->letter)
    data/cards/enrichment_report.json
    docs/research/digitalprairie/ok_pensioners.json
    docs/research/digitalprairie/ok_pensioners.with_death_dates.json
    """
    img = tmp_path / "data" / "cards" / "img"
    img.mkdir(parents=True)
    # 2 pcids for letter A (each one card), 2 pcids for letter B,
    # plus 1 pcid with no letter record (the '?' bucket).
    files = {
        101: ("__1010.jpg",),       # pcid 101, letter A
        102: ("__1020.jpg",),       # pcid 102, letter A (two-sided)
        102: ("__1021.jpg",),
        201: ("__2010.jpg",),       # pcid 201, letter B
        202: ("__2020.jpg",),       # pcid 202, letter B (two-sided)
        202: ("__2021.jpg",),
        999: ("__9990.jpg",),       # not in all.json (no letter)
    }
    # Use a list to allow duplicates of the same pcid across sides
    files = {
        101: [("101__1010.jpg", b"A-PNG")],
        102: [("102__1020.jpg", b"A-PNG-FRONT"),
              ("102__1021.jpg", b"A-PNG-BACK")],
        201: [("201__2010.jpg", b"B-PNG")],
        202: [("202__2020.jpg", b"B-PNG-FRONT"),
              ("202__2021.jpg", b"B-PNG-BACK")],
        999: [("999__9990.jpg", b"ORPHAN")],
    }
    pcids_by_letter = {"A": [101, 102], "B": [201, 202]}
    for letter, pcids in pcids_by_letter.items():
        for pcid in pcids:
            for name, payload in files[pcid]:
                (img / name).write_bytes(payload)
    # Also write the orphan
    for name, payload in files[999]:
        (img / name).write_bytes(payload)

    # viewer/A.html, A.json, B.html, B.json
    v = tmp_path / "data" / "cards" / "viewer"
    v.mkdir(parents=True)
    for letter in ("A", "B", "_"):
        (v / f"{letter}.html").write_text(
            f"<html>{letter}</html>", encoding="utf-8")
        (v / f"{letter}.json").write_text(
            json.dumps({"letter": letter, "records": []}),
            encoding="utf-8")
    (v / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")

    # all.json — master pcid -> letter map
    by_pcid = {}
    for letter, pcids in pcids_by_letter.items():
        for pcid in pcids:
            by_pcid[str(pcid)] = {
                "letter": letter,
                "name_raw": f"Test {letter}-{pcid}",
            }
    (v / "all.json").write_text(
        json.dumps({"by_pensioncard_id": by_pcid,
                    "letters": ["A", "B"],
                    "total_pensioners": 4}),
        encoding="utf-8")

    # metadata
    (tmp_path / "data" / "cards" / "enrichment_report.json").write_text(
        '{"changed": []}', encoding="utf-8")
    (tmp_path / "data" / "cards" / "red_ocr_results.json").write_text(
        '{}', encoding="utf-8")
    (tmp_path / "data" / "cards" / "red_ocr_summary.json").write_text(
        '{}', encoding="utf-8")

    # source-of-truth JSONs
    dp = tmp_path / "docs" / "research" / "digitalprairie"
    dp.mkdir(parents=True)
    (dp / "ok_pensioners.json").write_text("[]", encoding="utf-8")
    (dp / "ok_pensioners.with_death_dates.json").write_text(
        "[]", encoding="utf-8")

    out_dir = tmp_path / "dist"
    return tmp_path, out_dir, files, pcids_by_letter


# ============================================================
# Helpers
# ============================================================

def _run(src_root, out_dir, *extra):
    """Invoke main() with the script's module-ROOT monkey-patched to
    point at src_root, so the test corpus is read instead of the
    real repo."""
    mod = _load_module()
    monkey = sys.modules["distribute_pension_viewer"]
    monkey.ROOT = Path(src_root)
    argv = [
        "--out", str(out_dir / "bundle.zip"),
        *extra,
    ]
    return mod.main(argv)


# ============================================================
# pytest fixture for the corpus already supplies `corpus` arg
# ============================================================

@pytest.fixture
def corpus_paths(corpus):
    """Alias matching the way earlier tests consume the fixture tuple."""
    src_root, out_dir, files, pcids_by_letter = corpus
    return {
        "src_root": src_root,
        "out_dir": out_dir,
        "files": files,
        "pcids_by_letter": pcids_by_letter,
    }


def test_load_module():
    mod = _load_module()
    assert hasattr(mod, "main")
    assert hasattr(mod, "run_by_letter")
    assert hasattr(mod, "collect_files_for_letter")
    assert hasattr(mod, "load_pcid_to_letter")


def test_load_pcid_to_letter_reads_all_json(corpus_paths):
    src_root = corpus_paths["src_root"]
    mod = _load_module()
    import logging
    log = logging.getLogger("test")
    m = mod.load_pcid_to_letter(src_root, log)
    assert m[101] == "A"
    assert m[102] == "A"
    assert m[201] == "B"
    assert m[202] == "B"


def test_collect_files_for_letter_only_matching_jpgs(corpus_paths):
    src_root = corpus_paths["src_root"]
    files_map = corpus_paths["files"]
    pcids_by_letter = corpus_paths["pcids_by_letter"]
    mod = _load_module()
    import logging
    log = logging.getLogger("test")
    pcid_to_letter = mod.load_pcid_to_letter(src_root, log)
    a_files = mod.collect_files_for_letter(src_root, "A", pcid_to_letter)
    a_arcs = {arc.split("/", 2)[-1] for _, arc in a_files}
    # two A-jpgs (102 is two-sided) + A.html + A.json + shared = 7
    assert any(arc.endswith("101__1010.jpg") for _, arc in a_files)
    assert any(arc.endswith("102__1020.jpg") for _, arc in a_files)
    assert any(arc.endswith("102__1021.jpg") for _, arc in a_files)
    # orphan must NOT appear in letter A
    assert not any(arc.endswith("999__9990.jpg") for _, arc in a_files)
    # B jpgs must NOT appear in letter A
    assert not any(arc.endswith("201__2010.jpg") for _, arc in a_files)
    # Letter-page files must appear
    assert any(arc.endswith("A.html") for _, arc in a_files)
    assert any(arc.endswith("A.json") for _, arc in a_files)
    # Shared viewer/index
    assert any(arc.endswith("index.html") for _, arc in a_files)
    assert any(arc.endswith("all.json") for _, arc in a_files)
    # Shared metadata
    assert any(arc.endswith("enrichment_report.json") for _, arc in a_files)
    assert any(arc.endswith("red_ocr_results.json") for _, arc in a_files)
    assert any(arc.endswith("red_ocr_summary.json") for _, arc in a_files)
    # B-only metadata shouldn't be duplicated for letter A
    assert any(arc.endswith("ok_pensioners.json") for _, arc in a_files)


def test_by_letter_emits_one_zip_per_letter(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    rc = _run(src_root, out_dir, "--by-letter")
    assert rc == 0
    zips = sorted(p.name for p in out_dir.glob("*.zip"))
    # A.zip, B.zip, _.zip (orphan bucket), index.zip
    assert zips == ["bundle.A.zip", "bundle.B.zip",
                    "bundle._.zip", "bundle.index.zip"]


def test_by_letter_zip_contents_have_letter_page_only(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    with zipfile.ZipFile(out_dir / "bundle.A.zip") as zf:
        names = zf.namelist()
    # Letter A page exists, B page does NOT
    assert any(n.endswith("A.html") for n in names)
    assert any(n.endswith("A.json") for n in names)
    assert not any(n.endswith("B.html") for n in names)
    assert not any(n.endswith("B.json") for n in names)
    # A-jpgs present, B-jpgs absent, orphan absent (orphan lives in _.zip)
    assert "pension-viewer-bundle/data/cards/img/101__1010.jpg" in names
    assert "pension-viewer-bundle/data/cards/img/102__1020.jpg" in names
    assert "pension-viewer-bundle/data/cards/img/102__1021.jpg" in names
    assert "pension-viewer-bundle/data/cards/img/201__2010.jpg" not in names
    assert "pension-viewer-bundle/data/cards/img/999__9990.jpg" not in names


def test_by_letter_underscore_bucket_collects_unmapped_pcids(corpus_paths):
    """Pensioners with no letter (orphan pcids) ship in _.zip with the
    _.html / _.json page, so no jpgs are silently dropped."""
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    under = out_dir / "bundle._.zip"
    assert under.exists(), "expected _.zip for orphan bucket"
    with zipfile.ZipFile(under) as zf:
        names = zf.namelist()
    assert any(n.endswith("data/cards/viewer/_.html") for n in names)
    assert any(n.endswith("data/cards/viewer/_.json") for n in names)
    assert "pension-viewer-bundle/data/cards/img/999__9990.jpg" in names
    # A-only jpgs must NOT bleed into the orphan bucket
    assert "pension-viewer-bundle/data/cards/img/101__1010.jpg" not in names


def test_by_letter_index_zip_has_full_viewer_no_images(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    with zipfile.ZipFile(out_dir / "bundle.index.zip") as zf:
        names = zf.namelist()
    # Every letter page present (both A and B, plus _ for the bucket)
    assert any(n.endswith("A.html") for n in names)
    assert any(n.endswith("B.html") for n in names)
    assert any(n.endswith("_.html") for n in names)
    assert any(n.endswith("index.html") for n in names)
    assert any(n.endswith("all.json") for n in names)
    # NO images
    assert not any(n.endswith(".jpg") for n in names)


def test_by_letter_respects_letters_subset(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    rc = _run(src_root, out_dir, "--by-letter", "--letters", "A")
    assert rc == 0
    zips = sorted(p.name for p in out_dir.glob("*.zip"))
    assert zips == ["bundle.A.zip", "bundle.index.zip"]
    # B.zip + _.zip must NOT exist (--letters restricted to A only)
    assert not (out_dir / "bundle.B.zip").exists()
    assert not (out_dir / "bundle._.zip").exists()


def test_by_letter_dry_run_writes_nothing(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    rc = _run(src_root, out_dir, "--by-letter", "--dry-run")
    assert rc == 0
    assert not list(out_dir.glob("*.zip"))
    assert not list(out_dir.glob("*.partial"))


def test_by_letter_preserves_image_bytes(corpus_paths):
    """Letter zip must contain identical jpgs, not re-encoded."""
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    with zipfile.ZipFile(out_dir / "bundle.A.zip") as zf:
        data = zf.read("pension-viewer-bundle/data/cards/img/101__1010.jpg")
    assert data == b"A-PNG"


def test_by_letter_arcnames_use_bundle_prefix(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    for zipname in ("bundle.A.zip", "bundle._.zip", "bundle.index.zip"):
        with zipfile.ZipFile(out_dir / zipname) as zf:
            names = zf.namelist()
        # Every arcname is under pension-viewer-bundle/ so extraction
        # yields a self-contained folder.
        for n in names:
            assert n.startswith("pension-viewer-bundle/"), \
                f"{zipname}: bad arcname {n!r}"


def test_unselected_letter_in_subset_skipped_with_warning(corpus_paths, caplog):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    import logging
    caplog.set_level(logging.INFO, logger="distribute")
    rc = _run(src_root, out_dir, "--by-letter", "--letters", "A,QQ")
    assert rc == 0
    # QQ had no images — should be flagged as ignored in the log
    msgs = "\n".join(r.message for r in caplog.records)
    assert "QQ" in msgs, f"expected warning about QQ; got: {msgs!r}"
    zips = sorted(p.name for p in out_dir.glob("*.zip"))
    assert "bundle.A.zip" in zips
    assert "bundle.QQ.zip" not in zips
