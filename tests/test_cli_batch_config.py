"""CLI integration tests for --config arg + init-batch subcommand (J5-S1).

Tests the argument parsing + dispatch without actually running a batch
(fag_search_fn is mocked; no Playwright involved).
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run_unified import cli_main  # noqa: E402


def _make_pensioners_file(path: Path, n: int = 3) -> None:
    """Write a small ok_pensioners.json fixture."""
    import json
    data = [
        {
            "id": i + 1,
            "first_name": "John",
            "last_name": f"Smith{i}",
            "middle_name": "",
            "regiment": "10 AL",
            "death_year": "1930",
            "application_number": f"A{i+1}",
        }
        for i in range(n)
    ]
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_cgr_file(path: Path) -> None:
    """Write an empty enriched CGR JSONL."""
    path.write_text("", encoding="utf-8")


def test_cli_init_batch_creates_run_dir(tmp_path, monkeypatch, capsys):
    """`run_unified.py init-batch <name>` creates output/<name>/config.json."""
    monkeypatch.chdir(tmp_path)
    rc = cli_main(["init-batch", "alpha"])
    assert rc == 0
    cfg = tmp_path / "output" / "alpha" / "config.json"
    assert cfg.exists()
    captured = capsys.readouterr()
    assert "alpha" in captured.out
    assert str(cfg) in captured.out


def test_cli_init_batch_rejects_existing(tmp_path, monkeypatch):
    """`run_unified.py init-batch` refuses to clobber an existing run dir."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output" / "alpha").mkdir(parents=True)
    rc = cli_main(["init-batch", "alpha"])
    assert rc != 0


def test_cli_config_loads_and_runs(tmp_path, monkeypatch):
    """`--config output/foo/config.json` runs the batch end-to-end (no-fag mode).

    Verifies:
      - The config file is loaded
      - out_dir is derived from config.runname (output/<runname>/)
      - Results file appears at output/<runname>/results.jsonl? (S2 territory;
        this slice still uses state.jsonl, so just check state.jsonl here)
    """
    monkeypatch.chdir(tmp_path)
    # Scaffold input + cgr fixtures
    pensioners_file = tmp_path / "pensioners.json"
    cgr_file = tmp_path / "cgr.jsonl"
    _make_pensioners_file(pensioners_file, n=3)
    _make_cgr_file(cgr_file)

    # Scaffold the run via init-batch
    rc = cli_main(["init-batch", "beta"])
    assert rc == 0

    # Overwrite config.json with paths pointing at our fixtures
    cfg_path = tmp_path / "output" / "beta" / "config.json"
    import json
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["input"] = str(pensioners_file)
    cfg["cgr"] = str(cgr_file)
    cfg["start_row"] = 0
    cfg["end_row"] = 3
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Run with --config and --no-fag (no Playwright)
    with patch("scripts.fag_browser.make_fag_search_fn") as mfsf:
        rc = cli_main(["--config", str(cfg_path), "--no-fag"])
    assert rc == 0
    # Results file should exist under output/beta/
    state = tmp_path / "output" / "beta" / "results.jsonl"
    assert state.exists()


def test_cli_config_runname_mismatch_exits(tmp_path, monkeypatch):
    """`--config` whose runname doesn't match out_dir basename → non-zero exit."""
    monkeypatch.chdir(tmp_path)
    pensioners_file = tmp_path / "p.json"
    cgr_file = tmp_path / "c.jsonl"
    _make_pensioners_file(pensioners_file, n=1)
    _make_cgr_file(cgr_file)

    # Make output/foo/ but config says runname="bar"
    (tmp_path / "output" / "foo").mkdir(parents=True)
    cfg_path = tmp_path / "output" / "foo" / "config.json"
    import json
    cfg_path.write_text(json.dumps({
        "runname": "bar",
        "input": str(pensioners_file),
        "cgr": str(cgr_file),
    }), encoding="utf-8")

    rc = cli_main(["--config", str(cfg_path), "--no-fag"])
    assert rc != 0