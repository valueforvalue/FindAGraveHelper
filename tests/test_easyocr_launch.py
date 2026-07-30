"""Tests for the EasyOCR config-driven launcher + resume script.

These tests do NOT load the EasyOCR model or read images. They
exercise:

1. Config schema + load/save round-trip.
2. CLI arg reconstruction from a config (the seam between the
   launcher and the existing easyocr_pass.py argparse).
3. Resume-skip behavior on the canonical file (records with
   `easy_text` already present are not re-OCR'd).
4. Refuse-to-overwrite guard when the config's output resolves
   to the canonical file but the in-memory record count looks
   like a slice.

The launcher + resume script live in scripts/ingest/. They are
external to easyocr_pass.py: easyocr_pass.py's argparse is the
single source of truth for the CLI surface; the launcher reads
JSON, reconstructs argv, and shells out to easyocr_pass.py.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ingest import easyocr_launch as launch  
from scripts.ingest import easyocr_resume as resume_mod  


# ---- 1. Config schema --------------------------------------------------

def test_minimal_config_round_trips():
    """A minimal config (the keys needed for the full-resume
    invocation) survives JSON round-trip with no extra fields.
    """
    cfg = {
        "run_name": "full_2026-07-29",
        "input": "data/cards/red_ocr_results.json",
        "output": "data/cards/red_ocr_results.json",
        "in_place": True,
        "img_dir": "data/cards/img",
        "include_soldiers": True,
        "only_widows": False,
        "priority_only": False,
        "refresh": False,
        "throttle": 0.25,
        "workers": 1,
        "limit": 0,
    }
    path = launch.save_config(cfg, _ROOT / "data" / "easyocr_runs" / "x.json")
    loaded = launch.load_config(path)
    assert loaded == cfg


def test_missing_keys_filled_with_easyocr_pass_defaults():
    """An empty config + the easyocr_pass defaults are valid:
    the launcher fills in argparse defaults for anything missing.
    """
    empty: dict = {}
    args = launch.build_argv(empty)
    
    assert "--input" in args
    assert "data/cards/red_ocr_results.json" in args
    assert "--output" in args
    assert "--throttle" in args
    assert "--workers" in args
    assert int(args[args.index("--workers") + 1]) == 1
    assert float(args[args.index("--throttle") + 1]) == 0.25
    assert int(args[args.index("--limit") + 1]) == 0


def test_in_place_flag_included_when_true():
    cfg = {"in_place": True}
    args = launch.build_argv(cfg)
    assert "--in-place" in args


def test_in_place_flag_absent_when_false():
    cfg = {"in_place": False}
    args = launch.build_argv(cfg)
    assert "--in-place" not in args


def test_include_soldiers_flag_included():
    cfg = {"include_soldiers": True, "only_widows": False}
    args = launch.build_argv(cfg)
    assert "--include-soldiers" in args
    assert "--only-widows" not in args


def test_only_widows_default_explicit():
    """The full-resume config explicitly sets only_widows=False
    + include_soldiers=True. The launcher must emit the exact
    pair the canonical run used (otherwise the resume will skip
    a different set of records than the original run)."""
    cfg = {"only_widows": False, "include_soldiers": True}
    args = launch.build_argv(cfg)
    assert "--include-soldiers" in args
    assert "--only-widows" not in args


def test_priority_only_flag_included():
    cfg = {"priority_only": True}
    args = launch.build_argv(cfg)
    assert "--priority-only" in args


def test_refresh_flag_included():
    cfg = {"refresh": True}
    args = launch.build_argv(cfg)
    assert "--refresh" in args


def test_limit_passed_through():
    cfg = {"limit": 5}
    args = launch.build_argv(cfg)
    assert "--limit" in args
    assert int(args[args.index("--limit") + 1]) == 5


def test_workers_passed_through():
    cfg = {"workers": 6}
    args = launch.build_argv(cfg)
    assert int(args[args.index("--workers") + 1]) == 6


# ---- 2. Resume vs fresh run distinction --------------------------------

def test_resume_artifact_writes_canonical_path_in_place():
    """The resume script always emits --in-place when output ==
    input AND input is the canonical file. Sidecar-slice
    configs are not affected.
    """
    cfg = {
        "input": "data/cards/red_ocr_results.json",
        "output": "data/cards/red_ocr_results.json",
        "in_place": False,  
    }
    resolved = resume_mod.resolve_resume_mode(cfg)
    assert resolved["in_place"] is True, (
        "resume must auto-set in_place when input==output and "
        "target is the canonical file"
    )


def test_resume_artifact_leaves_sidecar_config_alone():
    """A config whose output is a sidecar file is not promoted
    to in-place. The user explicitly chose the sidecar."""
    cfg = {
        "input": "data/cards/red_ocr_results.json",
        "output": "data/cards/easyocr_slice_5.json",
        "in_place": False,
    }
    resolved = resume_mod.resolve_resume_mode(cfg)
    assert resolved["in_place"] is False
    assert resolved["output"] == "data/cards/easyocr_slice_5.json"


# ---- 3. Sliced-output safety guard (mirrors easyocr_pass.py) ----------

def test_slice_to_canonical_refused_without_in_place(monkeypatch, tmp_path):
    """If a user hands the launcher a config that points at the
    canonical file but limits the in-memory record count to a
    slice size, the launcher must refuse to overwrite the
    canonical file (mirroring easyocr_pass.py's safety guard).
    """
    
    fake_canonical = tmp_path / "red_ocr_results.json"
    sidecar_in = tmp_path / "slice_in.json"
    sidecar_in.write_text(json.dumps([{"_": i} for i in range(5)]))
    fake_canonical.write_text(
        json.dumps([{"_": i} for i in range(9436)])
    )

    cfg = {
        "input": str(sidecar_in),
        "output": str(fake_canonical),
        "in_place": False,
    }
    n = len(json.loads(sidecar_in.read_text()))
    assert launch._refuse_canonical_clobber(
        cfg, _override_paths=True, _input_load_count=n,
    ) is True


def test_run_launcher_exits_2_when_clobber_guard_fires(monkeypatch, tmp_path):
    """End-to-end: run_launcher() must SystemExit(2) when the
    safety guard fires."""
    fake_canonical = tmp_path / "red_ocr_results.json"
    sidecar_in = tmp_path / "slice_in.json"
    sidecar_in.write_text(json.dumps([{"_": i} for i in range(5)]))
    fake_canonical.write_text(
        json.dumps([{"_": i} for i in range(9436)])
    )

    cfg = {
        "input": str(sidecar_in),
        "output": "data/cards/red_ocr_results.json",
        "in_place": False,
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg))

    noop_pass = tmp_path / "noop_pass.py"
    noop_pass.write_text("# stub")

    with monkeypatch.context() as m:
        m.setattr(launch, "EASYOCR_PASS", noop_pass)
        rc = launch.run_launcher(cfg_path, dry_run=False)
    assert rc == 2


def test_slice_to_canonical_allowed_with_in_place(monkeypatch, tmp_path):
    """Same setup but in_place=True: the run is allowed (the
    safety guard is a 'looks like a slice' warning)."""
    fake_canonical = tmp_path / "red_ocr_results.json"
    sidecar_in = tmp_path / "slice_in.json"
    sidecar_in.write_text(json.dumps([{"_": i} for i in range(5)]))
    fake_canonical.write_text(
        json.dumps([{"_": i} for i in range(9436)])
    )

    cfg = {
        "input": str(sidecar_in),
        "output": str(fake_canonical),
        "in_place": True,
    }
    
    assert launch._refuse_canonical_clobber(
        cfg, _override_paths=True,
        _input_load_count=len(json.loads(sidecar_in.read_text())),
    ) is False


# ---- 4. Skip-on-easy_text resume contract ------------------------------

def test_skip_resume_count_matches_easy_text_present():
    """The resume-skip contract: records with `easy_text` already
    set are skipped. The launcher must expose the count of
    already-done records so the user can see real progress.
    """
    records = [
        {"easy_text": "abc"},
        {"easy_text": "def"},
        {"easy_text": None},  
        {},
        {"death_date": {"year": 1933}},  
    ]
    assert launch.count_already_done(records) == 2


# ---- 5. Schema freeze -------------------------------------------------

def test_schema_documented_in_module_docstring():
    """The launcher module must document every config key it
    accepts; that's how a future agent recovers the run."""
    import inspect
    doc = inspect.getdoc(launch)
    assert doc is not None
    for key in (
        "run_name", "input", "output", "in_place", "img_dir",
        "include_soldiers", "only_widows", "priority_only",
        "refresh", "throttle", "workers", "limit",
    ):
        assert key in doc, (
            f"config key {key!r} undocumented in launcher docstring"
        )
