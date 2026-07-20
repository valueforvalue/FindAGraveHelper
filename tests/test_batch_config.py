"""Tests for J5-S1: batch config.json + init-batch subcommand.

RED tests written first per tdd.md. Each test pins one acceptance
criterion from the feature spec. No browser / Playwright required.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.batch_config import (  # noqa: E402
    BatchConfig,
    ConfigError,
    init_batch,
    load_config,
    validate_config_against_dir,
)
from scripts.pipeline.scoring_constants import (  # noqa: E402
    LOW_SCORE_THRESHOLD,
)


# ============================================================
# init-batch subcommand
# ============================================================
def test_init_batch_writes_config_template(tmp_path, monkeypatch):
    """init-batch <runname> creates output/<runname>/config.json with defaults."""
    monkeypatch.chdir(tmp_path)
    created = init_batch("foo")

    expected = tmp_path / "output" / "foo" / "config.json"
    assert created == expected
    assert expected.exists()

    cfg = json.loads(expected.read_text(encoding="utf-8"))
    # v2 RunRecipe shape (issue #55)
    assert cfg["version"] == 2
    assert cfg["runname"] == "foo"
    assert "pensioners" in cfg["inputs"]
    assert "cgr" in cfg["inputs"]
    assert cfg["engine"]["throttle"] == 2.5
    assert cfg["engine"]["state_filter"] == "OK"
    assert cfg["pipeline"]["scoring"]["method"] == "weighted"
    assert cfg["pipeline"]["strategies"]["order"] == "fixed"
    assert cfg["post"]["collect_labels"] is True


def test_init_batch_creates_dir_layout(tmp_path, monkeypatch):
    """init-batch creates output/<runname>/ with config.json inside."""
    monkeypatch.chdir(tmp_path)
    init_batch("bar")
    assert (tmp_path / "output" / "bar").is_dir()
    assert (tmp_path / "output" / "bar" / "config.json").is_file()


def test_init_batch_rejects_existing_dir(tmp_path, monkeypatch):
    """init-batch refuses to clobber an existing run dir (no accidental overwrite)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output" / "foo").mkdir(parents=True)
    with pytest.raises(ConfigError, match="already exists"):
        init_batch("foo")


def test_init_batch_rejects_bad_runname(tmp_path, monkeypatch):
    """Non-slug runnames (spaces, uppercase, leading hyphen) are rejected."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="invalid runname"):
        init_batch("Bad Name")
    with pytest.raises(ConfigError, match="invalid runname"):
        init_batch("FOO")
    with pytest.raises(ConfigError, match="invalid runname"):
        init_batch("-leading-hyphen")


def test_init_batch_accepts_various_slugs(tmp_path, monkeypatch):
    """Hyphens, digits, underscores in runname are accepted."""
    monkeypatch.chdir(tmp_path)
    for slug in ("a", "abc", "with-hyphens", "x1", "two_words"):
        init_batch(slug)
        assert (tmp_path / "output" / slug / "config.json").exists()


# ============================================================
# load_config round-trip
# ============================================================
def test_load_config_round_trip(tmp_path):
    """Config dict → JSON file → BatchConfig dataclass → all keys preserved."""
    cfg_path = tmp_path / "config.json"
    raw = {
        "runname": "test-run",
        "input": "docs/research/digitalprairie/ok_pensioners.json",
        "cgr": "docs/research/cgr/ok_vets_enriched.jsonl",
        "start_row": 100,
        "end_row": 500,
        "throttle": 3.0,
        "low_score_threshold": 0.45,
        "fag_state_filter": "OK",
    }
    cfg_path.write_text(json.dumps(raw), encoding="utf-8")

    cfg = load_config(cfg_path)
    # v1 auto-upgrades to RunRecipe (issue #55)
    from scripts.batch_config import RunRecipe
    assert isinstance(cfg, RunRecipe)
    assert cfg.runname == "test-run"
    assert cfg.inputs.pensioners == Path("docs/research/digitalprairie/ok_pensioners.json")
    assert cfg.inputs.cgr == Path("docs/research/cgr/ok_vets_enriched.jsonl")
    assert cfg.inputs.start_row == 100
    assert cfg.inputs.end_row == 500
    assert cfg.engine.throttle == 3.0
    assert cfg.engine.state_filter == "OK"
    # Backward-compat properties still work
    assert cfg.throttle == 3.0
    assert cfg.fag_state_filter == "OK"
    assert cfg.input_path == Path("docs/research/digitalprairie/ok_pensioners.json")


def test_load_config_minimal_required(tmp_path):
    """Only runname + input + cgr are required; rest have defaults."""
    cfg_path = tmp_path / "config.json"
    raw = {
        "runname": "minimal",
        "input": "data/x.json",
        "cgr": "data/x.jsonl",
    }
    cfg_path.write_text(json.dumps(raw), encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.runname == "minimal"
    # Backward-compat properties on RunRecipe (v1 auto-upgrade)
    assert cfg.start_row == 0
    assert cfg.end_row is None
    assert cfg.throttle == 2.5
    # Default state filter
    assert cfg.fag_state_filter == "OK"


def test_load_config_missing_required_key(tmp_path):
    """Missing runname / input / cgr → ConfigError."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"runname": "x", "input": "i"}),
                       encoding="utf-8")
    with pytest.raises(ConfigError, match="cgr"):
        load_config(cfg_path)


def test_load_config_bad_json(tmp_path):
    """Unparseable JSON → ConfigError."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{not valid", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(cfg_path)


def test_load_config_type_coercion_safe(tmp_path):
    """v2 RunRecipe coerces numeric strings (float cast is safe)."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "runname": "x",
        "input": "i",
        "cgr": "c",
        "throttle": "3.0",  # string is cast to float in v2
    }), encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.engine.throttle == 3.0


# ============================================================
# validate_config_against_dir
# ============================================================
def test_validate_config_against_dir_match(tmp_path):
    """Config runname matches out_dir basename → ok."""
    out_dir = tmp_path / "output" / "foo"
    out_dir.mkdir(parents=True)
    cfg = BatchConfig(
        runname="foo",
        input_path=Path("i"),
        cgr_path=Path("c"),
        start_row=0,
        end_row=None,
        throttle=2.5,
        low_score_threshold=LOW_SCORE_THRESHOLD,
    )
    # Should not raise
    validate_config_against_dir(cfg, out_dir)


def test_config_validates_runname_matches_dir(tmp_path):
    """Config runname="bar" inside output/foo/ → ConfigError."""
    out_dir = tmp_path / "output" / "foo"
    out_dir.mkdir(parents=True)
    cfg = BatchConfig(
        runname="bar",
        input_path=Path("i"),
        cgr_path=Path("c"),
        start_row=0,
        end_row=None,
        throttle=2.5,
        low_score_threshold=LOW_SCORE_THRESHOLD,
    )
    with pytest.raises(ConfigError, match="runname.*bar.*dir.*foo"):
        validate_config_against_dir(cfg, out_dir)


# ============================================================
# Slug validation (used by init_batch)
# ============================================================
def test_runname_is_slug_property():
    """BatchConfig.runname_is_slug returns True for valid, False for invalid."""
    valid = BatchConfig(
        runname="abc-def_123",
        input_path=Path("i"),
        cgr_path=Path("c"),
        start_row=0,
        end_row=None,
        throttle=2.5,
        low_score_threshold=LOW_SCORE_THRESHOLD,
    )
    assert valid.runname_is_slug() is True

    invalid = BatchConfig(
        runname="Bad Name",
        input_path=Path("i"),
        cgr_path=Path("c"),
        start_row=0,
        end_row=None,
        throttle=2.5,
        low_score_threshold=LOW_SCORE_THRESHOLD,
    )
    assert invalid.runname_is_slug() is False


# ============================================================
# RunManifest bridge tests (Phase 2 Slice 2.1)
# ============================================================


def test_build_manifest_includes_policy_version():
    """build_manifest records the supplied policy version."""
    from scripts.batch_config import build_manifest, BatchConfig
    from pathlib import Path

    cfg = BatchConfig(
        runname="test-build-manifest",
        input_path=Path("input.jsonl"),
        cgr_path=Path("cgr.jsonl"),
    )
    m = build_manifest(cfg, policy_version="2")
    assert m.policy_version == "2"
    assert m.run_id == "test-build-manifest"


def test_manifest_roundtrip():
    """RunManifest survives to_dict() → from_dict() round-trip."""
    from scripts.batch_config import build_manifest, BatchConfig
    from scripts.blackboard.schema import RunManifest
    from pathlib import Path

    cfg = BatchConfig(
        runname="test-roundtrip",
        input_path=Path("input.jsonl"),
        cgr_path=Path("cgr.jsonl"),
    )
    original = build_manifest(cfg, policy_version="3",
                              knowledge_source_versions={"FaGScraper": "1.0"})
    d = original.to_dict()
    restored = RunManifest.from_dict(d)
    assert restored.manifest_id == original.manifest_id
    assert restored.run_id == original.run_id
    assert restored.policy_version == original.policy_version
    assert restored.knowledge_source_versions == original.knowledge_source_versions