"""Download script config-driven launcher.

Issue #142 follow-up (2026-07-31). Reads a JSON config that
captures every parameter of the application-images download
run, reconstructs the argv for `download_application_images.py`,
shells out, and records the config to
`data/ingest_runs/<run_name>.json` as the reproducibility
artifact.

Mirrors scripts/ingest/easyocr_launch.py exactly.

Config schema (missing keys fall back to the script's argparse
defaults):

- ``run_name`` (str, REQUIRED)
- ``input`` (str)   path to ok_pensioners.json
- ``out`` (str)     output directory for application jpgs
- ``summary`` (str) download-summary sidecar JSON path
- ``throttle`` (float) seconds between fetches
- ``refresh`` (bool)   force re-download even if file exists
- ``limit`` (int)      stop after N records (dry-runs)

Usage::

    cat > data/ingest_runs/applications_2026-07-29.json <<'JSON'
    {
      "run_name": "applications_2026-07-29",
      "throttle": 0.25,
      "limit": 0
    }
    JSON

    python scripts/ingest/download_launch.py \\
        data/ingest_runs/applications_2026-07-29.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DOWNLOAD_SCRIPT = _SCRIPTS_DIR / "download_application_images.py"
DEFAULT_RUNS_DIR = _ROOT / "data" / "ingest_runs"

DEFAULTS: dict[str, Any] = {
    "input": "docs/research/digitalprairie/ok_pensioners.json",
    "out": "data/cards/applications",
    "summary": "data/cards/download_summary_applications.json",
    "throttle": 0.25,
    "refresh": False,
    "limit": 0,
}


def load_config(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fill_defaults(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    out.update(cfg)
    return out


def save_config(cfg: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)
    return path


def build_argv(cfg: dict) -> list[str]:
    resolved = fill_defaults(cfg)
    argv = [sys.executable, "-u", str(DOWNLOAD_SCRIPT)]
    argv += ["--input", resolved["input"]]
    argv += ["--out", resolved["out"]]
    argv += ["--summary", resolved["summary"]]
    argv += ["--throttle", str(resolved["throttle"])]
    if resolved["refresh"]:
        argv.append("--refresh")
    argv += ["--limit", str(resolved["limit"])]
    return argv


def run_launcher(config_path: Path, *, dry_run: bool = False) -> int:
    config_path = Path(config_path)
    cfg = load_config(config_path)
    resolved = fill_defaults(cfg)
    save_config(resolved, config_path)

    argv = build_argv(resolved)
    sys.stderr.write(
        f"[download-launcher] run_name={resolved.get('run_name', '?')!r} "
        f"argv={' '.join(argv[2:])}\n"
    )
    if dry_run:
        return 0
    proc = subprocess.run(argv, cwd=str(_ROOT))
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return run_launcher(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
