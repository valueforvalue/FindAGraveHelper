#!/usr/bin/env bash
# restart.sh — resume a failed FindAGraveHelper run
# Generated for run directory: C:\Users\jmorris\AppData\Local\Temp\fag_g10
set -euo pipefail

RUN_DIR="C:\Users\jmorris\AppData\Local\Temp\fag_g10"
CONFIG="C:\Users\jmorris\AppData\Local\Temp\fag_g10\config.json"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: config.json not found at $CONFIG" >&2
  exit 1
fi

echo "Resuming run from $RUN_DIR"
echo "Config: $CONFIG"

exec python scripts/run_unified.py --config "$CONFIG" "$@"
