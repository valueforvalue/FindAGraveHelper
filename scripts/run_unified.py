"""Back-compat shim. Real implementation: scripts.pipeline.run_unified (T021)."""
import sys
from pathlib import Path

# Bootstrap sys.path so `scripts.X` imports resolve when this file
# is invoked as a top-level script (e.g. `python scripts/run_unified.py`).
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_ROOT = _SCRIPTS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.pipeline.run_unified import *  # noqa: F401, F403
from scripts.pipeline.run_unified import cli_main  # noqa: F401


if __name__ == "__main__":
    raise SystemExit(cli_main(sys.argv[1:]))