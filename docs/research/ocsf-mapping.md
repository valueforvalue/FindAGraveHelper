# OCSF Event Mapping (issue #100)

> **Standard:** [OCSF 1.8.0](https://schema.ocsf.io/1.8.0/)
> **Schema source:** `scripts/events/ocsf.py::OCSF_MAPPING`
> **Source-of-truth log:** `run_audit.jsonl` (native, JSONL)
> **Sidecar:** `run_audit.ocsf.jsonl` (OCSF, one envelope per line)

## Why OCSF

The pipeline's native audit log (`run_audit.jsonl`) is the
source of truth for operator analysis — directly greppable,
human-readable, and the format the runner emits. The OCSF
sidecar exists for one purpose: **SIEM ingestion**. Splunk,
Datadog, Elastic, and similar tools all consume OCSF
natively; the translation layer means operators can pipe
the pipeline's throttle + scheduler events into their SIEM
without writing a custom adapter.

The native format is never modified. The OCSF file is a
read-only sidecar that can be ignored entirely by operators
who don't need SIEM integration.

## Class + activity mapping

| Native event          | OCSF class_uid | OCSF class_name                    | activity_id | Note |
|-----------------------|---------------:|------------------------------------|------------:|------|
| `work_claimed`        | 1006 | Scheduled Job Activity             | 1 (Create)  | Blackboard claim |
| `work_completed`      | 1006 | Scheduled Job Activity             | 3 (Complete) | Blackboard finish |
| `strategy_ran`        | 1006 | Scheduled Job Activity             | 2 (Update)  | Per-strategy audit |
| `strategy_skipped`    | 1006 | Scheduled Job Activity             | 2 (Update)  | Per-strategy audit |
| `strategy_error`      | 1006 | Scheduled Job Activity             | 2 (Update)  | Per-strategy audit |
| `pensioner_start`     | 1006 | Scheduled Job Activity             | 1 (Create)  | Per-pensioner |
| `pensioner_end`       | 1006 | Scheduled Job Activity             | 3 (Complete) | Per-pensioner |
| `observation_appended` | 1006 | Scheduled Job Activity             | 2 (Update)  | Blackboard event |
| `run_summary`         | 1006 | Scheduled Job Activity             | 2 (Update)  | Run completion |
| `cooldown_set`        | 7003 | Process Remediation Activity       | 2 (Update)  | Throttle response |
| `bot_wall_observed`   | 2004 | Detection Finding                  | 1 (Create)  | CF challenge detection |

**activity_id semantics (OCSF ActivityId enum):**
- 1 = Create (the work was claimed, the pensioner was imported, the finding was raised)
- 2 = Update (an in-progress state change; strategy result, observation, remediation)
- 3 = Complete (the work was completed, the pensioner finished)
- 4 = Delete (not currently used; reserved for future eviction events)

## Envelope shape (per class)

### 1006 — Scheduled Job Activity

```json
{
  "class_uid": 1006,
  "class_name": "Scheduled Job Activity",
  "activity_id": 1,
  "time": 1784915693400,
  "metadata": {
    "product": {"name": "FindAGraveHelper", "version": "1.0.0"},
    "version": "1.8.0"
  },
  "job": {
    "name": "FaGScraperKS:strategy:B1-exact",
    "pensioner_id": 327,
    "strategy": "B1-exact",
    "candidates": 5,
    "state": "OK"
  }
}
```

The `job.name` is the OCSF analog of the OCSF `Job` object's
`name` field. For strategy events it's
`FaGScraperKS:strategy:<name>`. For work events it's the
work_id. For pensioner events it's `pensioner:<id>`.

### 7003 — Process Remediation Activity

```json
{
  "class_uid": 7003,
  "class_name": "Process Remediation Activity",
  "activity_id": 2,
  "time": 1784915693400,
  "metadata": {...},
  "remediation": {
    "name": "throttle_cooldown",
    "provider": "findagrave.com",
    "not_before": "2026-07-24T18:00:00Z"
  }
}
```

The `remediation` object carries the OCSF `remediation`
class's standard fields. `name: throttle_cooldown` is the
specific remediation type; `provider` and `not_before` are
the operator-relevant parameters.

### 2004 — Detection Finding

```json
{
  "class_uid": 2004,
  "class_name": "Detection Finding",
  "activity_id": 1,
  "time": 1784915693400,
  "metadata": {...},
  "finding_info": {
    "name": "cloudflare_bot_wall",
    "pensioner_id": 327,
    "url": "https://www.findagrave.com/memorial/12345"
  }
}
```

The `finding_info` object carries the OCSF Finding class's
verdict. `name: cloudflare_bot_wall` is the specific
detection type; `pensioner_id` + `url` are the trigger.

## Time format

OCSF time is `int` milliseconds since epoch (UTC). The
native log uses `float` seconds; the translation multiplies
by 1000 and truncates. The test suite pins this
conversion.

## What is NOT in the OCSF sidecar

- **Unknown event types.** If a future PR adds an event type
  before updating the mapping table, the OCSF sidecar silently
  skips it. Operators can grep `run_audit.jsonl` for the
  unknown event; the sidecar will be updated when the
  mapping table is.
- **Anything that isn't an audit event.** Per-observation
  payloads (full ScoreObserved, full StrategyResult) stay
  in the Blackboard. OCSF envelopes are summary-level
  by design (SIEMs want patterns, not full payloads).

## SIEM ingestion example

The sidecar is `run_audit.ocsf.jsonl` with one envelope per
line. Any OCSF-aware consumer can ingest it:

```bash
# Splunk:
$SPLUNK_HOME/bin/splunk add oneshot run_audit.ocsf.jsonl \
    -sourcetype ocsf:findagravehelper

# Datadog:
datadog-agent run-check ocsf --file run_audit.ocsf.jsonl

# Custom Python (rdflib / ocsf-parser):
python -m ocsf.parse run_audit.ocsf.jsonl
```

The `metadata.product.name: FindAGraveHelper` field lets
operators filter to pipeline events in a multi-source SIEM.

## Related

- `scripts/events/ocsf.py` — the translator.
- `tests/test_ocsf_events.py` — 14 tests pinning the contract.
- `docs/research/competitive-audit.md` §Axis 3 — the
  orchestrator peer-review that motivated this work.
- Issue #100 — the GitHub issue tracking this work.