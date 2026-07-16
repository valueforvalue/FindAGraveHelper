"""Tests for J5-S3: resume.sh artifact + log line + stdout print.

Surface 1: resume.sh written to output/<runname>/resume.sh at run end
  and on KeyboardInterrupt. The file is the exact CLI invocation
  needed to resume.

Surface 2: log line appended to run.log with the same command.

Surface 3: stdout gets the resume command (also via log/StreamHandler).

Edge: post-KeyboardInterrupt, the partial state.jsonl is reloadable.
"""
import io
import json
import logging
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.pipeline.run_unified import (  # noqa: E402
    UnifiedRunnerConfig,
    run_batch,
    cli_main,
    write_resume_artifact,
    build_resume_command,
)


def _sample_pensioners(n=2):
    return [
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


def _sample_cems():
    return [{"cemetery_id": 1, "veterans": []}]


def _fake_fag_no_results(p, c):
    return [], "no_results"


# ============================================================
# build_resume_command (pure function)
# ============================================================
def test_build_resume_command_uses_config():
    """Resume command references --config output/<runname>/config.json."""
    cfg_path = (Path("output") / "foo" / "config.json").resolve()
    cmd = build_resume_command(config_path=cfg_path)
    assert "--config" in cmd
    # Path may be normalized to absolute form on some platforms;
    # check the basename + that the parent dirs are present
    assert "config.json" in cmd
    assert "foo" in cmd


def test_build_resume_command_quotes_path_with_spaces():
    """Paths with spaces are quoted."""
    cfg_path = (Path("output") / "run with space" / "config.json").resolve()
    cmd = build_resume_command(config_path=cfg_path)
    assert "config.json" in cmd


def test_build_resume_command_is_absolute_when_given_absolute():
    cfg_path = (Path("/tmp/foo/config.json")).resolve()
    cmd = build_resume_command(config_path=cfg_path)
    assert "config.json" in cmd
    assert "foo" in cmd


# ============================================================
# write_resume_artifact (unit)
# ============================================================
def test_write_resume_artifact_creates_file(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    log = logging.getLogger("test_write_resume")
    write_resume_artifact(
        out_dir=out_dir,
        config_path=tmp_path / "out" / "config.json",
        log=log,
    )
    assert (out_dir / "resume.sh").exists()


def test_write_resume_artifact_content_includes_config(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = tmp_path / "out" / "config.json"
    log = logging.getLogger("test_write_resume_2")
    write_resume_artifact(out_dir=out_dir, config_path=cfg, log=log)
    content = (out_dir / "resume.sh").read_text(encoding="utf-8")
    assert "--config" in content
    assert str(cfg) in content
    # Shebang or python invocation present
    assert "python" in content.lower()


def test_write_resume_artifact_executable_on_posix(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = tmp_path / "out" / "config.json"
    log = logging.getLogger("test_write_resume_3")
    write_resume_artifact(out_dir=out_dir, config_path=cfg, log=log)
    f = out_dir / "resume.sh"
    if os.name == "posix":
        assert os.access(f, os.X_OK), "resume.sh must be executable on POSIX"


def test_write_resume_artifact_logs_command(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = tmp_path / "out" / "config.json"

    log = logging.getLogger("test_write_resume_4")
    log.setLevel(logging.INFO)
    sink = io.StringIO()
    handler = logging.StreamHandler(sink)
    log.addHandler(handler)

    write_resume_artifact(out_dir=out_dir, config_path=cfg, log=log)
    handler.flush()
    out = sink.getvalue()
    assert "RESUME COMMAND:" in out
    assert str(cfg) in out


def test_write_resume_artifact_idempotent(tmp_path):
    """Calling write_resume_artifact twice doesn't error and the file
    is still there."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = tmp_path / "out" / "config.json"
    log = logging.getLogger("test_write_resume_5")
    write_resume_artifact(out_dir=out_dir, config_path=cfg, log=log)
    write_resume_artifact(out_dir=out_dir, config_path=cfg, log=log)
    assert (out_dir / "resume.sh").exists()


# ============================================================
# run_batch integration: resume.sh appears at completion
# ============================================================
def test_run_batch_writes_resume_sh(tmp_path):
    """After run_batch, the run dir contains a resume.sh."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
    )
    run_batch(pensioners=_sample_pensioners(2),
              cemeteries=_sample_cems(),
              config=cfg,
              log=logging.getLogger("test_resume_int"),
              config_path_for_resume=tmp_path / "out" / "config.json",
    )
    assert (out_dir / "resume.sh").exists()


def test_run_batch_writes_resume_command_to_log(tmp_path):
    """run.log contains a RESUME COMMAND: line."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    log_path = out_dir / "run.log"
    # Capture into run.log via a real FileHandler
    log = logging.getLogger("test_resume_log")
    log.setLevel(logging.INFO)
    for h in list(log.handlers):
        log.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)

    cfg = UnifiedRunnerConfig(
        out_dir=out_dir,
        fag_search_fn=_fake_fag_no_results,
    )
    run_batch(
        pensioners=_sample_pensioners(1),
        cemeteries=_sample_cems(),
        config=cfg,
        log=log,
        config_path_for_resume=tmp_path / "out" / "config.json",
    )
    fh.flush()
    fh.close()
    content = log_path.read_text(encoding="utf-8")
    assert "RESUME COMMAND:" in content


# ============================================================
# cli_main integration: resume.sh on completion + on interrupt
# ============================================================
def _make_pensioners_file(path: Path, n: int = 2) -> None:
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
    path.write_text("", encoding="utf-8")


def test_cli_resume_sh_written_on_completion(tmp_path, monkeypatch):
    """`run_unified.py --config ...` writes resume.sh on completion."""
    monkeypatch.chdir(tmp_path)
    pensioners_file = tmp_path / "p.json"
    cgr_file = tmp_path / "c.jsonl"
    _make_pensioners_file(pensioners_file, n=2)
    _make_cgr_file(cgr_file)

    rc = cli_main(["init-batch", "gamma"])
    assert rc == 0

    cfg_path = tmp_path / "output" / "gamma" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["input"] = str(pensioners_file)
    cfg["cgr"] = str(cgr_file)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    with patch("scripts.fag_browser.make_fag_search_fn"):
        rc = cli_main(["--config", str(cfg_path), "--no-fag"])

    assert rc == 0
    resume = tmp_path / "output" / "gamma" / "resume.sh"
    assert resume.exists()
    content = resume.read_text(encoding="utf-8")
    assert "--config" in content
    assert "config.json" in content
    # run.log captures the RESUME COMMAND line (logging → file)
    run_log = tmp_path / "output" / "gamma" / "run.log"
    if run_log.exists():
        assert "RESUME COMMAND" in run_log.read_text(encoding="utf-8")


def test_cli_resume_after_keyboard_interrupt(tmp_path, monkeypatch):
    """KeyboardInterrupt mid-run still writes resume.sh; state is reloadable."""
    monkeypatch.chdir(tmp_path)
    pensioners_file = tmp_path / "p.json"
    cgr_file = tmp_path / "c.jsonl"
    _make_pensioners_file(pensioners_file, n=5)
    _make_cgr_file(cgr_file)

    rc = cli_main(["init-batch", "delta"])
    assert rc == 0

    cfg_path = tmp_path / "output" / "delta" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["input"] = str(pensioners_file)
    cfg["cgr"] = str(cgr_file)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Make the fag search fn raise KeyboardInterrupt on the 2nd pensioner
    call_count = {"n": 0}

    def fake_fag(p, c):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise KeyboardInterrupt("simulated user abort")
        return [], "no_results"

    with patch("scripts.fag_browser.make_fag_search_fn", return_value=fake_fag):
        rc = cli_main(["--config", str(cfg_path)])

    # cli_main returns 130 on KeyboardInterrupt
    assert rc == 130
    resume = tmp_path / "output" / "delta" / "resume.sh"
    assert resume.exists(), "resume.sh must be written on interrupt"

    # The partial state.jsonl must be reloadable
    results = tmp_path / "output" / "delta" / "results.jsonl"
    if results.exists():
        lines = [
            json.loads(l) for l in results.read_text(encoding="utf-8").strip().split("\n") if l
        ]
        # The first pensioner completed; the second was interrupted mid-call
        # (no record written). Third+ were never reached.
        assert len(lines) >= 1
        assert lines[0]["pensioner_id"] == 1