"""Deterministic observation ID helper (L11).

L11 (CONTEXT.md): every observation carries a deterministic ID derived
from its payload, so resume + replay do not see duplicate observations.

Slice 1 (Q1 locked decision): post-pass observation IDs are derived from
`sha256(kind|pensioner_id|source|source_version|run_id|pass_id)[:12]`,
prefixed with `obs-{kind_tag}-`. The kind tag (`cgr`, `dd`, `spouse`)
keeps the existing prefix convention used by downstream consumers.
"""
from __future__ import annotations

import hashlib

# Map Kind enum values to short tags for the observation_id prefix.
_KIND_TAG = {
    "CGRCorroboration": "cgr",
    "DixieDataMatch": "dd",
    "SpouseMatch": "spouse",
}


def deterministic_observation_id(
    *,
    kind: str,
    pensioner_id: int,
    source: str,
    source_version: str,
    run_id: str,
    pass_id: str,
) -> str:
    """Return a deterministic observation ID per L11.

    Args:
        kind: Observation kind (matches `Kind.value` enum strings).
        pensioner_id: Pensioner the observation is about.
        source: Producer identifier (e.g. "cgr_fag_dedup").
        source_version: Producer's version stamp.
        run_id: Per-run identifier (lets the same input reproduce
            distinct IDs across runs).
        pass_id: Per-pass identifier within a run (e.g. "post").

    Returns:
        `obs-{tag}-{12hex}` where tag is the kind's short identifier
        and 12hex is the first 12 hex chars of sha256 over the
        pipe-joined payload fields.
    """
    tag = _KIND_TAG.get(kind, "x")
    payload = "|".join(
        [
            str(kind),
            str(int(pensioner_id)),
            str(source),
            str(source_version),
            str(run_id),
            str(pass_id),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"obs-{tag}-{digest}"