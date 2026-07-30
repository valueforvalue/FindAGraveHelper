"""EasyOCR resume script.

Reads a saved run config and re-launches the run. The resume
contract:

- If the config's output == input and input is the canonical
  ``data/cards/red_ocr_results.json``, the resume always emits
  ``--in-place`` regardless of what the user originally set.
  This is safe because ``easyocr_pass.py``'s skip rule (records
  with ``easy_text`` already set are skipped) is the resume
  handshake.
- If the config points at a sidecar (e.g. a slice file), the
  sidecar's ``in_place`` is left alone.

This script is the single command an agent or operator runs
to resume the long EasyOCR death-date enrichment run after an
interruption. The only argument is the path to the saved
config artifact.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.ingest import easyocr_launch as launch  
from scripts.ingest import easyocr_resume as resume_mod  


CANONICAL_PATH = Path("data/cards/red_ocr_results.json")


def resolve_resume_mode(cfg: dict) -> dict:
    """Set in_place=True when the config's output resolves to
    the canonical file. Sidecar configs are untouched."""
    out = dict(cfg)
    output = Path(out.get("output") or out.get("input") or "")
    input_path = Path(out.get("input") or "")
    if output == input_path and output.name == CANONICAL_PATH.name:
        out["in_place"] = True
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config", type=Path,
                    help="path to the saved JSON config")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the resolved argv + save the "
                         "filled config, but do not invoke "
                         "easyocr_pass.py")
    args = ap.parse_args(argv)

    cfg = launch.load_config(args.config)
    resolved = resolve_resume_mode(cfg)
    launch.save_config(resolved, args.config)
    return launch.run_launcher(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
