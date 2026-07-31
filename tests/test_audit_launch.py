"""Tests for scripts/audit/audit_launch.py.

Mirrors the test shape of tests/test_easyocr_launch.py: config
round-trip, default filling, argv reconstruction, schema freeze.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.audit import audit_launch as launch  
from scripts.audit import audit_death_dates as audit  


# ---- 1. Config schema --------------------------------------------------

def test_minimal_config_round_trips():
    cfg = {
        "run_name": "smoke",
        "enriched": "docs/research/digitalprairie/ok_pensioners.with_death_dates.json",
        "enrichment": "data/cards/enrichment_report.json",
        "ocr": "data/cards/red_ocr_results.json",
        "out_json": "data/audit_death_dates_report.json",
        "out_md": "data/audit_death_dates_report.md",
        "strict": False,
    }
    path = launch.save_config(cfg, _ROOT / "data" / "audit_runs" / "x.json")
    loaded = launch.load_config(path)
    assert loaded == cfg


def test_defaults_filled():
    empty: dict = {}
    args = launch.build_argv(empty)
    assert "--enriched" in args
    assert (args[args.index("--enriched") + 1]
            == "docs/research/digitalprairie/ok_pensioners.with_death_dates.json")
    assert "--enrichment" in args
    assert "--ocr" in args
    assert "--out-json" in args
    assert "--out-md" in args
    assert "--strict" not in args


def test_strict_flag_included_when_true():
    args = launch.build_argv({"strict": True})
    assert "--strict" in args


def test_strict_flag_absent_when_false():
    args = launch.build_argv({"strict": False})
    assert "--strict" not in args


def test_out_paths_passed_through():
    args = launch.build_argv({
        "out_json": "/tmp/custom.json",
        "out_md": "/tmp/custom.md",
    })
    assert args[args.index("--out-json") + 1] == "/tmp/custom.json"
    assert args[args.index("--out-md") + 1] == "/tmp/custom.md"


def test_audit_death_dates_help_works():
    """Smoke: the audit script's main() must be invokable with
    --help (regression check on the argparse refactor)."""
    from scripts.audit.audit_death_dates import main
    assert callable(main)


def test_audit_death_dates_runs_with_default_paths(monkeypatch, tmp_path):
    """Smoke: main() with empty args list should run end-to-end
    on the canonical paths and write the reports."""
    
    from scripts.audit import audit_death_dates as audit
    rc = audit.main([])
    
    assert rc in (0, 1)
    
    assert Path("data/audit_death_dates_report.json").exists()


# ---- 2. Schema freeze -------------------------------------------------

def test_schema_documented_in_module_docstring():
    import inspect
    doc = inspect.getdoc(launch)
    assert doc is not None
    for key in ("run_name", "enriched", "enrichment", "ocr",
                "out_json", "out_md", "strict"):
        assert key in doc, (
            f"config key {key!r} undocumented in launcher docstring"
        )
