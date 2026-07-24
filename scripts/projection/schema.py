"""Projection schema spec — single source of truth for state.jsonl shape.

Issue #98 (versioned projection). The canonical field list lives
here so the schema file (`state.schema.json`) emitted by the
`state_schema` post-pass never drifts from the field set the
`ProjectionBuilder` actually emits.

The list is intentionally verbose (name, type, description) so a
human reader or downstream tooling can interpret the file without
reading the Python code.

When the row shape changes, bump `SCHEMA_VERSION`. Older
`state.jsonl` files are still readable as long as the v1 reader
is the conservative one (drop unknown fields, ignore missing
ones). Future slices can split the row shape into v2/v3 named
groups.
"""
from __future__ import annotations

from typing import Any


# Bump when:
#   - A new field is added to the row (additive change).
#   - An existing field's TYPE changes (breaking change).
#   - A field is renamed (breaking change; keep the old name too
#     and deprecate in the same version if you want to be
#     conservative).
SCHEMA_VERSION: int = 2


# Field-level spec. Add new entries here; don't remove or rename
# without bumping SCHEMA_VERSION.
ROW_FIELDS: list[dict[str, Any]] = [
    {
        "name": "pensioner_id",
        "type": "int",
        "required": True,
        "description": "Stable pensioner identifier (issue #14).",
    },
    {
        "name": "pensioner_name",
        "type": "str",
        "required": True,
        "description": "'last, first' name format. v2 view derives display name from this.",
    },
    {
        "name": "status",
        "type": "str",
        "required": True,
        "description": "Decision status: auto_accept, needs_review, low_score, no_candidates, ambiguous, error. Canonical values in scripts.pipeline.scoring_constants.",
    },
    {
        "name": "best_score",
        "type": "float",
        "required": True,
        "description": "Top score across ranked_candidates in [0, 1].",
    },
    {
        "name": "ranked_candidates",
        "type": "list[dict]",
        "required": True,
        "description": "Engine-specific scored candidates (FaG or Newspapers). See `common.candidates` for the engine-agnostic projection.",
    },
    {
        "name": "fag_records",
        "type": "list[dict]",
        "required": True,
        "description": "FaG-shaped duplicate of ranked_candidates (back-compat with v1 view consumers).",
    },
    {
        "name": "_policy_version",
        "type": "str",
        "required": True,
        "description": "DecisionPolicy version that produced the status field. Versioned per CONTEXT.md so a replay can recover the exact rule.",
    },
    {
        "name": "_schema_version",
        "type": "int",
        "required": True,
        "description": "Projection schema version (this file's source of truth). v2+; absent means v1 (legacy).",
    },
    {
        "name": "badges",
        "type": "list[str]",
        "required": True,
        "description": "Corroboration badges: cgr_match, spouse_match, dd_match. Computed by ProjectionBuilder from observations.",
    },
    {
        "name": "common",
        "type": "dict",
        "required": True,
        "description": "Engine-agnostic projection (issue #39). Carries id, title, engine, status, best_score, candidates, corroboration.",
    },
    {
        "name": "pensioner_first",
        "type": "str",
        "required": False,
        "description": "First name. v1 names: pensioner_-prefixed; the row may also carry the un-prefixed first_name.",
    },
    {
        "name": "pensioner_middle",
        "type": "str",
        "required": False,
        "description": "Middle name or initial.",
    },
    {
        "name": "pensioner_last",
        "type": "str",
        "required": False,
        "description": "Last name.",
    },
    {
        "name": "pensioner_app_number",
        "type": "str",
        "required": False,
        "description": "Application number from the OK pensioners record.",
    },
    {
        "name": "pensioner_birth_year",
        "type": "int",
        "required": False,
        "description": "Birth year if known.",
    },
    {
        "name": "pensioner_death_year",
        "type": "int",
        "required": False,
        "description": "Death year if known.",
    },
    {
        "name": "regiment",
        "type": "str",
        "required": False,
        "description": "CW regiment from the pensioner record.",
    },
    {
        "name": "company",
        "type": "str",
        "required": False,
        "description": "CW company letter.",
    },
    {
        "name": "pensioncard_backlink",
        "type": "str",
        "required": False,
        "description": "URL back to the digitalprairie.ok.gov pension card.",
    },
    {
        "name": "pensioncard_iiif_url",
        "type": "str",
        "required": False,
        "description": "IIIF image URL for the pension card.",
    },
    {
        "name": "pensioncard_pages",
        "type": "list[str]",
        "required": False,
        "description": "IIIF page IDs (issue #62). v2 view builds IIIF URLs from these.",
    },
    {
        "name": "pensioner_spouse_first",
        "type": "str",
        "required": False,
        "description": "Spouse first name (widow cross-reference).",
    },
    {
        "name": "pensioner_spouse_middle",
        "type": "str",
        "required": False,
        "description": "Spouse middle name.",
    },
    {
        "name": "pensioner_spouse_last",
        "type": "str",
        "required": False,
        "description": "Spouse last name.",
    },
    {
        "name": "backlink",
        "type": "str",
        "required": False,
        "description": "URL back to the pensioner record itself (not the candidate).",
    },
    {
        "name": "cgr_match",
        "type": "dict",
        "required": False,
        "description": "CGR corroboration evidence. Populated by the observation_enrichment post-pass.",
    },
    {
        "name": "dd_match",
        "type": "dict",
        "required": False,
        "description": "DixieData match evidence. Populated by the observation_enrichment post-pass.",
    },
    {
        "name": "spouse_match",
        "type": "dict",
        "required": False,
        "description": "Spouse cross-reference evidence. Populated by the observation_enrichment post-pass.",
    },
]


def render_schema_json() -> dict[str, Any]:
    """Render the schema as a dict suitable for JSON serialization.

    Shape:
        {
          "schema_version": int,
          "row_format": "newline-delimited JSON (L5)",
          "fields": [ {name, type, required, description}, ... ],
          "policy_version_field": "_policy_version",
          "schema_version_field": "_schema_version",
        }
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "row_format": "newline-delimited JSON (L5)",
        "fields": list(ROW_FIELDS),
        "policy_version_field": "_policy_version",
        "schema_version_field": "_schema_version",
    }


__all__ = ["ROW_FIELDS", "SCHEMA_VERSION", "render_schema_json"]