"""Tests for scripts/post_pass/labels.py — Slice 6.

Pin the post-pass extraction: the moved label-collection function
must read the most recent `decisions_*.json` sidecar and append
LabelSnapshots to the configured labels path, identically to the
inline `_collect_labels_if_enabled` in run_unified.py.

Slice 6 acceptance criterion (from
docs/designs/post-pass-extraction.md §Slice 6):
    "After Slice 6 lands, running the runner with a recipe that
    has `post.collect_labels=True` extracts and writes training
    labels identically to before the slice."
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.post_pass.labels import LabelsConfig, run


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


class _FakeRecipe:
    def __init__(self, post):
        self.post = post


class _FakePostConfig:
    def __init__(self, collect_labels: bool, labels_path: Path | None):
        self.collect_labels = collect_labels
        self.labels_path = str(labels_path) if labels_path else None


def _write_decisions_sidecar(path: Path, decisions: dict) -> None:
    payload = {"version": 1, "decisions": decisions}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_run_skipped_when_recipe_none(tmp_path):
    """No recipe → skipped=True."""
    config = LabelsConfig(recipe=None, out_dir=tmp_path)
    stats = run(config=config, log=_NullLogger())
    assert stats.skipped is True


def test_run_skipped_when_collect_labels_false(tmp_path):
    """collect_labels=False → skipped=True."""
    recipe = _FakeRecipe(_FakePostConfig(False, None))
    config = LabelsConfig(recipe=recipe, out_dir=tmp_path)
    stats = run(config=config, log=_NullLogger())
    assert stats.skipped is True


def test_run_skipped_when_no_decisions_sidecar(tmp_path):
    """No decisions_*.json → skipped=True with info log."""
    recipe = _FakeRecipe(_FakePostConfig(True, tmp_path / "labels.jsonl"))
    config = LabelsConfig(recipe=recipe, out_dir=tmp_path)
    stats = run(config=config, log=_NullLogger())
    assert stats.skipped is True


def test_run_appends_labels_to_path(tmp_path):
    """Sidecar found → labels written to labels_path."""
    sidecar = tmp_path / "decisions_2026.json"
    _write_decisions_sidecar(
        sidecar,
        {
            "1": {"decision": {"memorial_id": "memorial-1"}},
            "2": {"decision": {"decision_type": "needs_research"}},
            "3": {"decision": {"memorial_id": None}},
        },
    )
    labels_path = tmp_path / "labels.jsonl"
    recipe = _FakeRecipe(_FakePostConfig(True, labels_path))
    config = LabelsConfig(recipe=recipe, out_dir=tmp_path)

    stats = run(config=config, log=_NullLogger())

    assert stats.matched == 3
    assert labels_path.exists()
    written = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(written) == 3
    decisions = {w["pensioner_id"]: w["human_review_decision"] for w in written}
    assert decisions[1] == "accepted"
    assert decisions[2] == "ambiguous"
    assert decisions[3] == "rejected"


def test_run_uses_most_recent_sidecar(tmp_path):
    """When multiple sidecars exist, the lexicographically newest is used."""
    old = tmp_path / "decisions_2026_07_01.json"
    new = tmp_path / "decisions_2026_07_22.json"
    _write_decisions_sidecar(old, {"1": {"decision": {"memorial_id": "old"}}})
    _write_decisions_sidecar(new, {"2": {"decision": {"memorial_id": "new"}}})
    labels_path = tmp_path / "labels.jsonl"
    recipe = _FakeRecipe(_FakePostConfig(True, labels_path))
    config = LabelsConfig(recipe=recipe, out_dir=tmp_path)

    stats = run(config=config, log=_NullLogger())

    assert stats.matched == 1
    written = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert written[0]["pensioner_id"] == 2


def test_run_handles_exception_non_fatal(tmp_path):
    """Exception from extractor is logged; stats reflects error."""
    sidecar = tmp_path / "decisions_x.json"
    _write_decisions_sidecar(sidecar, {"1": {"decision": {"memorial_id": "x"}}})
    labels_path = tmp_path / "labels.jsonl"
    recipe = _FakeRecipe(_FakePostConfig(True, labels_path))
    config = LabelsConfig(recipe=recipe, out_dir=tmp_path)

    from unittest.mock import patch

    with patch(
        "scripts.learning.label_extractor.LabelExtractor.from_decisions_file",
        side_effect=RuntimeError("extractor broken"),
    ):
        stats = run(config=config, log=_NullLogger())

    assert stats.errors == 1
    assert stats.skipped is True


def test_run_returns_post_pass_stats_shape(tmp_path):
    """Stats object carries name."""
    config = LabelsConfig(recipe=None, out_dir=tmp_path)
    stats = run(config=config, log=_NullLogger())
    assert stats.name == "labels"