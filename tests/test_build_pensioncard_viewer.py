"""Tests for scripts/ingest/build_pensioncard_viewer.py.

Pins two contracts:

1. Letter routing — given ok_pensioners.json rows with various
   last_name/name_raw shapes, every pcid with a usable surname ends
   up under that letter's slice (not the '_' orphan bucket unless
   it really is orphaned).

2. Layout A — the viewer tree on disk has:
   - <out>/index.html  (top-level, alphabet grid)
   - <out>/all.json
   - <out>/lib/{alpine.min.js, leaflet.min.js,
                 leaflet.css, leaflet-images/*.png}
   - <out>/letters/{L}/viewer/{L}.html
   - <out>/letters/{L}/viewer/app.js
   - <out>/letters/{L}/{L}.json
   - <out>/letters/{L}/img/{pcid}__{page}.jpg
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "ingest" / "build_pensioncard_viewer.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_pensioncard_viewer", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_pensioncard_viewer"] = mod
    spec.loader.exec_module(mod)
    return mod


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def viewer_corpus(tmp_path):
    """Build a tiny corpus:

    data/cards/img/ — none (so records without images can still be
        tested for letter routing via enriched data).
    docs/research/digitalprairie/ok_pensioners.json — synthetic rows.
    data/cards/enrichment_report.json — synthetic entries for the
        records that don't have images.

    We deliberately include name-raw shapes that the previous
    heuristic broke on:
      - last_name='', name_raw='Costen A. J.'          (real surname)
      - last_name='', name_raw='Mrs. J. R.'            ('Mrs.' title only)
      - last_name='', name_raw='Mooney James W a.pdf'  (PDF junk tail)
      - last_name='', name_raw='(01) Index ...'        (parens title)
    """
    dp = tmp_path / "docs" / "research" / "digitalprairie"
    dp.mkdir(parents=True)
    rows = [
        # Real pensioners
        {"id": 1, "pensioncard_id": 101, "last_name": "Allen",
         "name_raw": "Allen, Reubin B.", "spouse_name_raw": ""},
        {"id": 2, "pensioncard_id": 102, "last_name": "Baker",
         "name_raw": "Baker, John R.", "spouse_name_raw": ""},
        {"id": 3, "pensioncard_id": 2048, "last_name": "",
         "name_raw": "Costen A. J.", "spouse_name_raw": ""},
        {"id": 4, "pensioncard_id": 3031, "last_name": "",
         "name_raw": "Neely Mrs. C. R.", "spouse_name_raw": ""},
        {"id": 5, "pensioncard_id": 3420, "last_name": "",
         "name_raw": "Mooney James W a1176 p1458.pdf", "spouse_name_raw": ""},
        # Real Mrs. card — title only, no comma, real surname missing
        # (this is the genuine orphan case that should land in _)
        {"id": 6, "pensioncard_id": 6001, "last_name": "",
         "name_raw": "Mrs. So-and-So", "spouse_name_raw": ""},
        # Parens title (index card)
        {"id": 7, "pensioncard_id": 888, "last_name": "",
         "name_raw": "(01) About the Commissioner", "spouse_name_raw": ""},
    ]
    (dp / "ok_pensioners.json").write_text(
        json.dumps(rows), encoding="utf-8")

    # No jpgs on disk; coverage is from enriched data alone.
    img_dir = tmp_path / "data" / "cards" / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    # Enrichment report — gives every record at least one row so
    # build_pensioncard_viewer.py keeps it
    rep = tmp_path / "data" / "cards" / "enrichment_report.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({"changed": [
        {"pensioncard_id": pcid, "death_year": 1915,
         "death_date_iso": "1915-02-26", "is_widow_card": False,
         "near_death_keyword": False, "mentions_soldier_name": False}
        for pcid in (101, 102, 2048, 3031, 3420, 6001, 888)
    ]}), encoding="utf-8")

    # Vendor dir placeholder so vendor_libs doesn't warn or fail
    vendor = tmp_path / "scripts" / "ingest" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "alpine.min.js").write_text("// alpine", encoding="utf-8")
    (vendor / "leaflet.min.js").write_text(
        "// leaflet", encoding="utf-8")
    (vendor / "leaflet.css").write_text(
        "/* leaflet css */", encoding="utf-8")
    (vendor / "leaflet-images").mkdir(parents=True, exist_ok=True)
    (vendor / "leaflet-images" / "marker-icon.png").write_bytes(b"PNG")

    return {
        "src_root": tmp_path,
        "out_dir": tmp_path / "data" / "cards" / "viewer",
    }


# ============================================================
# Tests
# ============================================================

def test_load_module():
    mod = _load_module()
    assert hasattr(mod, "main")
    assert hasattr(mod, "render_letter")
    assert hasattr(mod, "place_letter_files")
    assert hasattr(mod, "vendor_libs")


def test_letter_routing_records_to_correct_buckets(viewer_corpus):
    """`Costen A. J.` ends up in letter C, not '_'. Real 'Mrs.
    So-and-So' goes to '_'."""
    # Patch module's script-relative _SCRIPTS_DIR / VENDOR_DIR so
    # vendor_libs() can find alpine.min.js + leaflet.min.js + leaflet.css in
    # our tmp vendor dir.
    src_root = viewer_corpus["src_root"]
    mod = _load_module()
    monkey = sys.modules["build_pensioncard_viewer"]
    # The script's VENDOR_DIR is _SCRIPTS_DIR / "vendor". We override
    # VENDORED_LIBS to points in our tmp tree by monkey-patching the
    # helper.
    from types import SimpleNamespace
    fake_vendor = src_root / "scripts" / "ingest" / "vendor"
    monkey.VENDOR_DIR = fake_vendor
    rc = mod.main([
        "--input", str(src_root / "docs" / "research" / "digitalprairie" / "ok_pensioners.json"),
        "--report", str(src_root / "data" / "cards" / "enrichment_report.json"),
        "--img-dir", str(src_root / "data" / "cards" / "img"),
        "--out-dir", str(viewer_corpus["out_dir"]),
    ])
    # main() returns None on success
    assert (viewer_corpus["out_dir"] / "all.json").exists()

    by_letter = json.loads((viewer_corpus["out_dir"] / "all.json").read_text())["by_letter"]

    def has_pcid(letter, pcid):
        return any(r["pensioncard_id"] == pcid for r in by_letter.get(letter, []))

    # Real surnames hit their letter
    assert has_pcid("A", 101), "Allen → A"
    assert has_pcid("B", 102), "Baker → B"
    assert has_pcid("C", 2048), "Costen A.J. → C"
    assert has_pcid("N", 3031), "Neely Mrs. C.R. → N (real surname)"
    assert has_pcid("M", 3420), "Mooney James W a1176 p1458.pdf → M"

    # Genuine orphan (Mrs. So-and-So) goes to _
    assert has_pcid("_", 6001), "Mrs. So-and-So → _"

    # Parens-title index card also goes to _
    assert has_pcid("_", 888), "(01) About the Commissioner → _"


def test_layout_a_top_level_files(viewer_corpus):
    """index.html, all.json, lib/ at the bundle root."""
    src_root = viewer_corpus["src_root"]
    mod = _load_module()
    monkey = sys.modules["build_pensioncard_viewer"]
    fake_vendor = src_root / "scripts" / "ingest" / "vendor"
    monkey.VENDOR_DIR = fake_vendor
    mod.main([
        "--input", str(src_root / "docs" / "research" / "digitalprairie" / "ok_pensioners.json"),
        "--report", str(src_root / "data" / "cards" / "enrichment_report.json"),
        "--img-dir", str(src_root / "data" / "cards" / "img"),
        "--out-dir", str(viewer_corpus["out_dir"]),
    ])
    out = viewer_corpus["out_dir"]
    assert (out / "index.html").exists()
    assert (out / "all.json").exists()
    assert (out / "lib" / "alpine.min.js").exists()
    assert (out / "lib" / "leaflet.min.js").exists()
    assert (out / "lib" / "leaflet.css").exists()
    assert any((out / "lib" / "leaflet-images").glob("*.png"))


def test_layout_a_per_letter_subdirs(viewer_corpus):
    """letters/{L}/ subdirs contain viewer/, img/, sidecar json."""
    src_root = viewer_corpus["src_root"]
    mod = _load_module()
    monkey = sys.modules["build_pensioncard_viewer"]
    fake_vendor = src_root / "scripts" / "ingest" / "vendor"
    monkey.VENDOR_DIR = fake_vendor
    mod.main([
        "--input", str(src_root / "docs" / "research" / "digitalprairie" / "ok_pensioners.json"),
        "--report", str(src_root / "data" / "cards" / "enrichment_report.json"),
        "--img-dir", str(src_root / "data" / "cards" / "img"),
        "--out-dir", str(viewer_corpus["out_dir"]),
    ])
    out = viewer_corpus["out_dir"]
    for L in ("A", "B", "C", "M", "N", "_"):
        ldir = out / "letters" / L
        assert ldir.exists(), f"missing letters/{L}/"
        assert (ldir / "viewer" / f"{L}.html").exists()
        assert (ldir / "viewer" / "app.js").exists()
        assert (ldir / f"{L}.json").exists()
        assert (ldir / "img").exists()


def test_index_links_into_letter_pages(viewer_corpus):
    """index.html's Alpine card array points into letters/{L}/viewer/{L}.html."""
    src_root = viewer_corpus["src_root"]
    mod = _load_module()
    monkey = sys.modules["build_pensioncard_viewer"]
    fake_vendor = src_root / "scripts" / "ingest" / "vendor"
    monkey.VENDOR_DIR = fake_vendor
    mod.main([
        "--input", str(src_root / "docs" / "research" / "digitalprairie" / "ok_pensioners.json"),
        "--report", str(src_root / "data" / "cards" / "enrichment_report.json"),
        "--img-dir", str(src_root / "data" / "cards" / "img"),
        "--out-dir", str(viewer_corpus["out_dir"]),
    ])
    idx_html = (viewer_corpus["out_dir"] / "index.html").read_text(encoding="utf-8")
    for L in ("A", "B", "C"):
        assert f"letters/{L}/viewer/{L}.html" in idx_html, \
            f"letter card for {L} must link into letters/{L}/viewer/{L}.html"


def test_letter_page_html_uses_alpine_and_leaflet(viewer_corpus):
    """Each letter page loads vendor libs and wires the lightbox."""
    src_root = viewer_corpus["src_root"]
    mod = _load_module()
    monkey = sys.modules["build_pensioncard_viewer"]
    fake_vendor = src_root / "scripts" / "ingest" / "vendor"
    monkey.VENDOR_DIR = fake_vendor
    mod.main([
        "--input", str(src_root / "docs" / "research" / "digitalprairie" / "ok_pensioners.json"),
        "--report", str(src_root / "data" / "cards" / "enrichment_report.json"),
        "--img-dir", str(src_root / "data" / "cards" / "img"),
        "--out-dir", str(viewer_corpus["out_dir"]),
    ])
    a_html = (viewer_corpus["out_dir"] / "letters" / "A" / "viewer" / "A.html").read_text(encoding="utf-8")
    assert "../../../lib/alpine.min.js" in a_html
    assert "../../../lib/leaflet.min.js" in a_html
    assert "leaflet.css" in a_html
    assert "lightbox-overlay" in a_html
    # The viewer factory (L.imageOverlay / mountLeaflet) lives in
    # app.js, not the page template. Verify it's there too.
    app_js = (viewer_corpus["out_dir"] / "letters" / "A" / "viewer" / "app.js").read_text(encoding="utf-8")
    assert "L.imageOverlay" in app_js
    # Image src uses ../img/ relative path (letters/A/img is a sibling of viewer/)
    assert "../img/" in a_html
    assert "../../../index.html" in a_html
