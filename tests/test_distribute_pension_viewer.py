"""Tests for scripts/ingest/distribute_pension_viewer.py.

Pins the by-letter slicer contract for Layout A:

  bundle tree (per zipped letter):
    pension-viewer-bundle/data/cards/viewer/
    ├── index.html
    ├── all.json
    ├── lib/{alpine.min.js, openseadragon.min.js, openseadragon-images/}
    └── letters/{L}/
        ├── viewer/{L}.html
        ├── viewer/app.js
        ├── {L}.json
        └── img/{pcid}__{page}.jpg (only the jpgs for L)

  bundle tree (index zip):
    pension-viewer-bundle/data/cards/viewer/   (full viewer, no images)
    pension-viewer-bundle/docs/research/...    (metadata)
"""
from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
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
    """Build a tiny corpus shaped like build_pensioncard_viewer.py
    Layout A output:

      data/cards/img/{pcid}__{page}.jpg          (one or two sides)
      data/cards/viewer/index.html
      data/cards/viewer/all.json                 (by_letter shape)
      data/cards/viewer/letters/A/viewer/A.html, app.js
      data/cards/viewer/letters/A/A.json
      data/cards/viewer/letters/A/img/A*.jpg
      data/cards/viewer/letters/B/...
      data/cards/viewer/letters/_/...
      data/cards/viewer/lib/{alpine.min.js, openseadragon.min.js,
                              openseadragon-images/...}
    """
    # 1) Global img/ — these are the SOURCE files; build copies them
    # out into letters/{L}/img/. The bundler reads from letters/{L}/
    # not from the global img/ anymore.
    src_img = tmp_path / "data" / "cards" / "img"
    src_img.mkdir(parents=True)
    letter_pcid_payloads = {
        "A": {101: [("101__1010.jpg", b"A-PNG")],
              102: [("102__1020.jpg", b"A-PNG-FRONT"),
                    ("102__1021.jpg", b"A-PNG-BACK")]},
        "B": {201: [("201__2010.jpg", b"B-PNG")],
              202: [("202__2020.jpg", b"B-PNG-FRONT"),
                    ("202__2021.jpg", b"B-PNG-BACK")]},
        "_": {999: [("999__9990.jpg", b"ORPHAN")]},
    }
    for letter, pcids in letter_pcid_payloads.items():
        for pcid, lst in pcids.items():
            for name, payload in lst:
                (src_img / name).write_bytes(payload)

    # 2) viewer tree (Layout A)
    v = tmp_path / "data" / "cards" / "viewer"
    v.mkdir(parents=True, exist_ok=True)
    (v / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")

    # all.json — by_letter shape (current output of build script)
    by_letter_payload = {}
    for letter, pcids in letter_pcid_payloads.items():
        by_letter_payload[letter] = [
            {"pensioncard_id": pcid, "name_raw": f"Test {letter}-{pcid}",
             "death_date_iso": ""}
            for pcid in pcids
        ]
    (v / "all.json").write_text(
        json.dumps({"by_letter": by_letter_payload,
                    "total_pensioners": 5,
                    "rendered_letters": ["A", "B", "_"]}),
        encoding="utf-8")

    # letters/{L}/ subdirs
    for letter, pcids in letter_pcid_payloads.items():
        ldir = v / "letters" / letter
        (ldir / "viewer").mkdir(parents=True)
        (ldir / "viewer" / f"{letter}.html").write_text(
            f"<html>{letter}</html>", encoding="utf-8")
        (ldir / "viewer" / "app.js").write_text(
            f"// app.js for {letter}", encoding="utf-8")
        records = [{"pensioncard_id": pcid, "name_raw": f"{letter}-{pcid}"}
                   for pcid in pcids]
        (ldir / f"{letter}.json").write_text(
            json.dumps({"letter": letter, "records": records}),
            encoding="utf-8")
        (ldir / "img").mkdir(parents=True)
        for pcid, lst in pcids.items():
            for name, payload in lst:
                (ldir / "img" / name).write_bytes(payload)

    # lib/
    lib_dir = v / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "alpine.min.js").write_text("// alpine", encoding="utf-8")
    (lib_dir / "openseadragon.min.js").write_text(
        "// openseadragon", encoding="utf-8")
    osd_img = lib_dir / "openseadragon-images"
    osd_img.mkdir()
    (osd_img / "home_rest.png").write_bytes(b"\x89PNG\r\n")

    # 3) Metadata
    (tmp_path / "data" / "cards" / "enrichment_report.json").write_text(
        '{"changed": []}', encoding="utf-8")
    (tmp_path / "data" / "cards" / "red_ocr_results.json").write_text(
        '{}', encoding="utf-8")
    (tmp_path / "data" / "cards" / "red_ocr_summary.json").write_text(
        '{}', encoding="utf-8")

    dp = tmp_path / "docs" / "research" / "digitalprairie"
    dp.mkdir(parents=True)
    (dp / "ok_pensioners.json").write_text("[]", encoding="utf-8")
    (dp / "ok_pensioners.with_death_dates.json").write_text(
        "[]", encoding="utf-8")

    return {
        "src_root": tmp_path,
        "out_dir": tmp_path / "dist",
        "letter_pcid_payloads": letter_pcid_payloads,
    }


@pytest.fixture
def corpus_paths(corpus):
    return corpus


# ============================================================
# Helpers
# ============================================================

def _run(src_root, out_dir, *extra):
    """Invoke main() with the script's module-ROOT monkey-patched to
    point at src_root."""
    mod = _load_module()
    monkey = sys.modules["distribute_pension_viewer"]
    monkey.ROOT = Path(src_root)
    argv = ["--out", str(out_dir / "bundle.zip"), *extra]
    return mod.main(argv)


# ============================================================
# Module / unit tests
# ============================================================

def test_load_module():
    mod = _load_module()
    for fn in ("main", "run_by_letter", "collect_files_for_letter",
               "load_pcid_to_letter"):
        assert hasattr(mod, fn), f"missing {fn}"


def test_load_pcid_to_letter_reads_by_letter_shape(corpus_paths):
    src_root = corpus_paths["src_root"]
    mod = _load_module()
    import logging
    log = logging.getLogger("test")
    m = mod.load_pcid_to_letter(src_root, log)
    assert m[101] == "A"
    assert m[102] == "A"
    assert m[201] == "B"
    assert m[202] == "B"
    assert m[999] == "_"


def test_collect_files_for_letter_layout_a(corpus_paths):
    """Per-letter file list matches the Layout A path scheme."""
    src_root = corpus_paths["src_root"]
    mod = _load_module()
    import logging
    log = logging.getLogger("test")
    pcid_to_letter = mod.load_pcid_to_letter(src_root, log)
    a_files = mod.collect_files_for_letter(src_root, "A", pcid_to_letter)
    arcs = [arc for _, arc in a_files]

    # Letter-specific page + app.js + sidecar JSON live under
    # data/cards/viewer/letters/A/ in the bundle.
    assert any("data/cards/viewer/letters/A/viewer/A.html" in a for a in arcs)
    assert any("data/cards/viewer/letters/A/viewer/app.js" in a for a in arcs)
    assert any("data/cards/viewer/letters/A/A.json" in a for a in arcs)

    # Images live under data/cards/viewer/letters/A/img/ for letter A
    assert any("data/cards/viewer/letters/A/img/101__1010.jpg" in a for a in arcs)
    assert any("data/cards/viewer/letters/A/img/102__1020.jpg" in a for a in arcs)
    assert any("data/cards/viewer/letters/A/img/102__1021.jpg" in a for a in arcs)
    # B-letter jpgs must NOT leak into letter A
    assert not any("data/cards/viewer/letters/A/img/201" in a for a in arcs)
    # Orphan goes to _'s img/, NOT letter A's
    assert not any("data/cards/viewer/letters/A/img/999__9990.jpg" in a
                   for a in arcs)

    # Shared viewer files (top-level index.html, all.json, lib/)
    assert any("data/cards/viewer/index.html" in a for a in arcs)
    assert any("data/cards/viewer/all.json" in a for a in arcs)
    assert any("data/cards/viewer/lib/alpine.min.js" in a for a in arcs)
    assert any("data/cards/viewer/lib/openseadragon.min.js" in a for a in arcs)
    assert any("data/cards/viewer/lib/openseadragon-images/home_rest.png"
               in a for a in arcs)

    # Shared metadata under pension-viewer-bundle/data/cards/ and docs/
    assert any(arc.endswith("data/cards/enrichment_report.json") for arc in arcs)
    assert any(arc.endswith("docs/research/digitalprairie/ok_pensioners.json")
               for arc in arcs)


def test_collect_index_files_has_no_images(corpus_paths):
    src_root = corpus_paths["src_root"]
    mod = _load_module()
    import logging
    log = logging.getLogger("test")
    files = mod.collect_index_files(src_root)
    arcs = [arc for _, arc in files]
    # No jpgs at all in the index zip
    assert not any(a.endswith(".jpg") for a in arcs), arcs
    # But every viewer page is present
    for L in ("A", "B", "_"):
        assert any(f"letters/{L}/viewer/{L}.html" in a for a in arcs), L
    assert any("data/cards/viewer/index.html" in a for a in arcs)


# ============================================================
# End-to-end (zip write + read)
# ============================================================

def test_by_letter_emits_one_zip_per_letter(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    rc = _run(src_root, out_dir, "--by-letter")
    assert rc == 0
    zips = sorted(p.name for p in out_dir.glob("*.zip"))
    # A.zip, B.zip, _.zip (orphan), index.zip
    assert zips == ["bundle.A.zip", "bundle.B.zip",
                    "bundle._.zip", "bundle.index.zip"]


def test_by_letter_zip_contents_layout_a(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    with zipfile.ZipFile(out_dir / "bundle.A.zip") as zf:
        names = zf.namelist()
    # Letter page lives at data/cards/viewer/letters/A/viewer/A.html
    assert "pension-viewer-bundle/data/cards/viewer/letters/A/viewer/A.html" in names
    assert "pension-viewer-bundle/data/cards/viewer/letters/A/A.json" in names
    assert "pension-viewer-bundle/data/cards/viewer/letters/A/viewer/app.js" in names
    # Images live under letters/A/img/ (NOT the global img/)
    assert "pension-viewer-bundle/data/cards/viewer/letters/A/img/101__1010.jpg" in names
    assert "pension-viewer-bundle/data/cards/viewer/letters/A/img/102__1020.jpg" in names
    # No foreign letter
    assert not any("letters/B/" in n for n in names)
    # Top-level viewer index, all.json, lib/ all present
    assert "pension-viewer-bundle/data/cards/viewer/index.html" in names
    assert "pension-viewer-bundle/data/cards/viewer/all.json" in names
    assert "pension-viewer-bundle/data/cards/viewer/lib/alpine.min.js" in names


def test_by_letter_index_zip_full_viewer_no_images(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    with zipfile.ZipFile(out_dir / "bundle.index.zip") as zf:
        names = zf.namelist()
    assert not any(n.endswith(".jpg") for n in names)
    # All letter pages + index + lib present
    for L in ("A", "B", "_"):
        assert any(f"letters/{L}/viewer/{L}.html" in n for n in names)
    assert any("data/cards/viewer/index.html" in n for n in names)


def test_by_letter_respects_letters_subset(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    rc = _run(src_root, out_dir, "--by-letter", "--letters", "A")
    assert rc == 0
    zips = sorted(p.name for p in out_dir.glob("*.zip"))
    assert zips == ["bundle.A.zip", "bundle.index.zip"]
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
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    arc = "pension-viewer-bundle/data/cards/viewer/letters/A/img/101__1010.jpg"
    with zipfile.ZipFile(out_dir / "bundle.A.zip") as zf:
        data = zf.read(arc)
    assert data == b"A-PNG"


def test_by_letter_arcnames_use_bundle_prefix(corpus_paths):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    _run(src_root, out_dir, "--by-letter")
    for zipname in ("bundle.A.zip", "bundle._.zip", "bundle.index.zip"):
        with zipfile.ZipFile(out_dir / zipname) as zf:
            for n in zf.namelist():
                assert n.startswith("pension-viewer-bundle/"), \
                    f"{zipname}: bad arcname {n!r}"


def test_unselected_letter_in_subset_skipped_with_warning(corpus_paths, caplog):
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    import logging
    caplog.set_level(logging.INFO, logger="distribute")
    rc = _run(src_root, out_dir, "--by-letter", "--letters", "A,QQ")
    assert rc == 0
    msgs = "\n".join(r.message for r in caplog.records)
    assert "QQ" in msgs
    zips = sorted(p.name for p in out_dir.glob("*.zip"))
    assert "bundle.A.zip" in zips
    assert "bundle.QQ.zip" not in zips


def test_by_letter_merges_clean_into_one_folder(corpus_paths, tmp_path):
    """End-to-end Layout A invariant: extracting every emitted zip
    into one folder produces zero on-disk conflicts. Each letter's
    files live in letters/{L}/ so they cannot overlap regardless of
    how many pcids live across the corpus."""
    src_root = corpus_paths["src_root"]
    out_dir = corpus_paths["out_dir"]
    rc = _run(src_root, out_dir, "--by-letter")
    assert rc == 0
    merge = tmp_path / "merged"
    if merge.exists():
        import shutil; shutil.rmtree(merge)
    merge.mkdir()
    for zp in sorted(out_dir.glob("bundle.*.zip")):
        with zipfile.ZipFile(zp) as zf:
            zf.extractall(merge)
    # Walk every extracted file; arc basename -> write-set must be
    # singleton (or, for files shared across letter zips + index,
    # byte-identical).
    from collections import defaultdict
    by_relpath: dict[str, list[Path]] = defaultdict(list)
    for p in merge.rglob("*"):
        if p.is_file():
            by_relpath[p.relative_to(merge).as_posix()].append(p)
    # Just confirm no arc was written twice with conflicting bytes.
    # Files that ship in every letter-zip (index.html, all.json,
    # lib/*) come out byte-identical by construction.
    conflicts = []
    for rel, ps in by_relpath.items():
        if len(ps) > 1:
            first = ps[0].read_bytes()
            for other in ps[1:]:
                if other.read_bytes() != first:
                    conflicts.append(rel)
    assert not conflicts, f"conflicting duplicate files: {conflicts[:5]}"
    # Sanity: full viewer tree present
    a_html = merge / "pension-viewer-bundle" / "data" / "cards" / "viewer" / "letters" / "A" / "viewer" / "A.html"
    assert a_html.exists(), f"missing A.html at {a_html}"
    assert (merge / "pension-viewer-bundle" / "data" / "cards" / "viewer" / "index.html").exists()
    assert (merge / "pension-viewer-bundle" / "data" / "cards" / "viewer" / "lib" / "alpine.min.js").exists()
    # Both A and B images present
    assert (merge / "pension-viewer-bundle" / "data" / "cards" / "viewer" / "letters" / "A" / "img" / "101__1010.jpg").exists()
    assert (merge / "pension-viewer-bundle" / "data" / "cards" / "viewer" / "letters" / "B" / "img" / "201__2010.jpg").exists()
    assert (merge / "pension-viewer-bundle" / "data" / "cards" / "viewer" / "letters" / "_" / "img" / "999__9990.jpg").exists()
