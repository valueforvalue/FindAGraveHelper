# Live verification run — 2026-07-24 (issue #94 stealth swap)

> **Purpose:** end-to-end verification that the patchright
> stealth swap (issue #94) reaches Find a Grave without tripping
> the Cloudflare Turnstile 1015 backoff. The artifacts in this
> directory are the evidence.

## Run command

```bash
STEALTH_BACKEND=patchright \
  python -m scripts.pipeline.run_unified \
    --input docs/research/digitalprairie/ok_pensioners_g10.json \
    --cgr docs/research/cgr/ok_vets_enriched.jsonl \
    --out /tmp/fag_g10 \
    --limit 10 \
    --throttle 2.5
```

(`--input` is the 10 G-name slice: J. Gamble, John Gamblin, Martha
Gammon, Anna Gardner, J. Garner, Martha Garner, H. Garton, Nancy
Gentry, Nannie Gentry, Morris Gilbert.)

## Result

| Field | Value |
|---|---|
| Pensioners processed | 10 / 10 |
| Work items dispatched | 115 |
| Errors | 0 |
| Auto-accepts | 0 |
| Needs-review | 10 |
| Wall clock | 19 min 36 s |
| Cloudflare 1015 backoff | none |

## Artifacts

| File | What it proves |
|---|---|
| `results.jsonl` (3.6 MB) | 10 state rows with real FaG candidate URLs + per-record decisions. The row for pensioner 327 (J. Gamble) has `best_score: 0.644` and a real `https://www.findagrave.com/memorial/20360270/john-henry-gamble` link in `ranked_candidates`. **10/10 rows have `pensioncard_pages` populated** (auto-derived from the `pensioncard_iiif_url` field by the issue #101 fix; see `pensioncard_pages.json` sidecar below). |
| `open_gravestones.ndjson` (10 KB) | JSON-LD export with `@context` bundling Schema.org + Dublin Core + WikiTree + Wikidata + PROV-DM (issue #95). Same Gamble record emitted as a JSON-LD Person with the FaG memorial URL in `sameAs`. |
| `results.schema.json` (5.2 KB) | 28-field schema spec, `schema_version: 2` (issue #98). Proves the projection layer stamps the per-row `_schema_version` field. |
| `pensioncard_pages.json` (370 B) | Auto-derived sidecar (issue #101): `{pensioner_id_str: [pensioncard_id]}` mapping. Built from the `pensioncard_iiif_url` field in results.jsonl on first annotation. Single-page items (73% of pensioncards) get `[pensioncard_id]`; compound items would need `scripts/ingest/fetch_pensioncard_pages.py` to populate. |
| `view.html` (3.6 MB) | Self-contained review UI; opens in any browser without a server. Embedded results + sidecar JSON. |
| `run.log` (1.9 KB) | Per-pensioner log lines, including the scheduler batches and the `BrowserSession closed` shutdown. |
| `run_audit.jsonl` (1.2 MB) | Per-strategy audit events (RunAuditLog + observer). Includes `observation_appended`, `work_claimed`, `work_completed`, `cooldown_set`. |
| `run_analytics.json` (3.2 KB) | Per-KS metrics summary (issue #84 AnalyticsAggregator). |
| `blackboard.db` (5.0 MB) | SQLite WAL store: 115 work items + observations + lease history (heartbeats from issue #97). |
| `restart.sh` (516 B) | Auto-generated restart script. Run with `bash restart.sh` to resume from this state. |

## Regressions caught during the run

The run surfaced one real bug in the issue #97 heartbeat
implementation:

> `SQLite objects created in a thread can only be used in that
> same thread. The object was created in thread id 8552 and this
> is thread id 18832.`

The `SqliteBlackboardStore` connection is opened on the main
thread, but the issue #97 heartbeat thread is a daemon thread.
The connection was using the default `check_same_thread=True`.

**Fix:** `scripts/blackboard/store.py` now opens the connection
with `check_same_thread=False` and serializes writes via a
`threading.Lock` (so SQLite WAL mode still gets correct per-row
sequencing). The lock is the right defense — concurrent writes
across threads would otherwise race the WAL checkpoint.

The fix is part of the same commit as the swap (commit
`f09b871`).

## How to reproduce

1. Install patchright + chromium:
   ```bash
   pip install -r requirements-ci.txt
   python -m patchright install chromium
   ```
2. Run the same command (substituting the output dir for any
   path you can write to).
3. Open `view.html` in a browser to inspect the 10 records.

The expected result is identical to this directory: 10
`needs_review` rows, no errors, no 1015 backoff.

## Related

- Issue #94 — the swap itself.
- Issue #97 — the heartbeat that surfaced the cross-thread bug.
- `CONTEXT.md` §L8 — the FaG-PoT-only law, updated with the
  patchright swap history.
- `docs/research/competitive-audit.md` §Axis 2 — the
  pre-swap audit that flagged the only fragility point.