"""Tests for scripts/ingest/download_launch.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_ROOT = _TESTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ingest import download_launch as launch  


def test_minimal_config_round_trips():
    cfg = {
        "run_name": "applications_smoke",
        "input": "docs/research/digitalprairie/ok_pensioners.json",
        "out": "data/cards/applications",
        "summary": "data/cards/download_summary_applications.json",
        "throttle": 0.25,
        "refresh": False,
        "limit": 100,
    }
    path = launch.save_config(cfg, _ROOT / "data" / "ingest_runs" / "x.json")
    loaded = launch.load_config(path)
    assert loaded == cfg


def test_defaults_filled():
    empty: dict = {}
    args = launch.build_argv(empty)
    assert "--input" in args
    assert (args[args.index("--input") + 1]
            == "docs/research/digitalprairie/ok_pensioners.json")
    assert "--out" in args
    assert "--summary" in args
    assert "--throttle" in args
    assert float(args[args.index("--throttle") + 1]) == 0.25
    assert int(args[args.index("--limit") + 1]) == 0


def test_refresh_flag_included_when_true():
    args = launch.build_argv({"refresh": True})
    assert "--refresh" in args


def test_refresh_flag_absent_when_false():
    args = launch.build_argv({"refresh": False})
    assert "--refresh" not in args


def test_throttle_passed_through():
    args = launch.build_argv({"throttle": 0.5})
    assert float(args[args.index("--throttle") + 1]) == 0.5


def test_limit_passed_through():
    args = launch.build_argv({"limit": 100})
    assert int(args[args.index("--limit") + 1]) == 100


def test_help_works():
    from scripts.ingest.download_application_images import main
    assert callable(main)


def test_schema_documented_in_module_docstring():
    import inspect
    doc = inspect.getdoc(launch)
    assert doc is not None
    for key in ("run_name", "input", "out", "summary",
                "throttle", "refresh", "limit"):
        assert key in doc, (
            f"config key {key!r} undocumented in launcher docstring"
        )
