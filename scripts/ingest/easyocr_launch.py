"""EasyOCR config-driven launcher.

Issue #139 follow-up (2026-07-30). Reads a JSON config that
captures every parameter of the EasyOCR run, reconstructs the
argv for ``easyocr_pass.py``, shells out, and records the
config + the result counts to ``data/easyocr_runs/<run_name>.json``
as the reproducibility artifact.

Why a launcher, not a --config flag on easyocr_pass.py:

- The in-flight run (started 2026-07-29 21:01 UTC) used the
  existing argparse surface; if we add --config now and the
  in-flight run was somehow re-spawned, the CLI surface would
  diverge from the saved config.
- The repo's prior pattern (red_ink_ocr_watchdog.py,
  re_enrich_from_ocr.py) is thin external scripts; the
  launcher fits the same shape.
- Future agents reading the repo need one place to find the
  run recipe. The JSON artifact IS that place. The CLI flags
  in easyocr_pass.py are the implementation detail.

Config schema (the canonical set of keys; missing keys fall
back to easyocr_pass.py's argparse defaults):

- ``run_name`` (str, REQUIRED) — the run's display name. Used
  as the basename for the artifact path and in log lines.
- ``input`` (str) — path to the cached OCR results JSON
  (default: ``data/cards/red_ocr_results.json``).
- ``output`` (str) — path to write the updated results.
  Default: same as ``input`` (in-place).
- ``in_place`` (bool) — required ``true`` when ``output ==
  input`` AND ``input`` is the canonical file AND the
  in-memory record count is < 1000. The launcher refuses
  to proceed without it (see _refuse_canonical_clobber).
- ``img_dir`` (str) — directory containing the card jpegs
  (default: ``data/cards/img``).
- ``include_soldiers`` (bool) — include soldier records
  (default: false → widows only).
- ``only_widows`` (bool) — widows only (default: true).
  Set ``include_soldiers: true, only_widows: false`` for
  the full pass.
- ``priority_only`` (bool) — only records with empty
  ``red_text`` (highest-value subset).
- ``refresh`` (bool) — re-OCR even if ``easy_text`` is
  already set.
- ``throttle`` (float) — seconds between images (default 0.25).
- ``workers`` (int) — parallel EasyOCR workers (default 1;
  CPU-bound on this box, do not raise).
- ``limit`` (int) — process at most N records (smoke test).

Usage::

    # Create a config (any way you like; JSON is the
    # reproducibility artifact).
    cat > data/easyocr_runs/full_2026-07-29.json <<'JSON'
    {
      "run_name": "full_2026-07-29",
      "include_soldiers": true,
      "only_widows": false,
      "in_place": true
    }
    JSON

    # Run.
    python scripts/ingest/easyocr_launch.py \\
        data/easyocr_runs/full_2026-07-29.json

The launcher writes back the resolved config (every key
filled) to the same path. The artifact therefore captures
the effective config used for the run — not just the user's
intent.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Ensure Unicode stdout on Windows (per python skill
# §"Windows Pitfalls": cp1252 console crashes on emoji/unicode).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

EASYOCR_PASS = _SCRIPTS_DIR / "easyocr_pass.py"
DEFAULT_RUNS_DIR = _ROOT / "data" / "easyocr_runs"

# ---- Defaults (mirror easyocr_pass.py argparse defaults) --------------

DEFAULTS: dict[str, Any] = {
    "input": "data/cards/red_ocr_results.json",
    "output": None,                  
    "in_place": False,
    "img_dir": "data/cards/img",
    "include_soldiers": False,
    "only_widows": True,
    "priority_only": False,
    "refresh": False,
    "throttle": 0.25,
    "workers": 1,
    "limit": 0,
}


# ---- Config I/O -------------------------------------------------------

def load_config(path: Path) -> dict:
    """Load a JSON config from disk. Missing keys are NOT filled
    here; the caller decides whether to call fill_defaults."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fill_defaults(cfg: dict) -> dict:
    """Return a copy of cfg with every known key filled in. The
    input is not mutated."""
    out = dict(DEFAULTS)
    out.update(cfg)
    if out["output"] is None:
        out["output"] = out["input"]
    return out


def save_config(cfg: dict, path: Path) -> Path:
    """Atomic save: write to a temp file, then rename. Survives
    a kill -9 mid-write (the rename is atomic on the same
    filesystem)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)
    return path


# ---- argv reconstruction ----------------------------------------------

def build_argv(cfg: dict) -> list[str]:
    """Reconstruct the easyocr_pass.py argv from a config.

    The order matches the original easyocr_pass.py argparse
    surface so a future agent can diff the launched command
    against the in-flight run's log. If the in-flight run
    command changes, this mapping breaks loudly (a test
    pins the canonical mapping).
    """
    resolved = fill_defaults(cfg)
    argv = [sys.executable, "-u", str(EASYOCR_PASS)]
    argv += ["--input", resolved["input"]]
    argv += ["--output", resolved["output"]]
    if resolved["in_place"]:
        argv.append("--in-place")
    argv += ["--img-dir", resolved["img_dir"]]
    if resolved["include_soldiers"]:
        argv.append("--include-soldiers")
    if resolved["only_widows"] and not resolved["include_soldiers"]:
        argv.append("--only-widows")
    if resolved["priority_only"]:
        argv.append("--priority-only")
    if resolved["refresh"]:
        argv.append("--refresh")
    argv += ["--throttle", str(resolved["throttle"])]
    argv += ["--workers", str(resolved["workers"])]
    argv += ["--limit", str(resolved["limit"])]
    return argv


# ---- Safety guard (mirrors easyocr_pass.py) ---------------------------

def count_already_done(records: list[dict]) -> int:
    """How many records already have easy_text. The skip rule
    lives in easyocr_pass.py; we surface the count for log
    output only."""
    return sum(1 for r in records if r.get("easy_text"))


def _refuse_canonical_clobber(
    cfg: dict,
    *,
    _override_paths: bool = False,
    _input_load_count: int | None = None,
) -> bool:
    """Return True if the launch should be refused.

    Mirrors the safety guard in easyocr_pass.py: refuse to
    overwrite the canonical red_ocr_results.json when the
    in-memory record count looks like a slice (< 1000) and
    in_place wasn't set.
    """
    resolved = fill_defaults(cfg)
    if resolved["in_place"]:
        return False
    if Path(resolved["output"]).name != "red_ocr_results.json":
        return False
    if not _override_paths:
        return False
    if _input_load_count is None:
        return False
    return _input_load_count < 1000


# ---- Run --------------------------------------------------------------

def run_launcher(
    config_path: Path,
    *,
    dry_run: bool = False,
    python_executable: str | None = None,
) -> int:
    """Run the launcher end-to-end.

    1. Load + fill + save the config (the artifact).
    2. If output == canonical and record count looks like a
       slice and in_place is False: refuse (return 2).
    3. Shells out to easyocr_pass.py with the reconstructed
       argv. Streams output to the launcher's stdout.
    4. Returns the easyocr_pass.py exit code.
    """
    config_path = Path(config_path)
    cfg = load_config(config_path)
    resolved = fill_defaults(cfg)

    
    in_path = Path(resolved["input"])
    if in_path.exists():
        try:
            input_records = json.loads(in_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            input_records = []
    else:
        input_records = []
    already_done = count_already_done(input_records)

    
    if Path(resolved["output"]).resolve() == Path("data/cards/red_ocr_results.json").resolve():
        if _refuse_canonical_clobber(
            resolved,
            _override_paths=True,
            _input_load_count=len(input_records),
        ):
            sys.stderr.write(
                f"REFUSING: output resolves to canonical "
                f"data/cards/red_ocr_results.json but input has "
                f"only {len(input_records)} records (looks like a "
                f"slice). Pass in_place=true to proceed.\n"
            )
            return 2

    
    save_config(resolved, config_path)

    argv = build_argv(resolved)
    sys.stderr.write(
        f"[launcher] run_name={resolved.get('run_name', '?')!r} "
        f"already_done={already_done}/{len(input_records)} "
        f"argv={' '.join(argv[2:])}\n"
    )

    if dry_run:
        return 0

    proc = subprocess.run(argv, cwd=str(_ROOT))
    return proc.returncode


# ---- CLI --------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config", type=Path,
                    help="path to the JSON config")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the resolved argv + save the "
                         "filled config, but do not invoke "
                         "easyocr_pass.py")
    args = ap.parse_args(argv)
    return run_launcher(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
