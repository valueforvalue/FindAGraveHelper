"""Tests for versioned projection (#98).

Pin:
- ProjectionBuilder rows carry `_schema_version`.
- `state_schema` post-pass emits `state.schema.json` next to
  `state.jsonl` with the canonical field spec.
- A future-shape change can be detected by reading the schema
  and comparing `schema_version` to the consumer's pinned value.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.projection.schema import (
    ROW_FIELDS,
    SCHEMA_VERSION,
    render_schema_json,
)
from scripts.post_pass.state_schema import (
    StateSchemaConfig,
    _schema_path_for,
    run,
)


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


# ============================================================
# schema spec unit tests
# ============================================================


def test_schema_version_is_a_positive_int():
    """SCHEMA_VERSION is a positive int so consumers can compare."""
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION >= 1


def test_render_schema_includes_required_metadata():
    """The rendered schema has the metadata keys view.html needs."""
    s = render_schema_json()
    assert s["schema_version"] == SCHEMA_VERSION
    assert s["row_format"] == "newline-delimited JSON (L5)"
    assert s["policy_version_field"] == "_policy_version"
    assert s["schema_version_field"] == "_schema_version"
    assert isinstance(s["fields"], list)
    assert len(s["fields"]) > 0


def test_every_field_entry_has_required_keys():
    """Every field dict has name, type, required, description."""
    for f in ROW_FIELDS:
        assert "name" in f
        assert "type" in f
        assert "required" in f
        assert "description" in f
        assert isinstance(f["required"], bool)


def test_no_duplicate_field_names():
    """Field names are unique (the schema is a record shape, not a
    list)."""
    names = [f["name"] for f in ROW_FIELDS]
    assert len(names) == len(set(names)), f"Duplicates: {[n for n in names if names.count(n) > 1]}"


def test_required_fields_include_pensioner_id_and_status():
    """The truly required fields are flagged as such so a v1 reader
    can reject rows that lack them."""
    required = {f["name"] for f in ROW_FIELDS if f["required"]}
    assert "pensioner_id" in required
    assert "status" in required
    assert "best_score" in required
    assert "_schema_version" in required


# ============================================================
# ProjectionBuilder integration
# ============================================================


def test_projection_row_carries_schema_version():
    """ProjectionBuilder writes _schema_version on every row."""
    from scripts.blackboard.projector import ProjectionBuilder

    builder = ProjectionBuilder()
    row = builder.build_state_row(
        pensioner_id=42,
        pensioner_data={"first_name": "John", "last_name": "Doe"},
        candidates=[],
    )
    assert "_schema_version" in row
    assert row["_schema_version"] == SCHEMA_VERSION
    assert "_policy_version" in row


# ============================================================
# Post-pass integration
# ============================================================


def test_run_emits_schema_file_next_to_state(tmp_path: Path):
    """`run()` writes state.schema.json next to state.jsonl."""
    state_path = tmp_path / "state.jsonl"
    state_path.write_text("{}\n", encoding="utf-8")
    config = StateSchemaConfig(state_path=state_path)

    stats = run(config=config, log=_NullLogger())

    schema_path = tmp_path / "state.schema.json"
    assert schema_path.exists()
    assert stats.name == "state_schema"
    assert stats.matched == len(ROW_FIELDS)
    assert stats.skipped is False


def test_emitted_schema_is_valid_json_with_field_specs(tmp_path: Path):
    """The emitted file parses as JSON and has the field spec list."""
    state_path = tmp_path / "results.jsonl"
    config = StateSchemaConfig(state_path=state_path)

    run(config=config, log=_NullLogger())

    schema = json.loads((tmp_path / "results.schema.json").read_text(encoding="utf-8"))
    assert "fields" in schema
    field_names = {f["name"] for f in schema["fields"]}
    # Spot-check a few entries that view.html depends on.
    assert "pensioner_id" in field_names
    assert "_schema_version" in field_names
    assert "ranked_candidates" in field_names
    assert "common" in field_names


def test_run_skipped_when_state_path_is_none(tmp_path: Path):
    """No state_path → skipped=True, no file written."""
    config = StateSchemaConfig(state_path=None)
    stats = run(config=config, log=_NullLogger())
    assert stats.skipped is True
    assert stats.matched == 0
    assert not (tmp_path / "state.schema.json").exists()


def test_schema_path_helper():
    """`state.jsonl` → `state.schema.json`."""
    assert (
        _schema_path_for(Path("/tmp/state.jsonl"))
        == Path("/tmp/state.schema.json")
    )
    assert (
        _schema_path_for(Path("/tmp/results.jsonl"))
        == Path("/tmp/results.schema.json")
    )


def test_run_is_idempotent(tmp_path: Path):
    """Re-running overwrites the schema file identically. No duplicate,
    no error."""
    state_path = tmp_path / "state.jsonl"
    state_path.write_text("{}\n", encoding="utf-8")
    config = StateSchemaConfig(state_path=state_path)
    log = _NullLogger()

    first = run(config=config, log=log)
    second = run(config=config, log=log)
    assert first.matched == second.matched
    schema = json.loads((tmp_path / "state.schema.json").read_text(encoding="utf-8"))
    assert schema["schema_version"] == SCHEMA_VERSION