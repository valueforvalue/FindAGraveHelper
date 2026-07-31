"""Audit script config-driven launcher.

Issue #141 follow-up (2026-07-31). Reads a JSON config that
captures every parameter of the audit run, reconstructs the
argv for `audit_death_dates.py`, shells out, and records the
config + the result counts to `data/audit_runs/<run_name>.json`
as the reproducibility artifact.

Mirrors scripts/ingest/easyocr_launch.py exactly. The audit
script is independent of the OCR script, but the launcher
shape is the same: external, atomic, schema-free.

Config schema (missing keys fall back to audit_death_dates.py's
argparse defaults):

- ``run_name`` (str, REQUIRED)
- ``enriched`` (str)   path to ok_pensioners.with_death_dates.json
- ``enrichment`` (str) path to data/cards/enrichment_report.json
- ``ocr`` (str)        path to data/cards/red_ocr_results.json
- ``out_json`` (str)   output JSON path
- ``out_md`` (str)     output markdown path
- ``strict`` (bool)    exit 1 on any finding (for CI gating)

Usage::

    cat > data/audit_runs/2026-07-31_l3.json <<'JSON'
    {
      "run_name": "2026-07-31_l3",
      "strict": true
    }
    JSON

    python scripts/audit/audit_launch.py data/audit_runs/2026-07-31_l3.json
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

AUDIT_SCRIPT = _SCRIPTS_DIR / "audit_death_dates.py"
DEFAULT_RUNS_DIR = _ROOT / "data" / "audit_runs"

DEFAULTS: dict[str, Any] = {
    "enriched": "docs/research/digitalprairie/ok_pensioners.with_death_dates.json",
    "enrichment": "data/cards/enrichment_report.json",
    "ocr": "data/cards/red_ocr_results.json",
    "out_json": "data/audit_death_dates_report.json",
    "out_md": "data/audit_death_dates_report.md",
    "strict": False,
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
    argv = [sys.executable, "-u", str(AUDIT_SCRIPT)]
    argv += ["--enriched", resolved["enriched"]]
    argv += ["--enrichment", resolved["enrichment"]]
    argv += ["--ocr", resolved["ocr"]]
    argv += ["--out-json", resolved["out_json"]]
    argv += ["--out-md", resolved["out_md"]]
    if resolved["strict"]:
        argv.append("--strict")
    return argv


def run_launcher(config_path: Path, *, dry_run: bool = False) -> int:
    config_path = Path(config_path)
    cfg = load_config(config_path)
    resolved = fill_defaults(cfg)
    save_config(resolved, config_path)

    argv = build_argv(resolved)
    sys.stderr.write(
        f"[audit-launcher] run_name={resolved.get('run_name', '?')!r} "
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
