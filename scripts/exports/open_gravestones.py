"""Open-burial-data export (issue #95).

Emits one JSON-LD record per matched pensioner to an NDJSON
file, with a `@context` that bundles the canonical open-data
vocabularies for Civil War genealogy:

  - Schema.org/Cemetery (https://schema.org/Cemetery)
  - Schema.org/Person (the deceased)
  - Dublin Core terms (dcterms) — archival metadata
  - WikiTree profile ID (Trtnik-2 / WikiTree+ tool convention)
  - Wikidata Q-items (entity links to the Wikidata knowledge base)
  - W3C PROV-DM (provenance: which run + which policy produced
    each row's decision)

The export is the audit trail, not just the successful subset.
Rows with status=no_candidates OR no rank-1 candidate are still
emitted (with an empty `sameAs` and no WikiTree link) so a
downstream consumer can see what was searched and what was
matched.

Wire format:
  - One JSON object per line (newline-delimited JSON, L5).
  - Each object is valid JSON-LD 1.1 (https://www.w3.org/TR/json-ld/).
  - Optional `wikitree_id` / `wikidata_qid` enrichment is supplied
    by the caller (today: not yet wired to a WikiTree lookup;
    TODO when the lookup table lands).

Public API:
  - build_record(row, *, source_policy_version, run_id,
                 wikitree_id=None, wikidata_qid=None) -> dict
  - run(*, config, run_id, log) -> PostPassStats
  - OpenGravestonesConfig
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

from scripts.post_pass.types import BasePassConfig, PostPassStats


# JSON-LD @context for the export. Single source of truth.
# Bundles six vocabularies; consumers can pick the prefixes they
# understand (JSON-LD @context is a "use what you know" spec).
JSONLD_CONTEXT: dict[str, Any] = {
    "schema": "https://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "wikitree": "https://www.wikitree.com/wiki/",
    "wd": "http://www.wikidata.org/entity/",
    "prov": "http://www.w3.org/ns/prov#",
    # Common JSON-LD type aliases.
    "Person": "schema:Person",
    "Cemetery": "schema:Cemetery",
    "Place": "schema:Place",
}


@dataclass(frozen=True)
class OpenGravestonesConfig(BasePassConfig):
    """Configuration for the open-burial-data export pass.

    `state_path` is the state.jsonl input (one JSON per line).
    `target_path` is the NDJSON output (one JSON-LD per line).
    `wikitree_lookup_path` is an optional CSV `{pensioner_id,
    wikitree_id, wikidata_qid}` used to enrich the export.
    """

    state_path: Path | None = None
    target_path: Path | None = None
    wikitree_lookup_path: Path | None = None


class _LoggerLike(Protocol):
    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...
    def error(self, msg: str, *args: Any) -> None: ...


def _candidate_url(row: dict) -> str | None:
    """Return the FaG memorial URL from the row's top candidate, or None."""
    candidates = row.get("ranked_candidates") or row.get("fag_records") or []
    if not candidates:
        return None
    top = candidates[0]
    url = top.get("url") or top.get("backlink")
    if url:
        return url
    memorial_id = top.get("memorial_id")
    if memorial_id:
        return f"https://www.findagrave.com/memorial/{memorial_id}"
    return None


def _wikidata_qid_for_wikidata_url(qid: str | None) -> str | None:
    """Validate a Wikidata QID (e.g. 'Q12345'); return None if malformed."""
    if not qid:
        return None
    qid = qid.strip()
    if not qid.startswith("Q") or not qid[1:].isdigit():
        return None
    return qid


def _wikitree_profile_url(wikitree_id: str | None) -> str | None:
    """Build a WikiTree profile URL from an ID (Trtnik-2 convention)."""
    if not wikitree_id:
        return None
    wikitree_id = wikitree_id.strip()
    if not wikitree_id:
        return None
    return f"https://www.wikitree.com/wiki/{wikitree_id}"


def build_record(
    row: dict,
    *,
    source_policy_version: str,
    run_id: str,
    wikitree_id: str | None = None,
    wikidata_qid: str | None = None,
) -> dict:
    """Build one JSON-LD record from a state.jsonl row.

    Args:
        row: state.jsonl row (pensioner_id, status, candidates, etc.).
        source_policy_version: policy version that produced `status`.
        run_id: per-run identifier for PROV-DM wasGeneratedBy.
        wikitree_id: optional WikiTree profile ID (Trtnik-2 / WikiTree+
            tool convention; e.g. "Doe-123"). When supplied, emits a
            `wikitree:profile` link.
        wikidata_qid: optional Wikidata Q-item (e.g. "Q12345"). When
            supplied, appends to the sameAs list.

    Returns:
        A JSON-LD dict ready to be JSON-serialized as one line of
        the NDJSON export. The dict is always valid JSON-LD 1.1
        (top-level `@context` + `@type`).
    """
    rec: dict[str, Any] = {
        "@context": dict(JSONLD_CONTEXT),
        "@type": "Person",
        "@id": f"urn:findagravehelper:pensioner:{row.get('pensioner_id', '')}",
        # Dublin Core archival metadata (dcterms).
        "dcterms:identifier": str(row.get("pensioner_app_number", "")),
        "dcterms:title": row.get("pensioner_name", ""),
        "dcterms:source": row.get("pensioncard_backlink", ""),
        "dcterms:date": (
            f"{row.get('pensioner_birth_year', '')}-"
            f"{row.get('pensioner_death_year', '')}"
            if row.get("pensioner_birth_year") or row.get("pensioner_death_year")
            else ""
        ),
        "dcterms:created": row.get("_policy_version", ""),
        # Schema.org Person fields.
        "schema:givenName": row.get("pensioner_first", ""),
        "schema:additionalName": row.get("pensioner_middle", ""),
        "schema:familyName": row.get("pensioner_last", ""),
        "schema:deathDate": str(row.get("pensioner_death_year", "")),
        "schema:birthDate": str(row.get("pensioner_birth_year", "")),
        "schema:status": row.get("status", "unknown"),
        "schema:bestScore": float(row.get("best_score", 0.0) or 0.0),
        "schema:regiment": row.get("regiment", ""),
        "schema:company": row.get("company", ""),
        # W3C PROV-DM provenance.
        "prov:wasGeneratedBy": f"run:{run_id}",
        "prov:wasAttributedTo": (
            f"policy:v{source_policy_version}"
        ),
        "prov:generatedAtTime": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ),
    }

    # FaG memorial URL (Schema.org sameAs convention for "see also").
    fag_url = _candidate_url(row)
    same_as: list[str] = []
    if fag_url:
        same_as.append(fag_url)
    # Wikidata Q-item is also a sameAs (links the deceased to
    # the open knowledge base).
    qid = _wikidata_qid_for_wikidata_url(wikidata_qid)
    if qid:
        same_as.append(f"http://www.wikidata.org/entity/{qid}")
    if same_as:
        rec["sameAs"] = same_as

    # WikiTree profile link (separate from sameAs — it's a research
    # collaboration platform, not an "official" identity).
    wikitree_url = _wikitree_profile_url(wikitree_id)
    if wikitree_url:
        rec["wikitree:profile"] = wikitree_url

    return rec


def _load_wikitree_lookup(
    lookup_path: Path | None,
) -> dict[int, dict[str, str | None]]:
    """Load {pensioner_id: {wikitree_id, wikidata_qid}} from a CSV.

    CSV format: `pensioner_id,wikitree_id,wikidata_qid` (header row
    required). Missing fields are stored as None.
    """
    if lookup_path is None or not lookup_path.exists():
        return {}
    import csv

    out: dict[int, dict[str, str | None]] = {}
    with lookup_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pid = int(row.get("pensioner_id", "") or 0)
            except ValueError:
                continue
            if pid == 0:
                continue
            out[pid] = {
                "wikitree_id": (row.get("wikitree_id") or "").strip() or None,
                "wikidata_qid": (row.get("wikidata_qid") or "").strip() or None,
            }
    return out


def run(
    *,
    config: OpenGravestonesConfig,
    run_id: str,
    log: _LoggerLike,
) -> PostPassStats:
    """Run the open-burial-data export.

    Reads state.jsonl, emits one JSON-LD record per row to the
    target NDJSON. Optional WikiTree/Wikidata enrichment is loaded
    from a CSV sidecar (per-pensioner lookup). Corrupt lines are
    logged and skipped; the pass never aborts the run.

    Args:
        config: Pass config (state_path, target_path,
            wikitree_lookup_path).
        run_id: Run identifier (forwarded to PROV-DM).
        log: Logger for non-fatal warnings.

    Returns:
        PostPassStats with `name="open_gravestones"`. `skipped=True`
        when the state file is missing.
    """
    started = time.monotonic()
    if config.state_path is None or not config.state_path.exists():
        return PostPassStats(
            name="open_gravestones",
            skipped=True,
            duration_s=time.monotonic() - started,
        )
    if config.target_path is None:
        return PostPassStats(
            name="open_gravestones",
            skipped=True,
            duration_s=time.monotonic() - started,
        )

    # Pull the policy version from the first row (assumes the
    # whole run uses one policy). Fall back to "1" if the file
    # is empty or the first row lacks the field.
    policy_version = "1"
    try:
        with config.state_path.open(encoding="utf-8") as f:
            first = f.readline().strip()
        if first:
            first_row = json.loads(first)
            policy_version = str(first_row.get("_policy_version", "1"))
    except (OSError, json.JSONDecodeError):
        pass

    # Load WikiTree / Wikidata lookup (optional).
    lookup = _load_wikitree_lookup(config.wikitree_lookup_path)

    config.target_path.parent.mkdir(parents=True, exist_ok=True)
    matched = 0
    errors = 0
    with config.state_path.open(encoding="utf-8") as src, config.target_path.open(
        "w", encoding="utf-8"
    ) as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning("Skipping corrupt state.jsonl line: %s", exc)
                errors += 1
                continue
            pid = int(row.get("pensioner_id", 0) or 0)
            enrichment = lookup.get(pid, {})
            rec = build_record(
                row,
                source_policy_version=policy_version,
                run_id=run_id,
                wikitree_id=enrichment.get("wikitree_id"),
                wikidata_qid=enrichment.get("wikidata_qid"),
            )
            dst.write(json.dumps(rec, ensure_ascii=False) + "\n")
            matched += 1

    log.info(
        "Wrote %d JSON-LD records to %s (errors=%d)",
        matched,
        config.target_path,
        errors,
    )
    return PostPassStats(
        name="open_gravestones",
        matched=matched,
        errors=errors,
        duration_s=time.monotonic() - started,
    )


def config_from(
    parent: Any,
    *,
    state_path: Path,
    wikitree_lookup_path: Path | None = None,
) -> OpenGravestonesConfig:
    """Build OpenGravestonesConfig from the runner config + run context.

    `state_path` is passed by the runner; the target path defaults
    to `<out_dir>/open_gravestones.ndjson`. The WikiTree lookup is
    optional; when present, enrichment is loaded per row.
    """
    # Default target is a sibling of state.jsonl.
    target = state_path.with_name("open_gravestones.ndjson")
    return OpenGravestonesConfig(
        state_path=state_path,
        target_path=target,
        wikitree_lookup_path=wikitree_lookup_path,
    )


__all__ = [
    "JSONLD_CONTEXT",
    "OpenGravestonesConfig",
    "build_record",
    "config_from",
    "run",
]