"""Tests for scripts/post_pass/dd.py — Slice 4 + recipe-flag wiring.

Slice 4 acceptance criterion (from
docs/designs/post-pass-extraction.md §Slice 4):
    "After Slice 4 lands, running the runner with
    DIXIEDATA_DB or DIXIEDATA_ZIP_BACKUP set produces DixieDataMatch
    observations in the store identical to before the slice."

Recipe-flag acceptance (post-dd_enabled wiring):
    dd_enabled: true on the RunRecipe must enable the post-pass
    without requiring DIXIEDATA_DB in the environment. dd_db
    provides the path; when unset the default 'dixiedata.db' is
    used. Env vars still take precedence when set.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.blackboard.schema import Kind
from scripts.blackboard.store import SqliteBlackboardStore
from scripts.post_pass.dd import DDConfig, run
from scripts.state.repository import InMemoryStateRepository


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


@pytest.fixture
def sqlite_store(tmp_path):
    store = SqliteBlackboardStore(tmp_path / "bb.db")
    store.open()
    yield store
    store.close()


def test_run_skipped_when_no_db_env(monkeypatch, sqlite_store, tmp_path):
    """No DIXIEDATA_DB / DIXIEDATA_ZIP_BACKUP → skipped=True."""
    monkeypatch.delenv("DIXIEDATA_DB", raising=False)
    monkeypatch.delenv("DIXIEDATA_ZIP_BACKUP", raising=False)
    state_repo = InMemoryStateRepository([{"pensioner_id": 1}])
    config = DDConfig(db_path=None, zip_path=None)

    stats = run(state_repo, sqlite_store, config=config, run_id="r1", log=_NullLogger())

    assert stats.skipped is True
    assert stats.matched == 0


def test_run_skipped_when_index_empty(monkeypatch, sqlite_store, tmp_path):
    """Even with env vars set, an empty index means skipped."""
    monkeypatch.setenv("DIXIEDATA_DB", "/nonexistent/db.sqlite")
    state_repo = InMemoryStateRepository([{"pensioner_id": 1}])
    config = DDConfig(db_path=Path("/nonexistent/db.sqlite"), zip_path=None)

    # Patch load_dd_index to return None
    with patch("scripts.cgr.dixiedata_match.load_dd_index", return_value=None):
        stats = run(
            state_repo, sqlite_store, config=config, run_id="r1", log=_NullLogger()
        )
    assert stats.skipped is True


def test_run_emits_observations_for_matches(monkeypatch, sqlite_store, tmp_path):
    """When _match_pensioner_to_dd returns a dict, observation appended."""
    monkeypatch.setenv("DIXIEDATA_DB", "/fake/db.sqlite")
    state_repo = InMemoryStateRepository(
        [{"pensioner_id": 42, "name_raw": "X"}, {"pensioner_id": 99}]
    )
    config = DDConfig(db_path=Path("/fake/db.sqlite"), zip_path=None)

    fake_index = {"some": "index"}
    match_calls: list[int] = []

    def _fake_match(rec, idx):
        if rec.get("pensioner_id") == 42:
            match_calls.append(rec["pensioner_id"])
            return {"slug": "x-y-z"}
        return None

    with patch(
        "scripts.cgr.dixiedata_match.load_dd_index", return_value=fake_index
    ), patch(
        "scripts.cgr.dixiedata_match._match_pensioner_to_dd",
        side_effect=_fake_match,
    ):
        stats = run(
            state_repo, sqlite_store, config=config, run_id="r1", log=_NullLogger()
        )

    assert stats.matched == 1
    assert stats.skipped is False
    assert match_calls == [42]

    obs = [
        o
        for o in sqlite_store.read_observations_since(None)
        if o.kind == Kind.DixieDataMatch
    ]
    assert len(obs) == 1
    assert obs[0].pensioner_id == 42
    assert obs[0].payload["match_details"] == {"slug": "x-y-z"}


def test_run_skips_records_without_pensioner_id(monkeypatch, sqlite_store):
    """Records with no pensioner_id are skipped (no observation)."""
    monkeypatch.setenv("DIXIEDATA_DB", "/fake/db.sqlite")
    state_repo = InMemoryStateRepository(
        [{"pensioner_id": None, "name_raw": "no-pid"}]
    )
    config = DDConfig(db_path=Path("/fake/db.sqlite"), zip_path=None)

    with patch(
        "scripts.cgr.dixiedata_match.load_dd_index", return_value={"x": 1}
    ), patch(
        "scripts.cgr.dixiedata_match._match_pensioner_to_dd", return_value=None
    ):
        stats = run(
            state_repo, sqlite_store, config=config, run_id="r1", log=_NullLogger()
        )

    assert stats.matched == 0
    assert stats.skipped is False
    assert sqlite_store.read_observations_since(None) == []


def test_run_handles_exception_non_fatal(monkeypatch, sqlite_store, tmp_path):
    """An exception inside load_dd_index is logged, stats reflects error."""
    monkeypatch.setenv("DIXIEDATA_DB", "/fake/db.sqlite")
    state_repo = InMemoryStateRepository([{"pensioner_id": 1}])
    config = DDConfig(db_path=Path("/fake/db.sqlite"), zip_path=None)

    with patch(
        "scripts.cgr.dixiedata_match.load_dd_index",
        side_effect=RuntimeError("db broken"),
    ):
        stats = run(
            state_repo, sqlite_store, config=config, run_id="r1", log=_NullLogger()
        )

    assert stats.errors == 1
    assert stats.skipped is True


def test_run_returns_post_pass_stats(monkeypatch, sqlite_store):
    """Stats object carries name + counts."""
    monkeypatch.setenv("DIXIEDATA_DB", "/fake/db.sqlite")
    state_repo = InMemoryStateRepository([])
    config = DDConfig(db_path=Path("/fake/db.sqlite"), zip_path=None)

    with patch(
        "scripts.cgr.dixiedata_match.load_dd_index", return_value=None
    ):
        stats = run(
            state_repo, sqlite_store, config=config, run_id="r1", log=_NullLogger()
        )
    assert stats.name == "dd"
    assert stats.errors == 0


# ============================================================
# Recipe-flag wiring (dd_enabled + dd_db)
# ============================================================
def test_config_from_recipe_disabled_by_default(monkeypatch):
    """config_from(parent) without dd_enabled=True → no-op DDConfig.

    Recipe flag is OFF by default (preserves Slice 4 behavior: env
    vars were the gate). Without an env override AND without
    dd_enabled, the pass self-skips.
    """
    from scripts.post_pass.dd import config_from
    monkeypatch.delenv("DIXIEDATA_DB", raising=False)
    monkeypatch.delenv("DIXIEDATA_ZIP_BACKUP", raising=False)

    class ParentCfg:
        class post:
            dd_enabled = False
            dd_db = None

    cfg = config_from(ParentCfg())
    assert cfg.db_path is None
    assert cfg.zip_path is None


def test_config_from_recipe_enabled_uses_dd_db(monkeypatch):
    """dd_enabled=True + dd_db='path' → DDConfig wired without env."""
    from scripts.post_pass.dd import config_from
    monkeypatch.delenv("DIXIEDATA_DB", raising=False)
    monkeypatch.delenv("DIXIEDATA_ZIP_BACKUP", raising=False)

    class ParentCfg:
        class post:
            dd_enabled = True
            dd_db = "dixiedata.db"

    cfg = config_from(ParentCfg())
    assert cfg.db_path == Path("dixiedata.db")
    assert cfg.zip_path is None


def test_config_from_env_wins_over_recipe(monkeypatch, tmp_path):
    """Env var DIXIEDATA_DB overrides dd_db when both are set."""
    from scripts.post_pass.dd import config_from
    fake = tmp_path / "env-db.sqlite"
    monkeypatch.setenv("DIXIEDATA_DB", str(fake))

    class ParentCfg:
        class post:
            dd_enabled = True
            dd_db = "dixiedata.db"  # should be ignored

    cfg = config_from(ParentCfg())
    assert cfg.db_path == fake


def test_config_from_recipe_enabled_default_path(monkeypatch):
    """dd_enabled=True with no dd_db → default to 'dixiedata.db'."""
    from scripts.post_pass.dd import config_from
    monkeypatch.delenv("DIXIEDATA_DB", raising=False)
    monkeypatch.delenv("DIXIEDATA_ZIP_BACKUP", raising=False)

    class ParentCfg:
        class post:
            dd_enabled = True
            dd_db = None

    cfg = config_from(ParentCfg())
    assert cfg.db_path == Path("dixiedata.db")


def test_run_with_recipe_flag_emits_matches(monkeypatch, sqlite_store):
    """End-to-end: config_from(recipe) → run() emits DixieDataMatch."""
    from scripts.post_pass.dd import config_from
    monkeypatch.delenv("DIXIEDATA_DB", raising=False)
    monkeypatch.delenv("DIXIEDATA_ZIP_BACKUP", raising=False)

    class ParentCfg:
        class post:
            dd_enabled = True
            dd_db = "/fake/db.sqlite"

    config = config_from(ParentCfg())
    state_repo = InMemoryStateRepository(
        [{"pensioner_id": 42, "name_raw": "X"}]
    )

    with patch(
        "scripts.cgr.dixiedata_match.load_dd_index", return_value={"k": "v"}
    ), patch(
        "scripts.cgr.dixiedata_match._match_pensioner_to_dd",
        return_value={"slug": "x-y"},
    ):
        stats = run(
            state_repo, sqlite_store, config=config,
            run_id="r1", log=_NullLogger(),
        )

    assert stats.skipped is False
    assert stats.matched == 1
    obs = [
        o for o in sqlite_store.read_observations_since(None)
        if o.kind == Kind.DixieDataMatch
    ]
    assert len(obs) == 1