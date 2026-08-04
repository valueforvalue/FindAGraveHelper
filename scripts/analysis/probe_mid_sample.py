"""Pick 5 mid-set records (likely misses) for smoke testing."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from probe_575_capped import build_input
soldiers = build_input()
# Pick records 200-204 (mid-set, where B1 misses are more likely)
mid = soldiers[200:205]
with open("data/probe_input_mid5.json", "w") as f:
    json.dump(mid, f, indent=2)
for s in mid:
    print(f"  {s['soldier_id']}: {s['first']} {s['last']} bucket={s['bucket']} state='{s['state']}'")
